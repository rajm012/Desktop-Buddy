"""Pure context state, per-application policy, and change detection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class NetworkState(str, Enum):
    UNKNOWN = "unknown"
    OFFLINE = "offline"
    ONLINE = "online"


@dataclass(frozen=True)
class NetworkStatus:
    state: NetworkState = NetworkState.UNKNOWN
    interface: str = ""


@dataclass(frozen=True)
class MediaStatus:
    available: bool = False
    player: str = ""
    playback: str = "unknown"
    title: str = ""
    artist: str = ""


@dataclass(frozen=True)
class ApplicationProfile:
    """A local matching rule that can silence attention for one application."""

    id: str
    name: str
    class_contains: str = ""
    title_contains: str = ""
    suppress_notifications: bool = True
    pause_animation: bool = False
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: object) -> "ApplicationProfile | None":
        if not isinstance(value, dict):
            return None
        profile_id = _safe_id(value.get("id"))
        name = str(value.get("name", "")).strip()[:80]
        class_contains = str(value.get("class_contains", "")).strip()[:120]
        title_contains = str(value.get("title_contains", "")).strip()[:120]
        if not profile_id or not name or not (class_contains or title_contains):
            return None
        return cls(
            profile_id,
            name,
            class_contains,
            title_contains,
            bool(value.get("suppress_notifications", True)),
            bool(value.get("pause_animation", False)),
            bool(value.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "class_contains": self.class_contains,
            "title_contains": self.title_contains,
            "suppress_notifications": self.suppress_notifications,
            "pause_animation": self.pause_animation,
            "enabled": self.enabled,
        }

    def matches(self, class_name: str, title: str) -> bool:
        if not self.enabled:
            return False
        class_ok = (
            not self.class_contains
            or self.class_contains.casefold() in (class_name or "").casefold()
        )
        title_ok = (
            not self.title_contains
            or self.title_contains.casefold() in (title or "").casefold()
        )
        return class_ok and title_ok


@dataclass(frozen=True)
class ContextSnapshot:
    idle_seconds: float | None = None
    fullscreen: bool = False
    active_class: str = ""
    active_title: str = ""
    profile_id: str = ""
    profile_name: str = ""
    profile_suppresses: bool = False
    profile_pauses_animation: bool = False
    on_battery: bool = False
    battery_percent: int | None = None
    low_battery: bool = False
    network: NetworkState = NetworkState.UNKNOWN
    network_interface: str = ""
    meeting_active: bool = False
    meeting_title: str = ""


@dataclass(frozen=True)
class ContextChange:
    name: str
    payload: dict[str, object]


class ContextEngine:
    """Build snapshots and emit stable changes without polling by itself."""

    def __init__(
        self,
        profiles: list[ApplicationProfile] | None = None,
        low_battery_percent: int = 20,
    ) -> None:
        self.profiles = list(profiles or [])
        self.low_battery_percent = max(1, min(100, int(low_battery_percent)))
        self.snapshot = ContextSnapshot()
        self.initialized = False

    def update(
        self,
        *,
        idle_seconds: float | None,
        fullscreen: bool,
        active_class: str,
        active_title: str,
        on_battery: bool,
        battery_percent: int | None,
        network: NetworkStatus,
        meeting_active: bool = False,
        meeting_title: str = "",
    ) -> list[ContextChange]:
        profile = next(
            (
                item
                for item in self.profiles
                if item.matches(active_class, active_title)
            ),
            None,
        )
        low_battery = bool(
            on_battery
            and battery_percent is not None
            and battery_percent <= self.low_battery_percent
        )
        current = ContextSnapshot(
            idle_seconds=max(0.0, idle_seconds) if idle_seconds is not None else None,
            fullscreen=bool(fullscreen),
            active_class=str(active_class),
            active_title=str(active_title),
            profile_id=profile.id if profile else "",
            profile_name=profile.name if profile else "",
            profile_suppresses=bool(profile and profile.suppress_notifications),
            profile_pauses_animation=bool(profile and profile.pause_animation),
            on_battery=bool(on_battery),
            battery_percent=battery_percent,
            low_battery=low_battery,
            network=network.state,
            network_interface=network.interface,
            meeting_active=bool(meeting_active),
            meeting_title=str(meeting_title),
        )
        previous = self.snapshot
        self.snapshot = current
        changes: list[ContextChange] = []
        if not self.initialized or previous.fullscreen != current.fullscreen:
            changes.append(
                ContextChange("system.fullscreen", {"active": current.fullscreen})
            )
        if not self.initialized or (
            previous.active_class,
            previous.active_title,
            previous.profile_id,
        ) != (current.active_class, current.active_title, current.profile_id):
            changes.append(
                ContextChange(
                    "system.active_application",
                    {
                        "class_name": current.active_class,
                        "title": current.active_title,
                        "profile_id": current.profile_id,
                    },
                )
            )
        if not self.initialized or previous.low_battery != current.low_battery:
            changes.append(
                ContextChange(
                    "system.low_battery",
                    {
                        "active": current.low_battery,
                        "percent": current.battery_percent,
                    },
                )
            )
        if not self.initialized or previous.network != current.network:
            changes.append(
                ContextChange(
                    "system.network",
                    {
                        "state": current.network.value,
                        "interface": current.network_interface,
                    },
                )
            )
        if not self.initialized or (
            previous.meeting_active,
            previous.meeting_title,
        ) != (current.meeting_active, current.meeting_title):
            changes.append(
                ContextChange(
                    "calendar.meeting",
                    {"active": current.meeting_active, "title": current.meeting_title},
                )
            )
        self.initialized = True
        return changes

    def attention_allowed(
        self,
        *,
        suppress_fullscreen: bool,
        suppress_meetings: bool,
        urgent: bool = False,
    ) -> bool:
        if urgent:
            return True
        state = self.snapshot
        return not (
            (suppress_fullscreen and state.fullscreen)
            or state.profile_suppresses
            or (suppress_meetings and state.meeting_active)
        )


def profiles_from_config(values: object) -> list[ApplicationProfile]:
    if not isinstance(values, list):
        return []
    profiles: list[ApplicationProfile] = []
    ids: set[str] = set()
    for raw in values:
        profile = ApplicationProfile.from_dict(raw)
        if profile is None or profile.id in ids:
            continue
        ids.add(profile.id)
        profiles.append(profile)
    return profiles


def _safe_id(value: object) -> str:
    text = "".join(
        character if character.isalnum() or character in "_-" else "-"
        for character in str(value or "").strip().lower()
    )
    return text.strip("-")[:64]
