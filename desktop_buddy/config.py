"""Persistent configuration for Desktop Buddy."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .platforms import get_backend

_PLATFORM_PATHS = get_backend().paths()
CONFIG_DIR = _PLATFORM_PATHS.config_dir
CONFIG_PATH = _PLATFORM_PATHS.config_file
STATE_DIR = _PLATFORM_PATHS.state_dir
LOG_PATH = _PLATFORM_PATHS.log_file

THEMES: dict[str, dict[str, str]] = {
    "circuit": {
        "label": "Circuit White",
        "body": "#f2f6f5",
        "body_dark": "#c5cecd",
        "belly": "#ffffff",
        "accent": "#9eacab",
        "outline": "#293136",
        "blush": "#9ce6ea",
        "eye": "#111719",
    },
    "mint": {
        "label": "Mochi Mint",
        "body": "#7ed6b5",
        "body_dark": "#5bbf9c",
        "belly": "#eafbf3",
        "accent": "#f9a8c9",
        "outline": "#2f5d50",
        "blush": "#f7a8b8",
        "eye": "#20302c",
    },
    "peach": {
        "label": "Peach Puff",
        "body": "#ffb38a",
        "body_dark": "#f09a70",
        "belly": "#fff1e8",
        "accent": "#ff8fab",
        "outline": "#7a4030",
        "blush": "#f97d92",
        "eye": "#3a231d",
    },
    "lavender": {
        "label": "Lavender",
        "body": "#b9a7f5",
        "body_dark": "#9d8ae0",
        "belly": "#f2edff",
        "accent": "#ffc6e0",
        "outline": "#4a3b78",
        "blush": "#e79cc4",
        "eye": "#2d2450",
    },
    "sky": {
        "label": "Sky",
        "body": "#8ecae6",
        "body_dark": "#74b6d6",
        "belly": "#eaf6fc",
        "accent": "#ffb703",
        "outline": "#29506b",
        "blush": "#f4a3b5",
        "eye": "#1e3a4d",
    },
    "sakura": {
        "label": "Sakura",
        "body": "#ffc2d1",
        "body_dark": "#f2a3b8",
        "belly": "#fff0f4",
        "accent": "#c9a7eb",
        "outline": "#8a4b61",
        "blush": "#f48fb1",
        "eye": "#4a2430",
    },
    "charcoal": {
        "label": "Charcoal",
        "body": "#4a4e69",
        "body_dark": "#3b3f57",
        "belly": "#c9ccd5",
        "accent": "#f2a65a",
        "outline": "#22223b",
        "blush": "#c77d8a",
        "eye": "#11121c",
    },
}

DEFAULT_THEME = "circuit"

# Character roster. Keys are stored in the config; labels are user-facing.
SPECIES: dict[str, dict[str, str]] = {
    "robot": {"label": "Bolt the Robot", "default_name": "Bolt"},
    "ghost": {"label": "Boo-ombastic", "default_name": "Boo-ombastic"},
    "mochi": {"label": "Mochi", "default_name": "Mochi"},
}
DEFAULT_SPECIES = "robot"
CURRENT_CONFIG_SCHEMA_VERSION = 1


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade persisted settings without relying on user-facing names."""
    migrated = dict(data)
    try:
        version = int(migrated.get("schema_version", 0))
    except (TypeError, ValueError):
        version = 0

    if version < 1:
        # Version 0 predates an explicit character field. At that point Mochi
        # was the only renderer, so the migration is based on file structure,
        # not on a possibly customized or translated display name.
        migrated.setdefault("species", "mochi")
        version = 1

    migrated["schema_version"] = max(version, CURRENT_CONFIG_SCHEMA_VERSION)
    return migrated


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _valid_time(value: object, fallback: str) -> str:
    for candidate in (value, fallback):
        try:
            hours, minutes = str(candidate).strip().split(":", 1)
            hour, minute = int(hours), int(minutes)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except (TypeError, ValueError, AttributeError):
            continue
    return "09:00"


@dataclass
class Config:
    """User-facing settings, persisted as JSON."""

    schema_version: int = CURRENT_CONFIG_SCHEMA_VERSION
    name: str = SPECIES[DEFAULT_SPECIES]["default_name"]
    species: str = DEFAULT_SPECIES
    theme: str = DEFAULT_THEME
    scale: float = 0.8
    speed: float = 1.0
    fps: int = 30
    always_on_top: bool = True
    click_through: bool = False
    reduce_on_battery: bool = True
    playful: bool = True
    can_sleep: bool = True
    sleep_after: float = 180.0
    perch_on_windows: bool = True
    perch_delay: float = 1.2
    reminders_enabled: bool = True
    reminder_sound: bool = True
    breakfast_enabled: bool = True
    breakfast_time: str = "09:00"
    lunch_enabled: bool = True
    lunch_time: str = "13:30"
    snack_enabled: bool = True
    snack_time: str = "16:30"
    dinner_enabled: bool = True
    dinner_time: str = "21:00"
    winddown_enabled: bool = True
    winddown_time: str = "23:00"
    water_enabled: bool = True
    water_interval_minutes: int = 45
    break_enabled: bool = True
    break_interval_minutes: int = 60
    active_start: str = "09:00"
    active_end: str = "22:30"
    reminder_grace_minutes: int = 45
    snooze_minutes: int = 10
    autostart: bool = False
    paused: bool = False
    position_x: float | None = None

    # ------------------------------------------------------------------ load
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        data = migrate_config(data)
        known = {f.name for f in fields(cls)}
        kwargs = {key: value for key, value in data.items() if key in known}
        config = cls(**kwargs)
        config.normalize()
        return config

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    # ------------------------------------------------------------------ save
    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    # --------------------------------------------------------------- helpers
    def normalize(self) -> None:
        try:
            self.schema_version = max(
                int(self.schema_version), CURRENT_CONFIG_SCHEMA_VERSION
            )
        except (TypeError, ValueError):
            self.schema_version = CURRENT_CONFIG_SCHEMA_VERSION
        self.name = (
            str(self.name).strip()[:24] or SPECIES[DEFAULT_SPECIES]["default_name"]
        )
        if self.species not in SPECIES:
            self.species = DEFAULT_SPECIES
        if self.theme not in THEMES:
            self.theme = DEFAULT_THEME
        try:
            self.scale = _clamp(float(self.scale), 0.5, 1.8)
        except (TypeError, ValueError):
            self.scale = 0.8
        try:
            self.speed = _clamp(float(self.speed), 0.4, 2.5)
        except (TypeError, ValueError):
            self.speed = 1.0
        try:
            self.fps = int(_clamp(int(self.fps), 10, 60))
        except (TypeError, ValueError):
            self.fps = 30
        for flag in (
            "always_on_top",
            "click_through",
            "reduce_on_battery",
            "playful",
            "can_sleep",
            "perch_on_windows",
            "reminders_enabled",
            "reminder_sound",
            "breakfast_enabled",
            "lunch_enabled",
            "snack_enabled",
            "dinner_enabled",
            "winddown_enabled",
            "water_enabled",
            "break_enabled",
            "autostart",
            "paused",
        ):
            setattr(self, flag, bool(getattr(self, flag)))
        try:
            self.sleep_after = _clamp(float(self.sleep_after), 15.0, 3600.0)
        except (TypeError, ValueError):
            self.sleep_after = 180.0
        try:
            self.perch_delay = _clamp(float(self.perch_delay), 0.3, 10.0)
        except (TypeError, ValueError):
            self.perch_delay = 1.2
        self.breakfast_time = _valid_time(self.breakfast_time, "09:00")
        self.lunch_time = _valid_time(self.lunch_time, "13:30")
        self.snack_time = _valid_time(self.snack_time, "16:30")
        self.dinner_time = _valid_time(self.dinner_time, "21:00")
        self.winddown_time = _valid_time(self.winddown_time, "23:00")
        self.active_start = _valid_time(self.active_start, "09:00")
        self.active_end = _valid_time(self.active_end, "22:30")
        try:
            self.water_interval_minutes = int(
                _clamp(int(self.water_interval_minutes), 10, 180)
            )
        except (TypeError, ValueError):
            self.water_interval_minutes = 45
        try:
            self.break_interval_minutes = int(
                _clamp(int(self.break_interval_minutes), 20, 240)
            )
        except (TypeError, ValueError):
            self.break_interval_minutes = 60
        try:
            self.reminder_grace_minutes = int(
                _clamp(int(self.reminder_grace_minutes), 5, 180)
            )
        except (TypeError, ValueError):
            self.reminder_grace_minutes = 45
        try:
            self.snooze_minutes = int(_clamp(int(self.snooze_minutes), 1, 60))
        except (TypeError, ValueError):
            self.snooze_minutes = 10
        if self.position_x is not None:
            try:
                self.position_x = float(self.position_x)
            except (TypeError, ValueError):
                self.position_x = None

    def theme_colors(self) -> dict[str, str]:
        return dict(THEMES.get(self.theme, THEMES[DEFAULT_THEME]))

    def copy(self) -> "Config":
        return Config.from_dict(self.to_dict())

    def reset(self) -> None:
        """Restore every setting to its factory default."""
        default = Config()
        for field_info in fields(self):
            setattr(self, field_info.name, getattr(default, field_info.name))
