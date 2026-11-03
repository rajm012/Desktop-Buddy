"""Platform capability interface and portable Qt-backed defaults."""

from __future__ import annotations

import getpass
import hashlib
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from PyQt6.QtCore import QStandardPaths, QUrl

from .. import APP_SLUG

try:
    from PyQt6.QtMultimedia import QSoundEffect
except Exception:  # noqa: BLE001  # pragma: no cover - optional Qt component
    QSoundEffect = None  # type: ignore[assignment,misc]


class Capability(str, Enum):
    PATHS = "paths"
    AUTOSTART = "autostart"
    BATTERY = "battery"
    ACTIVE_WINDOW = "active_window"
    ALWAYS_ON_TOP = "always_on_top"
    WORKSPACE_BEHAVIOR = "workspace_behavior"
    CLICK_THROUGH = "click_through"
    AUDIO = "audio"
    SESSION_DIAGNOSTICS = "session_diagnostics"


@dataclass(frozen=True)
class CapabilityInfo:
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class PlatformPaths:
    config_dir: Path
    state_dir: Path
    cache_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def log_file(self) -> Path:
        return self.state_dir / "desktop-buddy.log"


@dataclass(frozen=True)
class BatteryStatus:
    on_battery: bool = False
    label: str = "unavailable"


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    class_name: str
    title: str
    x: int
    y: int
    width: int
    height: int
    hidden: bool = False
    fullscreen: bool = False


class ActiveWindowProbe:
    """Minimal active-window query interface."""

    @property
    def available(self) -> bool:
        return False

    def active_window(self) -> WindowInfo | None:
        return None

    def close(self) -> None:
        return None


def _standard_path(location: QStandardPaths.StandardLocation, fallback: Path) -> Path:
    value = QStandardPaths.writableLocation(location)
    return Path(value) if value else fallback


class PlatformBackend(ABC):
    """Operating-system services used by the application and Qt UI."""

    def __init__(self) -> None:
        self._sound_effects: set[Any] = set()

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> dict[Capability, CapabilityInfo]:
        raise NotImplementedError

    def capability(self, capability: Capability) -> CapabilityInfo:
        return self.capabilities().get(
            capability, CapabilityInfo(False, "Not implemented on this platform.")
        )

    def supports(self, capability: Capability) -> bool:
        return self.capability(capability).available

    def paths(self) -> PlatformPaths:
        home_value = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.HomeLocation
        )
        home = Path(home_value) if home_value else Path.home()
        config_root = _standard_path(
            QStandardPaths.StandardLocation.GenericConfigLocation, home
        )
        state_root = _standard_path(
            QStandardPaths.StandardLocation.GenericStateLocation, config_root
        )
        cache_root = _standard_path(
            QStandardPaths.StandardLocation.GenericCacheLocation, state_root
        )
        return PlatformPaths(
            config_dir=config_root / APP_SLUG,
            state_dir=state_root / APP_SLUG,
            cache_dir=cache_root / APP_SLUG,
        )

    def session_environment(self) -> Mapping[str, str]:
        return os.environ

    def user_session_id(self) -> str:
        user = getpass.getuser() or "user"
        env = self.session_environment()
        session = (
            env.get("XDG_SESSION_ID")
            or env.get("SESSIONNAME")
            or env.get("WAYLAND_DISPLAY")
            or env.get("DISPLAY")
            or "default"
        )
        digest = hashlib.sha256(f"{user}\0{session}".encode()).hexdigest()[:12]
        safe_user = re.sub(r"[^A-Za-z0-9_.-]", "-", user).strip("-") or "user"
        return f"{safe_user}-{digest}"

    def server_name(self) -> str:
        return f"{APP_SLUG}-{self.user_session_id()}"

    def icon_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "assets" / "icon.svg"

    def autostart_path(self, base: Path | None = None) -> Path | None:
        return None

    def autostart_enabled(self, base: Path | None = None) -> bool:
        path = self.autostart_path(base)
        return bool(path and path.is_file())

    def set_autostart(self, enabled: bool, base: Path | None = None) -> Path | None:
        raise OSError(self.capability(Capability.AUTOSTART).reason)

    def battery_status(self) -> BatteryStatus:
        return BatteryStatus()

    def create_active_window_probe(self) -> ActiveWindowProbe:
        return ActiveWindowProbe()

    def classify_window(self, class_name: str) -> str | None:
        return None

    def apply_workspace_behavior(self, native_window_id: int) -> bool:
        return False

    @property
    def audio_available(self) -> bool:
        return QSoundEffect is not None

    def play_audio(self, path: Path, volume: float = 0.55) -> bool:
        if QSoundEffect is None or not path.is_file():
            return False
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.setLoopCount(1)
        effect.setVolume(max(0.0, min(1.0, float(volume))))
        self._sound_effects.add(effect)

        def cleanup() -> None:
            if effect.isPlaying():
                return
            self._sound_effects.discard(effect)
            effect.deleteLater()

        effect.playingChanged.connect(cleanup)
        effect.play()
        return True

    def session_type(self) -> str:
        return "unknown"

    def diagnostics(self) -> dict[str, object]:
        return {"backend": self.name, "session": self.session_type()}


class GenericPlatformBackend(PlatformBackend):
    """Safe fallback until a native Windows or macOS backend is implemented."""

    @property
    def name(self) -> str:
        return "generic"

    def capabilities(self) -> dict[Capability, CapabilityInfo]:
        unavailable = "A native backend is not implemented for this platform yet."
        return {
            Capability.PATHS: CapabilityInfo(True),
            Capability.AUTOSTART: CapabilityInfo(False, unavailable),
            Capability.BATTERY: CapabilityInfo(False, unavailable),
            Capability.ACTIVE_WINDOW: CapabilityInfo(False, unavailable),
            Capability.ALWAYS_ON_TOP: CapabilityInfo(False, unavailable),
            Capability.WORKSPACE_BEHAVIOR: CapabilityInfo(False, unavailable),
            Capability.CLICK_THROUGH: CapabilityInfo(False, unavailable),
            Capability.AUDIO: CapabilityInfo(self.audio_available, unavailable),
            Capability.SESSION_DIAGNOSTICS: CapabilityInfo(True),
        }
