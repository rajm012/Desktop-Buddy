"""Persistent configuration for Desktop Buddy."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from . import APP_SLUG


def _xdg_path(env_var: str, default: Path) -> Path:
    value = os.environ.get(env_var)
    return Path(value) if value else default


CONFIG_DIR = _xdg_path("XDG_CONFIG_HOME", Path.home() / ".config") / APP_SLUG
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_DIR = _xdg_path("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_SLUG
LOG_PATH = STATE_DIR / "desktop-buddy.log"

THEMES: dict[str, dict[str, str]] = {
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

DEFAULT_THEME = "mint"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class Config:
    """User-facing settings, persisted as JSON."""

    name: str = "Mochi"
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
    autostart: bool = False
    paused: bool = False
    position_x: float | None = None

    # ------------------------------------------------------------------ load
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
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
        self.name = str(self.name).strip()[:24] or "Mochi"
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
            "autostart",
            "paused",
        ):
            setattr(self, flag, bool(getattr(self, flag)))
        try:
            self.sleep_after = _clamp(float(self.sleep_after), 15.0, 3600.0)
        except (TypeError, ValueError):
            self.sleep_after = 180.0
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
