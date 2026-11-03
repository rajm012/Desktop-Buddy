"""General local reminder scheduling, recurrence parsing, and history.

All datetimes are timezone-naive local wall-clock values. The module has no Qt
or operating-system dependencies and is deterministic with an injected clock.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from enum import Enum
from typing import Callable

CURRENT_WELLNESS_SCHEMA_VERSION = 2
MAX_HISTORY_ENTRIES = 500


class Recurrence(str, Enum):
    ONE_TIME = "one_time"
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    INTERVAL = "interval"


class HistoryStatus(str, Enum):
    DONE = "done"
    MISSED = "missed"
    SNOOZED = "snoozed"


def parse_hhmm(value: object, fallback: str = "09:00") -> dtime:
    for candidate in (value, fallback):
        try:
            hours, minutes = str(candidate).strip().split(":", 1)
            hour, minute = int(hours), int(minutes)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return dtime(hour=hour, minute=minute)
        except (TypeError, ValueError, AttributeError):
            continue
    return dtime(hour=9)


def format_hhmm(value: dtime) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _stable_id(value: object) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return text[:64]


@dataclass(frozen=True)
class ScheduleSpec:
    recurrence: Recurrence
    time_of_day: dtime | None = None
    one_time_at: datetime | None = None
    interval_minutes: int | None = None
    weekdays: tuple[int, ...] = ()

    def describe(self) -> str:
        if self.recurrence is Recurrence.ONE_TIME and self.one_time_at:
            return self.one_time_at.strftime("%Y-%m-%d at %H:%M")
        if self.recurrence is Recurrence.INTERVAL and self.interval_minutes:
            minutes = self.interval_minutes
            if minutes % 60 == 0:
                hours = minutes // 60
                return f"every {hours} hour{'s' if hours != 1 else ''}"
            return f"every {minutes} minutes"
        prefix = "weekdays" if self.recurrence is Recurrence.WEEKDAYS else "daily"
        return f"{prefix} at {format_hhmm(self.time_of_day or dtime(9))}"


def _parse_clock(value: str) -> dtime | None:
    match = re.fullmatch(
        r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*", value, re.IGNORECASE
    )
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        if meridiem == "am":
            hour %= 12
        else:
            hour = hour % 12 + 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return dtime(hour, minute)


def parse_reminder_phrase(text: str, now: datetime | None = None) -> ScheduleSpec:
    """Parse a small, intentionally local and deterministic schedule grammar."""
    now = now or datetime.now()
    phrase = " ".join(str(text).strip().lower().split())
    match = re.fullmatch(r"in (\d+) (minute|minutes|hour|hours|day|days)", phrase)
    if match:
        amount = max(1, int(match.group(1)))
        unit = match.group(2)
        if unit.startswith("minute"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("hour"):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return ScheduleSpec(Recurrence.ONE_TIME, one_time_at=now + delta)

    match = re.fullmatch(r"every (\d+) (minute|minutes|hour|hours)", phrase)
    if match:
        amount = max(1, int(match.group(1)))
        minutes = amount * (60 if match.group(2).startswith("hour") else 1)
        return ScheduleSpec(Recurrence.INTERVAL, interval_minutes=minutes)

    match = re.fullmatch(r"(weekdays|daily|every day) at (.+)", phrase)
    if match:
        clock = _parse_clock(match.group(2))
        if clock is None:
            raise ValueError("Use a time such as 09:00, 9 or 9:30 pm.")
        recurrence = (
            Recurrence.WEEKDAYS if match.group(1) == "weekdays" else Recurrence.DAILY
        )
        weekdays = (0, 1, 2, 3, 4) if recurrence is Recurrence.WEEKDAYS else ()
        return ScheduleSpec(recurrence, time_of_day=clock, weekdays=weekdays)

    match = re.fullmatch(r"tomorrow at (.+)", phrase)
    if match:
        clock = _parse_clock(match.group(1))
        if clock is None:
            raise ValueError("Use a time such as 09:00, 9 or 9:30 pm.")
        target = datetime.combine(now.date() + timedelta(days=1), clock)
        return ScheduleSpec(Recurrence.ONE_TIME, one_time_at=target)

    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) at (.+)", phrase)
    if match:
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise ValueError("Use a valid date in YYYY-MM-DD form.") from exc
        clock = _parse_clock(match.group(2))
        if clock is None:
            raise ValueError("Use a time such as 09:00, 9 or 9:30 pm.")
        return ScheduleSpec(
            Recurrence.ONE_TIME, one_time_at=datetime.combine(day, clock)
        )

    raise ValueError(
        "Try ‘in 20 minutes’, ‘daily at 9’, ‘weekdays at 09:00’, "
        "‘every 2 hours’, or ‘tomorrow at 8 pm’."
    )


@dataclass(frozen=True)
class Reminder:
    id: str
    kind: str
    title: str
    icon: str
    message: str
    recurrence: Recurrence
    enabled: bool = True
    urgent: bool = False
    time_of_day: dtime | None = None
    one_time_at: datetime | None = None
    interval_minutes: int | None = None
    weekdays: tuple[int, ...] = ()
    snooze_minutes: int = 10
    action_id: str | None = None

    def pick_message(self, _rng: random.Random) -> str:
        return self.message

    def schedule(self) -> ScheduleSpec:
        return ScheduleSpec(
            self.recurrence,
            self.time_of_day,
            self.one_time_at,
            self.interval_minutes,
            self.weekdays,
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "icon": self.icon,
            "message": self.message,
            "recurrence": self.recurrence.value,
            "enabled": self.enabled,
            "urgent": self.urgent,
            "snooze_minutes": self.snooze_minutes,
        }
        if self.time_of_day is not None:
            data["time"] = format_hhmm(self.time_of_day)
        if self.one_time_at is not None:
            data["one_time_at"] = self.one_time_at.isoformat()
        if self.interval_minutes is not None:
            data["interval_minutes"] = self.interval_minutes
        if self.weekdays:
            data["weekdays"] = list(self.weekdays)
        if self.action_id:
            data["action_id"] = self.action_id
        return data

    @classmethod
    def from_dict(cls, data: object) -> "Reminder | None":
        if not isinstance(data, dict):
            return None
        reminder_id = _stable_id(data.get("id"))
        title = str(data.get("title", "")).strip()[:80]
        if not reminder_id or not title:
            return None
        try:
            recurrence = Recurrence(str(data.get("recurrence", "daily")))
        except ValueError:
            recurrence = Recurrence.DAILY
        time_of_day = None
        one_time_at = None
        interval = None
        weekdays: tuple[int, ...] = ()
        if recurrence in (Recurrence.DAILY, Recurrence.WEEKDAYS):
            time_of_day = parse_hhmm(data.get("time"), "09:00")
            if recurrence is Recurrence.WEEKDAYS:
                raw_days = data.get("weekdays", (0, 1, 2, 3, 4))
                if not isinstance(raw_days, (list, tuple)):
                    raw_days = (0, 1, 2, 3, 4)
                days: set[int] = set()
                for value in raw_days:
                    try:
                        day = int(value)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= day <= 6:
                        days.add(day)
                weekdays = tuple(sorted(days)) or (0, 1, 2, 3, 4)
        elif recurrence is Recurrence.ONE_TIME:
            one_time_at = _parse_datetime(data.get("one_time_at"))
            if one_time_at is None:
                return None
        else:
            try:
                interval = max(1, min(10080, int(data.get("interval_minutes", 60))))
            except (TypeError, ValueError):
                interval = 60
        try:
            snooze = max(1, min(1440, int(data.get("snooze_minutes", 10))))
        except (TypeError, ValueError):
            snooze = 10
        message = str(data.get("message") or f"{title}!").strip()[:500]
        raw_action_id = data.get("action_id")
        action_id = (
            _stable_id(raw_action_id) if isinstance(raw_action_id, str) else None
        ) or None
        return cls(
            id=reminder_id,
            kind=str(data.get("kind", "custom")).strip()[:32] or "custom",
            title=title,
            icon=str(data.get("icon", "⏰")).strip()[:8] or "⏰",
            message=message,
            recurrence=recurrence,
            enabled=bool(data.get("enabled", True)),
            urgent=bool(data.get("urgent", False)),
            time_of_day=time_of_day,
            one_time_at=one_time_at,
            interval_minutes=interval,
            weekdays=weekdays,
            snooze_minutes=snooze,
            action_id=action_id,
        )


@dataclass(frozen=True)
class ReminderOccurrence:
    reminder: Reminder
    scheduled_for: datetime
    snoozed: bool = False

    @property
    def id(self) -> str:
        return self.reminder.id


@dataclass(frozen=True)
class HistoryEntry:
    reminder_id: str
    title: str
    status: HistoryStatus
    scheduled_for: datetime
    handled_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "reminder_id": self.reminder_id,
            "title": self.title,
            "status": self.status.value,
            "scheduled_for": self.scheduled_for.isoformat(),
            "handled_at": self.handled_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "HistoryEntry | None":
        if not isinstance(data, dict):
            return None
        scheduled = _parse_datetime(data.get("scheduled_for"))
        handled = _parse_datetime(data.get("handled_at"))
        try:
            status = HistoryStatus(str(data.get("status")))
        except ValueError:
            return None
        reminder_id = _stable_id(data.get("reminder_id"))
        if not reminder_id or scheduled is None or handled is None:
            return None
        return cls(
            reminder_id,
            str(data.get("title", reminder_id))[:80],
            status,
            scheduled,
            handled,
        )


@dataclass
class ReminderState:
    schema_version: int = CURRENT_WELLNESS_SCHEMA_VERSION
    last_done: dict[str, datetime] = field(default_factory=dict)
    snooze_until: dict[str, datetime] = field(default_factory=dict)
    last_triggered: dict[str, datetime] = field(default_factory=dict)
    history: list[HistoryEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        def dates(values: dict[str, datetime]) -> dict[str, str]:
            return {key: value.isoformat() for key, value in values.items()}

        return {
            "schema_version": self.schema_version,
            "last_done": dates(self.last_done),
            "snooze_until": dates(self.snooze_until),
            "last_triggered": dates(self.last_triggered),
            "history": [entry.to_dict() for entry in self.history],
        }

    @classmethod
    def from_dict(cls, data: object) -> "ReminderState":
        if not isinstance(data, dict):
            return cls()
        try:
            version = int(data.get("schema_version", 0))
        except (TypeError, ValueError):
            version = 0
        state = cls(schema_version=max(version, CURRENT_WELLNESS_SCHEMA_VERSION))
        for field_name in ("last_done", "snooze_until", "last_triggered"):
            raw = data.get(field_name)
            if not isinstance(raw, dict):
                continue
            target = getattr(state, field_name)
            for key, value in raw.items():
                parsed = _parse_datetime(value)
                if parsed is not None:
                    target[_stable_id(key)] = parsed
        raw_history = data.get("history")
        if isinstance(raw_history, list):
            state.history = [
                entry
                for item in raw_history[-MAX_HISTORY_ENTRIES:]
                if (entry := HistoryEntry.from_dict(item)) is not None
            ]
        return state


def build_reminders(config) -> list[Reminder]:  # noqa: ANN001
    raw = getattr(config, "reminders", [])
    if not isinstance(raw, list):
        return []
    reminders: list[Reminder] = []
    seen: set[str] = set()
    for item in raw:
        reminder = Reminder.from_dict(item)
        if reminder is None or reminder.id in seen:
            continue
        seen.add(reminder.id)
        reminders.append(reminder)
    return reminders


class WellnessEngine:
    """Decides when reminders are due and records terminal outcomes."""

    def __init__(
        self,
        config,  # noqa: ANN001
        state: ReminderState | None = None,
        rng: random.Random | None = None,
        now_fn: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.state = state or ReminderState()
        self.rng = rng or random.Random()
        self.now_fn = now_fn
        self.reminders = build_reminders(config)
        self.dirty = False
        self._sanitize()

    def _sanitize(self) -> None:
        now = self.now_fn()
        for reminder in self.reminders:
            if reminder.recurrence is not Recurrence.INTERVAL:
                continue
            last = self.state.last_done.get(reminder.id)
            interval = timedelta(minutes=reminder.interval_minutes or 60)
            if last is None or last > now or now - last > interval * 3:
                self.state.last_done[reminder.id] = now
                self.dirty = True

    def active_hours_ok(self, now: datetime) -> bool:
        start = parse_hhmm(getattr(self.config, "active_start", "09:00"))
        end = parse_hhmm(getattr(self.config, "active_end", "22:30"), "22:30")
        current = now.time()
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def enabled(self, reminder: Reminder | None = None) -> bool:
        master = bool(getattr(self.config, "reminders_enabled", True))
        return master and (reminder is None or reminder.enabled)

    def due(self, now: datetime | None = None) -> list[ReminderOccurrence]:
        now = now or self.now_fn()
        if not self.enabled():
            return []
        result: list[ReminderOccurrence] = []
        grace = timedelta(
            minutes=int(getattr(self.config, "reminder_grace_minutes", 45))
        )
        for reminder in self.reminders:
            if not self.enabled(reminder):
                continue
            quiet = not reminder.urgent and not self.active_hours_ok(now)
            snooze = self.state.snooze_until.get(reminder.id)
            if snooze is not None:
                if now >= snooze and not quiet:
                    result.append(ReminderOccurrence(reminder, snooze, True))
                continue
            scheduled = self._current_occurrence(reminder, now)
            if scheduled is None or self._handled(reminder.id, scheduled):
                continue
            if now < scheduled or quiet:
                continue
            if reminder.recurrence is Recurrence.INTERVAL or now <= scheduled + grace:
                result.append(ReminderOccurrence(reminder, scheduled))
            else:
                self._append_history(reminder, HistoryStatus.MISSED, scheduled, now)
                self.state.last_triggered[reminder.id] = scheduled
                self.dirty = True
        result.sort(key=lambda item: item.scheduled_for)
        return result

    def mark_triggered(self, occurrence: ReminderOccurrence) -> None:
        self.state.last_triggered[occurrence.id] = occurrence.scheduled_for
        if occurrence.snoozed:
            self.state.snooze_until.pop(occurrence.id, None)
        self.dirty = True

    def mark_done(self, reminder: Reminder, now: datetime | None = None) -> None:
        now = now or self.now_fn()
        scheduled = self.state.last_triggered.get(reminder.id, now)
        self._append_history(reminder, HistoryStatus.DONE, scheduled, now)
        self.state.last_done[reminder.id] = now
        self.state.snooze_until.pop(reminder.id, None)
        self.dirty = True

    def mark_missed(self, reminder: Reminder, now: datetime | None = None) -> None:
        now = now or self.now_fn()
        scheduled = self.state.last_triggered.get(reminder.id, now)
        self._append_history(reminder, HistoryStatus.MISSED, scheduled, now)
        self.state.last_done[reminder.id] = now
        self.state.snooze_until.pop(reminder.id, None)
        self.dirty = True

    def snooze(
        self,
        reminder: Reminder,
        minutes: int | None = None,
        now: datetime | None = None,
    ) -> datetime:
        now = now or self.now_fn()
        delay = max(1, int(minutes or reminder.snooze_minutes))
        until = now + timedelta(minutes=delay)
        scheduled = self.state.last_triggered.get(reminder.id, now)
        self._append_history(reminder, HistoryStatus.SNOOZED, scheduled, now)
        self.state.snooze_until[reminder.id] = until
        self.dirty = True
        return until

    def find(self, key: str) -> Reminder | None:
        lookup = _stable_id(key)
        for reminder in self.reminders:
            if reminder.id == lookup or reminder.kind == key:
                return reminder
        return None

    def upcoming(
        self, count: int = 5, now: datetime | None = None
    ) -> list[tuple[datetime, Reminder]]:
        now = now or self.now_fn()
        entries: list[tuple[datetime, Reminder]] = []
        for reminder in self.reminders:
            if not self.enabled(reminder):
                continue
            snooze = self.state.snooze_until.get(reminder.id)
            if snooze is not None:
                entries.append((snooze, reminder))
                continue
            scheduled = self._next_occurrence(reminder, now)
            if scheduled is not None:
                entries.append((scheduled, reminder))
        entries.sort(key=lambda item: item[0])
        return entries[: max(0, int(count))]

    def recent_history(self, count: int = 20) -> list[HistoryEntry]:
        return list(reversed(self.state.history[-max(0, int(count)) :]))

    def _current_occurrence(self, reminder: Reminder, now: datetime) -> datetime | None:
        if reminder.recurrence is Recurrence.ONE_TIME:
            return reminder.one_time_at
        if reminder.recurrence in (Recurrence.DAILY, Recurrence.WEEKDAYS):
            if (
                reminder.recurrence is Recurrence.WEEKDAYS
                and now.weekday() not in reminder.weekdays
            ):
                return None
            return datetime.combine(now.date(), reminder.time_of_day or dtime(9))
        interval = timedelta(minutes=reminder.interval_minutes or 60)
        base = self.state.last_done.get(reminder.id, now)
        triggered = self.state.last_triggered.get(reminder.id)
        if triggered is not None and triggered > base:
            base = triggered
        return base + interval

    def _next_occurrence(self, reminder: Reminder, now: datetime) -> datetime | None:
        if reminder.recurrence is Recurrence.ONE_TIME:
            scheduled = reminder.one_time_at
            if scheduled is None or self._handled(reminder.id, scheduled):
                return None
            return scheduled
        if reminder.recurrence is Recurrence.INTERVAL:
            return self._current_occurrence(reminder, now)
        clock = reminder.time_of_day or dtime(9)
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            if (
                reminder.recurrence is Recurrence.WEEKDAYS
                and day.weekday() not in reminder.weekdays
            ):
                continue
            scheduled = datetime.combine(day, clock)
            if scheduled < now or self._handled(reminder.id, scheduled):
                continue
            return scheduled
        return None

    def _handled(self, reminder_id: str, scheduled: datetime) -> bool:
        triggered = self.state.last_triggered.get(reminder_id)
        done = self.state.last_done.get(reminder_id)
        return bool(
            (triggered is not None and triggered >= scheduled)
            or (done is not None and done >= scheduled)
        )

    def _append_history(
        self,
        reminder: Reminder,
        status: HistoryStatus,
        scheduled: datetime,
        handled: datetime,
    ) -> None:
        entry = HistoryEntry(reminder.id, reminder.title, status, scheduled, handled)
        if self.state.history and self.state.history[-1] == entry:
            return
        self.state.history.append(entry)
        del self.state.history[:-MAX_HISTORY_ENTRIES]
        self.dirty = True
