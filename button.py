from gpiozero import Button
from signal import pause
import os
import sys
import time
from wyze_sdk.errors import WyzeApiError
from dotenv import load_dotenv
import json

print("🔧 Starting button.py...")

# Load environment variables
load_dotenv()
print("🔧 Environment loaded")

# Import your existing modules
try:
    from token_manager import token_manager
    print("🔧 Token manager imported")
    from button_config import button_config
    print("🔧 Button config imported")
except Exception as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

print("🔧 Initializing GPIO button...")
try:
    button = Button(4, bounce_time=0.1)
    print("✅ GPIO button initialized")
except Exception as e:
    print(f"❌ GPIO button error: {e}")
    print("💡 Try running with: sudo .venv/bin/python button.py")
    sys.exit(1)


class FlaskIntegratedButtonController:
    def __init__(self):
        print("🔧 Initializing FlaskIntegratedButtonController...")
        self.client = None
        self.last_press_time = 0
        self.debounce_delay = 1.0  # Prevent accidental double-presses
        self.initialize()

    def initialize(self):
        """Initialize Wyze client"""
        try:
            print("🚀 Initializing Wyze connection...")
            self.client = token_manager.get_client()
            print("✅ Wyze client initialized successfully!")
        except (WyzeApiError, EnvironmentError) as e:
            print(f"❌ Failed to initialize Wyze client: {e}")
            sys.exit(1)

    def get_target_device(self):
        """Get the currently configured button device from the config (fresh each time)"""
        # Read JSON file directly to ensure fresh data
        try:
            with open('button_config.json', 'r') as file:
                config_data = json.load(file)
            button_device_config = config_data.get('button_device')
        except FileNotFoundError:
            print("⚠️  button_config.json not found")
            return None
        except json.JSONDecodeError:
            print("⚠️  Invalid JSON in button_config.json")
            return None

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

    def get_device_state(self, device):
        """Get the current state of the device"""
        try:
            print(f"🔍 Checking current state of {device.nickname}...")

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
                print(f"⚠️  Unknown device type {device.type}, assuming OFF")
                return False

            state_text = "ON" if is_on else "OFF"
            print(f"💡 {device.nickname} is currently {state_text}")
            return is_on

        except WyzeApiError as e:
            print(f"❌ Error getting device state: {e}")
            print("🔄 Assuming device is OFF for toggle logic")
            return False

    def toggle_device(self):
        """Toggle the configured button device based on its current state"""
        current_time = time.time()
        if current_time - self.last_press_time < self.debounce_delay:
            print("⏱️  Button press ignored (debounce)")
            return

        self.last_press_time = current_time

        # Get current target device from configuration (fresh each time)
        print("🔧 Checking for updated device configuration...")
        device = self.get_target_device()
        if not device:
            return

        try:
            # Get the actual current state of the device
            current_state = self.get_device_state(device)

            # Toggle to opposite state
            action = "off" if current_state else "on"
            print(f"🔄 Turning {action.upper()} {device.nickname}...")

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

            # Show success message
            new_state = not current_state
            status_emoji = "💡" if new_state else "🌙"
            print(f"✅ {status_emoji} {device.nickname} is now {action.upper()}")

        except WyzeApiError as e:
            print(f"❌ Error controlling device: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")

    def show_status(self):
        """Show current button configuration status"""
        button_device_config = button_config.get_button_device()
        if button_device_config:
            print(f"🎯 Button configured for: {button_device_config['nickname']}")
            print(f"📍 MAC: {button_device_config['mac']}")

            device = self.get_target_device()
            if device:
                print(f"✅ Device is online and ready")
                # Show current state
                current_state = self.get_device_state(device)
                state_text = "ON" if current_state else "OFF"
                print(f"💡 Current state: {state_text}")
            else:
                print("⚠️  Device is not available")
        else:
            print("⚠️  No device configured for button control")
            print("   Visit the Flask web interface to configure a device")


print("🔧 Creating controller instance...")
try:
    # Initialize controller
    controller = FlaskIntegratedButtonController()
    print("✅ Controller created successfully")
except Exception as e:
    print(f"❌ Controller creation failed: {e}")
    sys.exit(1)

# Show initial status
print("🚀 Flask-Integrated GPIO Button Controller")
print("=" * 50)
try:
    controller.show_status()
except Exception as e:
    print(f"❌ Error showing status: {e}")
print("=" * 50)

# Set up button handler
print("🔧 Setting up button handler...")
try:
    button.when_pressed = controller.toggle_device
    print("✅ Button handler set")
except Exception as e:
    print(f"❌ Button handler error: {e}")
    sys.exit(1)

print("🔘 Press the button to toggle your configured device")
print("🌐 Visit the Flask app to change button configuration")
print("⌨️  Press Ctrl+C to exit")
print("\n📋 Button will check configuration and device state on each press")

try:
    print("🔧 Starting main loop...")
    pause()
except KeyboardInterrupt:
    print("\n👋 Shutting down...")
except Exception as e:
    print(f"❌ Main loop error: {e}")