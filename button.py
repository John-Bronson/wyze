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

from logging_setup import setup_logging

logger = setup_logging("button")
logger.info("starting button.py")

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

    def get_target_device(self):
        """Get the currently configured button device from the config (fresh each time)"""
        # Read JSON file directly to ensure fresh data
        try:
            with open('button_config.json', 'r') as file:
                config_data = json.load(file)
            button_device_config = config_data.get('button_device')
        except FileNotFoundError:
            logger.warning("button_config.json not found")
            return None
        except json.JSONDecodeError:
            logger.warning("invalid JSON in button_config.json")
            return None

        if not button_device_config:
            logger.warning("no device configured for button control; "
                           "set one in the web interface")
            return None

        try:
            # Re-fetch the client each press so an expired token is refreshed
            # rather than reused from startup.
            self.client = token_manager.get_client()
            devices = self.client.devices_list()
            device = next((d for d in devices if d.mac == button_device_config['mac']), None)

            if not device:
                logger.error("configured device %s (%s) not found in account",
                             button_device_config['nickname'], button_device_config['mac'])
                return None

            if not device.is_online:
                logger.warning("device %s is offline", device.nickname)
                return None

            return device

        except WYZE_ERRORS as e:
            logger.error("error getting device list: %s: %s", type(e).__name__, e)
            return None

    def get_device_state(self, device):
        """Get the current state of the device"""
        try:
            logger.debug("checking current state of %s", device.nickname)

            # Different device types have different state properties
            if device.type == 'Plug':
                # For plugs, get detailed info including state
                plug_info = self.client.plugs.info(device_mac=device.mac)
                is_on = plug_info.is_on
            elif device.type in ['MeshLight', 'Bulb', 'Light']:
                # For bulbs, get detailed info including state
                bulb_info = self.client.bulbs.info(device_mac=device.mac)
                is_on = bulb_info.is_on
            else:
                logger.warning("unknown device type %s, assuming OFF", device.type)
                return False

            logger.info("%s is currently %s", device.nickname, "ON" if is_on else "OFF")
            return is_on

        except WYZE_ERRORS as e:
            logger.error("error getting device state (%s: %s); assuming OFF",
                         type(e).__name__, e)
            return False

    def toggle_device(self):
        """Toggle the configured button device based on its current state"""
        current_time = time.time()
        if current_time - self.last_press_time < self.debounce_delay:
            logger.debug("button press ignored (debounce)")
            return

        self.last_press_time = current_time
        logger.info("button pressed")

        # Get current target device from configuration (fresh each time)
        device = self.get_target_device()
        if not device:
            return

        try:
            # Get the actual current state of the device
            current_state = self.get_device_state(device)

            # Toggle to opposite state
            action = "off" if current_state else "on"
            logger.info("turning %s %s", action.upper(), device.nickname)

            # Determine controller type
            device_controllers = {
                'Plug': self.client.plugs,
                'MeshLight': self.client.bulbs,
                'Bulb': self.client.bulbs,
                'Light': self.client.bulbs
            }

            controller = device_controllers.get(device.type)
            if not controller:
                logger.error("unsupported device type: %s", device.type)
                return

            # Execute command
            if action == "on":
                controller.turn_on(
                    device_mac=device.mac,
                    device_model=device.product.model
                )
            else:
                controller.turn_off(
                    device_mac=device.mac,
                    device_model=device.product.model
                )

            logger.info("%s is now %s", device.nickname, action.upper())

        except WYZE_ERRORS as e:
            logger.error("error controlling device: %s: %s", type(e).__name__, e)
        except Exception as e:
            logger.exception("unexpected error controlling device: %s", e)

    def show_status(self):
        """Show current button configuration status"""
        button_device_config = button_config.get_button_device()
        if not button_device_config:
            logger.warning("no device configured for button control; "
                           "configure one in the web interface")
            return

        logger.info("button configured for %s (%s)",
                    button_device_config['nickname'], button_device_config['mac'])
        device = self.get_target_device()
        if device:
            state = self.get_device_state(device)
            logger.info("device is online and ready, currently %s",
                        "ON" if state else "OFF")
        else:
            logger.warning("configured device is not available")


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
                "configured device")
except Exception as e:
    logger.exception("button handler error: %s", e)
    sys.exit(1)

try:
    pause()
except KeyboardInterrupt:
    logger.info("shutting down")
except Exception as e:
    logger.exception("main loop error: %s", e)
