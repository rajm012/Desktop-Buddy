"""Platform-independent focus-session state and persistence.

The engine uses absolute local datetimes for running sessions, so elapsed time
remains accurate when UI frames are delayed or the computer sleeps. It has no
Qt or operating-system dependencies and can be tested with an injected clock.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable

CURRENT_FOCUS_SCHEMA_VERSION = 1


class SessionKind(str, Enum):
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class FocusStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class FocusEventType(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class FocusSettings:
    focus_seconds: int = 25 * 60
    short_break_seconds: int = 5 * 60
    long_break_seconds: int = 15 * 60
    long_break_every: int = 4

    def duration(self, kind: SessionKind) -> int:
        if kind is SessionKind.SHORT_BREAK:
            return max(1, int(self.short_break_seconds))
        if kind is SessionKind.LONG_BREAK:
            return max(1, int(self.long_break_seconds))
        return max(1, int(self.focus_seconds))

    @classmethod
    def from_config(cls, config) -> "FocusSettings":  # noqa: ANN001
        return cls(
            focus_seconds=int(config.focus_minutes) * 60,
            short_break_seconds=int(config.short_break_minutes) * 60,
            long_break_seconds=int(config.long_break_minutes) * 60,
            long_break_every=int(config.long_break_every),
        )


@dataclass(frozen=True)
class FocusEvent:
    type: FocusEventType
    kind: SessionKind
    next_kind: SessionKind
    at: datetime
    credited_seconds: int = 0


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _enum_value(enum_type, value, fallback):  # noqa: ANN001
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return fallback


@dataclass
class FocusState:
    schema_version: int = CURRENT_FOCUS_SCHEMA_VERSION
    status: FocusStatus = FocusStatus.STOPPED
    kind: SessionKind = SessionKind.FOCUS
    started_at: datetime | None = None
    deadline: datetime | None = None
    paused_remaining_seconds: float | None = None
    session_duration_seconds: int = 0
    completed_focus_sessions: int = 0
    history: dict[str, int] = field(default_factory=dict)
    last_completed_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "kind": self.kind.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "paused_remaining_seconds": self.paused_remaining_seconds,
            "session_duration_seconds": self.session_duration_seconds,
            "completed_focus_sessions": self.completed_focus_sessions,
            "history": dict(sorted(self.history.items())),
            "last_completed_at": (
                self.last_completed_at.isoformat() if self.last_completed_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "FocusState":
        if not isinstance(data, dict):
            return cls()
        try:
            version = int(data.get("schema_version", 0))
        except (TypeError, ValueError):
            version = 0
        state = cls(
            schema_version=max(version, CURRENT_FOCUS_SCHEMA_VERSION),
            status=_enum_value(FocusStatus, data.get("status"), FocusStatus.STOPPED),
            kind=_enum_value(SessionKind, data.get("kind"), SessionKind.FOCUS),
            started_at=_parse_datetime(data.get("started_at")),
            deadline=_parse_datetime(data.get("deadline")),
            last_completed_at=_parse_datetime(data.get("last_completed_at")),
        )
        try:
            state.paused_remaining_seconds = max(
                0.0, float(data.get("paused_remaining_seconds"))
            )
        except (TypeError, ValueError):
            state.paused_remaining_seconds = None
        try:
            state.session_duration_seconds = max(
                0, int(data.get("session_duration_seconds", 0))
            )
        except (TypeError, ValueError):
            state.session_duration_seconds = 0
        try:
            state.completed_focus_sessions = max(
                0, int(data.get("completed_focus_sessions", 0))
            )
        except (TypeError, ValueError):
            state.completed_focus_sessions = 0
        raw_history = data.get("history")
        if isinstance(raw_history, dict):
            for key, value in raw_history.items():
                try:
                    date.fromisoformat(str(key))
                    seconds = max(0, int(value))
                except (TypeError, ValueError):
                    continue
                state.history[str(key)] = seconds
        state._sanitize()
        return state

    @classmethod
    def load(cls, path: Path) -> "FocusState":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return cls()
        return cls.from_dict(data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _sanitize(self) -> None:
        if self.status is FocusStatus.RUNNING and self.deadline is None:
            self.status = FocusStatus.STOPPED
        if self.status is FocusStatus.PAUSED and self.paused_remaining_seconds is None:
            self.status = FocusStatus.STOPPED
        if self.status is FocusStatus.STOPPED:
            self.deadline = None
            self.paused_remaining_seconds = None
            self.started_at = None
            self.session_duration_seconds = 0


class FocusEngine:
    """Pomodoro-style focus state machine with explicit user actions."""

    def __init__(
        self,
        settings: FocusSettings | None = None,
        state: FocusState | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or FocusSettings()
        self.state = state or FocusState()
        self.now_fn = now_fn or datetime.now
        self.state._sanitize()

    def set_settings(self, settings: FocusSettings) -> None:
        """Use new durations for future sessions without changing an active one."""
        self.settings = settings

    def start(
        self, kind: SessionKind | None = None, now: datetime | None = None
    ) -> bool:
        if self.state.status is not FocusStatus.STOPPED:
            return False
        now = now or self.now_fn()
        if kind is not None:
            self.state.kind = kind
        duration = self.settings.duration(self.state.kind)
        self.state.status = FocusStatus.RUNNING
        self.state.started_at = now
        self.state.deadline = now + timedelta(seconds=duration)
        self.state.paused_remaining_seconds = None
        self.state.session_duration_seconds = duration
        return True

    def pause(self, now: datetime | None = None) -> bool:
        if self.state.status is not FocusStatus.RUNNING or self.state.deadline is None:
            return False
        now = now or self.now_fn()
        self.state.paused_remaining_seconds = max(
            0.0, (self.state.deadline - now).total_seconds()
        )
        self.state.status = FocusStatus.PAUSED
        self.state.deadline = None
        return True

    def resume(self, now: datetime | None = None) -> bool:
        if self.state.status is not FocusStatus.PAUSED:
            return False
        now = now or self.now_fn()
        remaining = max(0.0, self.state.paused_remaining_seconds or 0.0)
        self.state.status = FocusStatus.RUNNING
        self.state.deadline = now + timedelta(seconds=remaining)
        self.state.paused_remaining_seconds = None
        return True

    def stop(self) -> bool:
        if (
            self.state.status is FocusStatus.STOPPED
            and self.state.kind is SessionKind.FOCUS
        ):
            return False
        self._clear_session()
        self.state.kind = SessionKind.FOCUS
        return True

    def skip(self, now: datetime | None = None) -> FocusEvent | None:
        if self.state.status is FocusStatus.STOPPED:
            return None
        now = now or self.now_fn()
        skipped = self.state.kind
        next_kind = self._next_kind(skipped)
        self._clear_session()
        self.state.kind = next_kind
        return FocusEvent(FocusEventType.SKIPPED, skipped, next_kind, now)

    def tick(self, now: datetime | None = None) -> list[FocusEvent]:
        if self.state.status is not FocusStatus.RUNNING or self.state.deadline is None:
            return []
        now = now or self.now_fn()
        if now < self.state.deadline:
            return []
        completed_at = self.state.deadline
        completed = self.state.kind
        credited = 0
        if completed is SessionKind.FOCUS:
            credited = max(1, self.state.session_duration_seconds)
            day = completed_at.date().isoformat()
            self.state.history[day] = self.state.history.get(day, 0) + credited
            self.state.completed_focus_sessions += 1
            self._trim_history(completed_at.date())
        next_kind = self._next_kind(completed)
        self._clear_session()
        self.state.kind = next_kind
        self.state.last_completed_at = completed_at
        return [
            FocusEvent(
                FocusEventType.COMPLETED,
                completed,
                next_kind,
                now,
                credited,
            )
        ]

    def remaining_seconds(self, now: datetime | None = None) -> int:
        if self.state.status is FocusStatus.PAUSED:
            return max(0, math.ceil(self.state.paused_remaining_seconds or 0.0))
        if self.state.status is FocusStatus.RUNNING and self.state.deadline is not None:
            now = now or self.now_fn()
            return max(0, math.ceil((self.state.deadline - now).total_seconds()))
        return self.settings.duration(self.state.kind)

    def today_seconds(self, now: datetime | None = None) -> int:
        now = now or self.now_fn()
        return self.state.history.get(now.date().isoformat(), 0)

    def recent_history(
        self, days: int = 7, now: datetime | None = None
    ) -> list[tuple[date, int]]:
        now = now or self.now_fn()
        count = max(1, int(days))
        return [
            (
                now.date() - timedelta(days=offset),
                self.state.history.get(
                    (now.date() - timedelta(days=offset)).isoformat(), 0
                ),
            )
            for offset in range(count - 1, -1, -1)
        ]

    def _next_kind(self, current: SessionKind) -> SessionKind:
        if current is not SessionKind.FOCUS:
            return SessionKind.FOCUS
        cadence = max(1, int(self.settings.long_break_every))
        if self.state.completed_focus_sessions > 0 and (
            self.state.completed_focus_sessions % cadence == 0
        ):
            return SessionKind.LONG_BREAK
        return SessionKind.SHORT_BREAK

    def _clear_session(self) -> None:
        self.state.status = FocusStatus.STOPPED
        self.state.started_at = None
        self.state.deadline = None
        self.state.paused_remaining_seconds = None
        self.state.session_duration_seconds = 0

    def _trim_history(self, today: date) -> None:
        cutoff = today - timedelta(days=366)
        self.state.history = {
            key: value
            for key, value in self.state.history.items()
            if date.fromisoformat(key) >= cutoff
        }


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def kind_label(kind: SessionKind) -> str:
    return {
        SessionKind.FOCUS: "Focus",
        SessionKind.SHORT_BREAK: "Short break",
        SessionKind.LONG_BREAK: "Long break",
    }[kind]
