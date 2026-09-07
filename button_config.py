"""Which devices the GPIO button controls.

Stores a list of devices ("the button group"). Configurations written before
multi-device support held a single "button_device" object; those are migrated
to a one-item list on read, so an existing button_config.json keeps working.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ButtonConfig:
    def __init__(self, config_file: str = "button_config.json"):
        self.config_file = config_file
        self.config_data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file, migrating the old single-device shape."""
        data: Dict[str, Any] = {"button_devices": [], "last_updated": None}
        if not os.path.exists(self.config_file):
            return data

        try:
            with open(self.config_file, 'r') as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, IOError) as err:
            logger.warning("could not read %s (%s); starting from an empty group",
                           self.config_file, err)
            return data

        if "button_devices" in loaded:
            data["button_devices"] = [d for d in loaded["button_devices"] if d]
        elif loaded.get("button_device"):
            # Pre-multi-device format: promote the single entry to a list.
            data["button_devices"] = [loaded["button_device"]]
            logger.info("migrated button_config.json from single device (%s) "
                        "to a device group", loaded["button_device"].get("nickname"))
        data["last_updated"] = loaded.get("last_updated")
        return data

    def reload(self) -> None:
        """Re-read from disk. The button daemon calls this on each press so it
        picks up changes made in the web interface without a restart."""
        self.config_data = self._load_config()

    def _save_config(self) -> bool:
        """Save configuration to file"""
        import datetime
        self.config_data["last_updated"] = datetime.datetime.now().isoformat()
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config_data, f, indent=2)
            return True
        except IOError as err:
            logger.error("could not write %s: %s", self.config_file, err)
            return False

    # ---------------------------------------------------------------- reading

    def get_button_devices(self) -> List[Dict[str, str]]:
        """Every device in the button group, in the order they were saved."""
        return list(self.config_data.get("button_devices") or [])

    def get_macs(self) -> List[str]:
        return [d["mac"] for d in self.get_button_devices() if d.get("mac")]

    def is_selected(self, mac: str) -> bool:
        return mac in self.get_macs()

    # ---------------------------------------------------------------- writing

    def set_button_devices(self, devices: List[Dict[str, str]]) -> bool:
        """Replace the whole group. `devices` is a list of {mac, nickname}."""
        cleaned = [{"mac": d["mac"], "nickname": d.get("nickname", d["mac"])}
                   for d in devices if d.get("mac")]
        self.config_data["button_devices"] = cleaned
        logger.info("button group set to %d device(s): %s", len(cleaned),
                    ", ".join(d["nickname"] for d in cleaned) or "(none)")
        return self._save_config()

    def clear_button_devices(self) -> bool:
        """Remove every device from the group."""
        self.config_data["button_devices"] = []
        logger.info("button group cleared")
        return self._save_config()


# Create global instance
button_config = ButtonConfig()
