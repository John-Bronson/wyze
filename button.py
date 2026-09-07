from gpiozero import Button
from signal import pause
import os
import sys
import time
from wyze_sdk.errors import WyzeApiError, WyzeClientError
from dotenv import load_dotenv
import json

# Load environment variables before anything reads them.
load_dotenv()

from concurrent.futures import ThreadPoolExecutor

from logging_setup import setup_logging
import wyze_keepalive

logger = setup_logging("button")
logger.info("starting button.py")
wyze_keepalive.enable()

# One long-lived pool, deliberately not per-press: wyze_keepalive keeps a warm
# HTTPS connection per thread, and reusing the same threads keeps those
# connections alive between button presses. Capped well below the device count
# to stay polite to Wyze's API.
MAX_PARALLEL = 6
_pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL, thread_name_prefix="wyze")


def _in_pool(fn, *args):
    """Run one call on a pool thread, so it uses a warm connection."""
    return _pool.submit(fn, *args).result()


def _map_pool(fn, items):
    """Run fn over items concurrently, preserving order. Exceptions come back
    as the result so one failure cannot abandon the rest of the group."""
    futures = [_pool.submit(fn, item) for item in items]
    results = []
    for future in futures:
        try:
            results.append(future.result())
        except Exception as err:  # logged by the caller alongside its device
            results.append(err)
    return results

# WyzeClientError is not a subclass of WyzeApiError. Catching only the latter
# is what let a failed token refresh kill this process outright, leaving
# systemd to restart it every few seconds indefinitely.
WYZE_ERRORS = (WyzeApiError, WyzeClientError)

try:
    from token_manager import token_manager
    from button_config import button_config
    logger.info("token manager and button config imported")
except Exception as e:
    logger.exception("import error: %s", e)
    sys.exit(1)

try:
    button = Button(4, bounce_time=0.1)
    logger.info("GPIO button initialized on pin 4")
except Exception as e:
    logger.exception("GPIO button error: %s", e)
    logger.error("if this is a permissions problem, try: sudo .venv/bin/python button.py")
    sys.exit(1)


class FlaskIntegratedButtonController:
    def __init__(self):
        self.client = None
        self.last_press_time = 0
        self.debounce_delay = 1.0  # Prevent accidental double-presses
        self.busy = False          # a group toggle takes seconds; ignore re-entry
        self.initialize()

    def initialize(self):
        """Initialize Wyze client"""
        try:
            logger.info("initializing Wyze connection")
            self.client = token_manager.get_client()
            logger.info("Wyze client ready; %s", token_manager.status())
        except (WyzeApiError, WyzeClientError, EnvironmentError) as e:
            logger.error("failed to initialize Wyze client: %s: %s",
                         type(e).__name__, e)
            sys.exit(1)

    def get_target_devices(self):
        """Resolve the configured button group to live, online devices.

        Re-read from disk each press so changes made in the web interface take
        effect without restarting this daemon.
        """
        button_config.reload()
        configured = button_config.get_button_devices()
        if not configured:
            logger.warning("no devices configured for button control; "
                           "set a group in the web interface")
            return []

        try:
            # Re-fetch the client each press so an expired token is refreshed
            # rather than reused from startup.
            self.client = token_manager.get_client()
            devices = _in_pool(self.client.devices_list)
        except WYZE_ERRORS as e:
            logger.error("error getting device list: %s: %s", type(e).__name__, e)
            return []

        by_mac = {d.mac: d for d in devices}
        targets = []
        for entry in configured:
            device = by_mac.get(entry["mac"])
            if device is None:
                logger.error("configured device %s (%s) not found in account",
                             entry.get("nickname"), entry["mac"])
            elif not device.is_online:
                logger.warning("skipping %s: device is offline", device.nickname)
            else:
                targets.append(device)

        logger.info("button group: %d of %d configured device(s) usable",
                    len(targets), len(configured))
        return targets

    def get_device_state(self, device):
        """Current on/off state of one device, or None if it cannot be read."""
        try:
            if device.type == 'Plug':
                return self.client.plugs.info(device_mac=device.mac).is_on
            if device.type in ['MeshLight', 'Bulb', 'Light']:
                return self.client.bulbs.info(device_mac=device.mac).is_on
            logger.warning("unknown device type %s for %s; excluding it from "
                           "the vote", device.type, device.nickname)
            return None
        except WYZE_ERRORS as e:
            logger.error("could not read state of %s (%s: %s); excluding it "
                         "from the vote", device.nickname, type(e).__name__, e)
            return None

    def _controller_for(self, device):
        return {
            'Plug': self.client.plugs,
            'MeshLight': self.client.bulbs,
            'Bulb': self.client.bulbs,
            'Light': self.client.bulbs,
        }.get(device.type)

    def decide_action(self, states):
        """Majority vote: move the group to whichever state most are NOT in.

        `states` is a list of booleans, one per device we could read. A tie
        turns everything on - pressing a light switch and getting light is the
        friendlier outcome.
        """
        on_count = sum(1 for state in states if state)
        off_count = len(states) - on_count
        action = "off" if on_count > off_count else "on"
        logger.info("group vote: %d on, %d off -> turning all %s%s",
                    on_count, off_count, action.upper(),
                    " (tie)" if on_count == off_count else "")
        return action

    def toggle_device(self):
        """Toggle every device in the group to a single, shared state."""
        current_time = time.time()
        if current_time - self.last_press_time < self.debounce_delay:
            logger.debug("button press ignored (debounce)")
            return
        if self.busy:
            logger.info("button press ignored: previous group toggle still running")
            return

        self.last_press_time = current_time
        self.busy = True
        started = time.monotonic()
        try:
            logger.info("button pressed")
            devices = self.get_target_devices()
            if not devices:
                return

            read_started = time.monotonic()
            outcomes = _map_pool(self.get_device_state, devices)
            states = []
            readable = []
            for device, state in zip(devices, outcomes):
                if isinstance(state, Exception):
                    logger.error("  could not read %s: %s: %s", device.nickname,
                                 type(state).__name__, state)
                    continue
                if state is None:
                    continue
                logger.info("  %s is %s", device.nickname, "ON" if state else "OFF")
                states.append(state)
                readable.append(device)
            logger.info("read %d device state(s) in %.1fs", len(states),
                        time.monotonic() - read_started)

            if not states:
                logger.error("could not read the state of any device in the "
                             "group; doing nothing")
                return

            action = self.decide_action(states)

            def apply(device):
                controller = self._controller_for(device)
                if not controller:
                    raise ValueError(f"unsupported device type {device.type}")
                command = controller.turn_on if action == "on" else controller.turn_off
                command(device_mac=device.mac, device_model=device.product.model)
                return True

            write_started = time.monotonic()
            succeeded = 0
            for device, outcome in zip(readable, _map_pool(apply, readable)):
                if isinstance(outcome, Exception):
                    logger.error("  failed to turn %s %s: %s: %s", action,
                                 device.nickname, type(outcome).__name__, outcome)
                else:
                    logger.info("  %s is now %s", device.nickname, action.upper())
                    succeeded += 1
            logger.info("applied %d change(s) in %.1fs", succeeded,
                        time.monotonic() - write_started)

            logger.info("group toggle complete: %d/%d device(s) turned %s in %.1fs",
                        succeeded, len(readable), action.upper(),
                        time.monotonic() - started)
        except Exception as e:
            logger.exception("unexpected error during group toggle: %s", e)
        finally:
            self.busy = False

    def show_status(self):
        """Log the current button group at startup."""
        configured = button_config.get_button_devices()
        if not configured:
            logger.warning("no devices configured for button control; "
                           "configure a group in the web interface")
            return

        logger.info("button group has %d device(s): %s", len(configured),
                    ", ".join(d.get("nickname", d["mac"]) for d in configured))
        devices = self.get_target_devices()
        for device in devices:
            state = self.get_device_state(device)
            logger.info("  %s: %s", device.nickname,
                        "unknown" if state is None else ("ON" if state else "OFF"))


try:
    controller = FlaskIntegratedButtonController()
except SystemExit:
    raise
except Exception as e:
    logger.exception("controller creation failed: %s", e)
    sys.exit(1)

try:
    controller.show_status()
except Exception as e:
    logger.exception("error showing status: %s", e)

try:
    button.when_pressed = controller.toggle_device
    logger.info("button handler attached; press the button to toggle the "
                "configured group")
except Exception as e:
    logger.exception("button handler error: %s", e)
    sys.exit(1)

try:
    pause()
except KeyboardInterrupt:
    logger.info("shutting down")
except Exception as e:
    logger.exception("main loop error: %s", e)
