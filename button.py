from gpiozero import Button
from signal import pause
import os
import sys
import time
from wyze_sdk.errors import WyzeApiError
from dotenv import load_dotenv

# Import your existing modules
from token_manager import token_manager
from button_config import button_config

# Load environment variables
load_dotenv()

button = Button(4, bounce_time=0.1)


class FlaskIntegratedButtonController:
    def __init__(self):
        self.client = None
        self.device_state = False  # Track current state for toggling
        self.last_press_time = 0
        self.debounce_delay = 1.0  # Prevent accidental double-presses
        self.initialize()

    def initialize(self):
        """Initialize Wyze client"""
        try:
            print(" Initializing Wyze connection...")
            self.client = token_manager.get_client()
            print("✅ Wyze client initialized successfully!")
        except (WyzeApiError, EnvironmentError) as e:
            print(f"❌ Failed to initialize Wyze client: {e}")
            sys.exit(1)

    def get_target_device(self):
        """Get the currently configured button device from the config"""
        button_device_config = button_config.get_button_device()
        if not button_device_config:
            print("⚠️  No device configured for button control")
            print("   Use the Flask web interface to set a button device")
            return None

        try:
            devices = self.client.devices_list()
            device = next((d for d in devices if d.mac == button_device_config['mac']), None)

            if not device:
                print(f"❌ Configured device {button_device_config['nickname']} not found")
                return None

            if not device.is_online:
                print(f"⚠️  Device {device.nickname} is offline")
                return None

            return device

        except WyzeApiError as e:
            print(f"❌ Error getting device list: {e}")
            return None

    def toggle_device(self):
        """Toggle the configured button device"""
        current_time = time.time()
        if current_time - self.last_press_time < self.debounce_delay:
            print("⏱️  Button press ignored (debounce)")
            return

        self.last_press_time = current_time

        # Get current target device from configuration
        device = self.get_target_device()
        if not device:
            return

        try:
            action = "on" if not self.device_state else "off"
            print(f" Turning {action} {device.nickname}...")

            # Determine controller type
            device_controllers = {
                'Plug': self.client.plugs,
                'MeshLight': self.client.bulbs,
                'Bulb': self.client.bulbs,
                'Light': self.client.bulbs
            }

            controller = device_controllers.get(device.type)
            if not controller:
                print(f"❌ Unsupported device type: {device.type}")
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

            self.device_state = not self.device_state
            status_emoji = "" if self.device_state else ""
            print(f"{status_emoji} {device.nickname} is now {action.upper()}")

        except WyzeApiError as e:
            print(f"❌ Error controlling device: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

    def show_status(self):
        """Show current button configuration status"""
        button_device_config = button_config.get_button_device()
        if button_device_config:
            print(f" Button configured for: {button_device_config['nickname']}")
            print(f" MAC: {button_device_config['mac']}")

            device = self.get_target_device()
            if device:
                print(f"✅ Device is online and ready")
            else:
                print("⚠️  Device is not available")
        else:
            print("⚠️  No device configured for button control")
            print("   Visit the Flask web interface to configure a device")


# Initialize controller
controller = FlaskIntegratedButtonController()

# Show initial status
print(" Flask-Integrated GPIO Button Controller")
print("=" * 50)
controller.show_status()
print("=" * 50)

# Set up button handler
button.when_pressed = controller.toggle_device

print(" Press the button to toggle your configured device")
print(" Visit the Flask app to change button configuration")
print("⌨️  Press Ctrl+C to exit")

try:
    pause()
except KeyboardInterrupt:
    print("\n Shutting down...")
