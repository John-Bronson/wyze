
"""
Button configuration manager for storing which device the GPIO button controls.
"""
import json
import os
from typing import Optional, Dict, Any

class ButtonConfig:
    def __init__(self, config_file: str = "button_config.json"):
        self.config_file = config_file
        self.config_data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Return default config
        return {
            "button_device": None,
            "last_updated": None
        }

    def _save_config(self) -> bool:
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config_data, f, indent=2)
            return True
        except IOError:
            return False

    def get_button_device(self) -> Optional[Dict[str, str]]:
        """Get the currently configured button device"""
        return self.config_data.get("button_device")

    def set_button_device(self, mac: str, nickname: str) -> bool:
        """Set which device the button should control"""
        import datetime

        self.config_data["button_device"] = {
            "mac": mac,
            "nickname": nickname
        }
        self.config_data["last_updated"] = datetime.datetime.now().isoformat()

        return self._save_config()

    def clear_button_device(self) -> bool:
        """Clear the button device configuration"""
        self.config_data["button_device"] = None
        self.config_data["last_updated"] = None

        return self._save_config()

# Create global instance
button_config = ButtonConfig()