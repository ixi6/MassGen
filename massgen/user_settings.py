"""User settings manager for MassGen TUI preferences.

Handles persistence of user preferences like theme and vim mode
to a config file in the user's home directory.
"""

import json
from pathlib import Path
from typing import Any


class UserSettings:
    """Manages user preferences for MassGen TUI.

    Settings are stored in ~/.config/massgen/settings.json
    """

    DEFAULT_SETTINGS = {
        "theme": "dark",
        "vim_mode": False,
    }

    def __init__(self):
        self._settings: dict[str, Any] = {}
        self._config_dir = Path.home() / ".config" / "massgen"
        self._settings_file = self._config_dir / "settings.json"
        self._load()

    def _load(self) -> None:
        """Load settings from file or create with defaults."""
        if self._settings_file.exists():
            try:
                with open(self._settings_file) as f:
                    loaded = json.load(f)
                # Merge with defaults to ensure all keys exist
                self._settings = {**self.DEFAULT_SETTINGS, **loaded}
            except (json.JSONDecodeError, OSError):
                # If file is corrupted, use defaults
                self._settings = self.DEFAULT_SETTINGS.copy()
                self._save()
        else:
            # First run - create with defaults
            self._settings = self.DEFAULT_SETTINGS.copy()
            self._save()

    def _save(self) -> None:
        """Save current settings to file."""
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            with open(self._settings_file, "w") as f:
                json.dump(self._settings, f, indent=2)
        except OSError:
            # If we can't write, just keep settings in memory
            pass

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and persist to disk."""
        self._settings[key] = value
        self._save()

    @property
    def theme(self) -> str:
        """Get the current theme."""
        return self._settings.get("theme", "dark")

    @theme.setter
    def theme(self, value: str) -> None:
        """Set and save the theme."""
        self._settings["theme"] = value
        self._save()

    @property
    def vim_mode(self) -> bool:
        """Get vim mode setting."""
        return self._settings.get("vim_mode", False)

    @vim_mode.setter
    def vim_mode(self, value: bool) -> None:
        """Set and save vim mode."""
        self._settings["vim_mode"] = value
        self._save()

    def to_dict(self) -> dict[str, Any]:
        """Return all settings as a dictionary."""
        return self._settings.copy()


# Global settings instance
_user_settings: UserSettings | None = None


def get_user_settings() -> UserSettings:
    """Get the global user settings instance."""
    global _user_settings
    if _user_settings is None:
        _user_settings = UserSettings()
    return _user_settings
