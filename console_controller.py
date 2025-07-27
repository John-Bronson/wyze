#!/usr/bin/env python3
"""
Console application for controlling Wyze devices via menu interface.
Perfect for Raspberry Pi deployment with GPIO button integration.
"""

import os
import sys
from typing import List, Optional
from wyze_sdk.errors import WyzeApiError
from wyze_sdk.models.devices import Device

# Import our existing token manager
from token_manager import token_manager


class WyzeConsoleController:
    def __init__(self):
        self.client = None
        self.devices = []

    def initialize(self) -> bool:
        """Initialize the Wyze client and load devices"""
        try:
            print("Initializing Wyze connection...")
            self.client = token_manager.get_client()
            self.refresh_devices()
            print(f"Successfully connected! Found {len(self.devices)} devices.")
            return True
        except (WyzeApiError, EnvironmentError) as e:
            print(f"Failed to initialize: {e}")
            return False

    def refresh_devices(self) -> None:
        """Refresh the device list"""
        if self.client:
            self.devices = [d for d in self.client.devices_list() if d.is_online]

    def display_devices(self) -> None:
        """Display all available devices"""
        if not self.devices:
            print("No online devices found.")
            return

        print("\n=== Available Devices ===")
        for i, device in enumerate(self.devices, 1):
            status = "Online" if device.is_online else "Offline"
            print(f"{i}. {device.nickname} ({device.mac}) - {status}")

    def toggle_device(self, device: Device, action: str) -> bool:
        """Toggle a device on or off"""
        try:
            print(f"Turning {action} {device.nickname}...")
            if action == "on":
                self.client.plugs.turn_on(device_mac=device.mac, device_model=device.product.model)
            elif action == "off":
                self.client.plugs.turn_off(device_mac=device.mac, device_model=device.product.model)
            print(f"Successfully turned {action} {device.nickname}")
            return True
        except WyzeApiError as e:
            print(f"Error controlling {device.nickname}: {e}")
            return False

    def get_device_by_nickname(self, nickname: str) -> Optional[Device]:
        """Find device by nickname (case-insensitive)"""
        for device in self.devices:
            if device.nickname.lower() == nickname.lower():
                return device
        return None

    def get_device_by_mac(self, mac: str) -> Optional[Device]:
        """Find device by MAC address"""
        for device in self.devices:
            if device.mac == mac:
                return device
        return None


def show_main_menu():
    """Display the main menu options"""
    print("\n" + "=" * 50)
    print("         WYZE DEVICE CONTROLLER")
    print("=" * 50)
    print("1. List all devices")
    print("2. Turn device ON")
    print("3. Turn device OFF")
    print("4. Toggle specific device (by nickname)")
    print("5. Refresh device list")
    print("6. Quick toggle (by MAC address)")
    print("q. Quit")
    print("=" * 50)


def get_user_choice() -> str:
    """Get user menu choice"""
    return input("Enter your choice: ").strip().lower()


def select_device(controller: WyzeConsoleController) -> Optional[Device]:
    """Let user select a device from the list"""
    if not controller.devices:
        print("No devices available.")
        return None

    controller.display_devices()
    try:
        choice = input("\nEnter device number: ").strip()
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(controller.devices):
                return controller.devices[index]
        print("Invalid selection.")
    except (ValueError, IndexError):
        print("Invalid input.")
    return None


def quick_toggle_by_name(controller: WyzeConsoleController) -> None:
    """Quick toggle by device nickname"""
    nickname = input("Enter device nickname: ").strip()
    device = controller.get_device_by_nickname(nickname)

    if not device:
        print(f"Device '{nickname}' not found.")
        return

    action = input(f"Turn {device.nickname} [on/off]: ").strip().lower()
    if action in ['on', 'off']:
        controller.toggle_device(device, action)
    else:
        print("Invalid action. Use 'on' or 'off'.")


def quick_toggle_by_mac(controller: WyzeConsoleController) -> None:
    """Quick toggle by MAC address (useful for GPIO scripting)"""
    mac = input("Enter device MAC address: ").strip()
    device = controller.get_device_by_mac(mac)

    if not device:
        print(f"Device with MAC '{mac}' not found.")
        return

    action = input(f"Turn {device.nickname} [on/off]: ").strip().lower()
    if action in ['on', 'off']:
        controller.toggle_device(device, action)
    else:
        print("Invalid action. Use 'on' or 'off'.")


def gpio_toggle_device(mac_address: str, action: str) -> bool:
    """
    Function designed for GPIO button integration.
    Call this from your Raspberry Pi GPIO handler.

    Args:
        mac_address: MAC address of the device to control
        action: 'on' or 'off'

    Returns:
        bool: True if successful, False otherwise
    """
    controller = WyzeConsoleController()
    if not controller.initialize():
        return False

    device = controller.get_device_by_mac(mac_address)
    if not device:
        print(f"Device with MAC {mac_address} not found.")
        return False

    return controller.toggle_device(device, action)


def main():
    """Main application loop"""
    print("Starting Wyze Console Controller...")

    # Validate environment variables
    required_vars = ['WYZE_EMAIL', 'WYZE_PASSWORD', 'WYZE_KEY_ID', 'WYZE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"Error: Missing environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file.")
        sys.exit(1)

    # Initialize controller
    controller = WyzeConsoleController()
    if not controller.initialize():
        print("Failed to initialize. Exiting.")
        sys.exit(1)

    # Main menu loop
    while True:
        show_main_menu()
        choice = get_user_choice()

        if choice == '1':
            controller.display_devices()

        elif choice == '2':
            device = select_device(controller)
            if device:
                controller.toggle_device(device, "on")

        elif choice == '3':
            device = select_device(controller)
            if device:
                controller.toggle_device(device, "off")

        elif choice == '4':
            quick_toggle_by_name(controller)

        elif choice == '5':
            print("Refreshing device list...")
            controller.refresh_devices()
            print(f"Found {len(controller.devices)} online devices.")

        elif choice == '6':
            quick_toggle_by_mac(controller)

        elif choice == 'q':
            print("Goodbye!")
            break

        else:
            print("Invalid choice. Please try again.")

        # Pause before showing menu again
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()