"""Wellness reminder scheduling (pure logic, no Qt).

Boo can nudge you about meals, snacks, water and stretch breaks. Everything
here is timezone-naive local time and easily unit-testable via `now_fn`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable


@dataclass(frozen=True)
class Reminder:
    id: str
    kind: str  # meal | water | break | winddown
    title: str
    icon: str
    messages: tuple[str, ...]
    time_of_day: dtime | None = None
    interval_minutes: int | None = None
    snooze_minutes: int = 10

    def pick_message(self, rng: random.Random) -> str:
        return rng.choice(self.messages)


@dataclass
class ReminderState:
    last_done: dict[str, datetime] = field(default_factory=dict)
    snooze_until: dict[str, datetime] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            "last_done": {
                key: value.isoformat() for key, value in self.last_done.items()
            },
            "snooze_until": {
                key: value.isoformat() for key, value in self.snooze_until.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReminderState":
        state = cls()
        for key, value in (data.get("last_done") or {}).items():
            try:
                state.last_done[key] = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                continue
        for key, value in (data.get("snooze_until") or {}).items():
            try:
                state.snooze_until[key] = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                continue
        return state


WATER_MESSAGES = (
    "Water break! Your ghost is 90% water and wants some company. 💧",
    "Sip sip! Hydration check. 💧",
    "A glass of water would taste great right now. 💧",
    "Boo says: drink up, human! 💧",
)

BREAK_MESSAGES = (
    "Stand up, stretch, and look far away for 20 seconds. 🧘",
    "Break time! Roll your shoulders and unclench your jaw. 🌿",
    "Screen break — let your eyes rest for a minute. 👀",
    "Quick stretch break! Boo will keep your chair warm.",
)

BREAKFAST_MESSAGES = (
    "Breakfast time! Don't skip it. 🥞",
    "Morning fuel o'clock — something warm and tasty. 🥣",
    "Breakfast! Your brain wants porridge, eggs, or fruit. 🍳",
)

LUNCH_MESSAGES = (
    "Lunch time! Step away from the screen. 🍛",
    "Lunch o'clock — eat something that makes you happy. 🥗",
    "Time to feed the human. Lunch! 🍜",
)

SNACK_MESSAGES = (
    "Little snack o'clock? Fruit or nuts would be lovely. 🍎",
    "Snack break! Something small and nice. 🥜",
    "Feeling peckish? A snack never hurt. 🍪",
)

DINNER_MESSAGES = (
    "Dinner time! Close the laptop and eat properly. 🍽",
    "Dinner o'clock — you've earned it. 🍲",
    "Time for dinner. Boo is drooling (ghosts can drool). 👻",
)

WINDDOWN_MESSAGES = (
    "It's getting late — Boo is feeling sleepy. 💤",
    "Wind down: dim the lights, stretch, and rest your eyes. 🌙",
    "Almost bedtime. Tomorrow's code will still be there. 😴",
)


def parse_hhmm(value: str, fallback: str) -> dtime:
    for candidate in (value, fallback):
        try:
            hours, minutes = str(candidate).strip().split(":", 1)
            hour = int(hours)
            minute = int(minutes)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return dtime(hour=hour, minute=minute)
        except (TypeError, ValueError, AttributeError):
            continue
    return dtime(hour=9, minute=0)


def format_hhmm(value: dtime) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def build_reminders(config) -> list[Reminder]:  # noqa: ANN001 - duck-typed Config
    reminders: list[Reminder] = []
    if getattr(config, "breakfast_enabled", True):
        reminders.append(
            Reminder(
                id="breakfast",
                kind="meal",
                title="Breakfast",
                icon="🥞",
                messages=BREAKFAST_MESSAGES,
                time_of_day=parse_hhmm(config.breakfast_time, "09:00"),
                snooze_minutes=15,
            )
        )
    if getattr(config, "lunch_enabled", True):
        reminders.append(
            Reminder(
                id="lunch",
                kind="meal",
                title="Lunch",
                icon="🍛",
                messages=LUNCH_MESSAGES,
                time_of_day=parse_hhmm(config.lunch_time, "13:30"),
                snooze_minutes=15,
            )
        )
    if getattr(config, "snack_enabled", True):
        reminders.append(
            Reminder(
                id="snack",
                kind="meal",
                title="Snack",
                icon="🍎",
                messages=SNACK_MESSAGES,
                time_of_day=parse_hhmm(config.snack_time, "16:30"),
                snooze_minutes=15,
            )
        )
    if getattr(config, "dinner_enabled", True):
        reminders.append(
            Reminder(
                id="dinner",
                kind="meal",
                title="Dinner",
                icon="🍽",
                messages=DINNER_MESSAGES,
                time_of_day=parse_hhmm(config.dinner_time, "21:00"),
                snooze_minutes=15,
            )
        )
    if getattr(config, "water_enabled", True):
        reminders.append(
            Reminder(
                id="water",
                kind="water",
                title="Water break",
                icon="💧",
                messages=WATER_MESSAGES,
                interval_minutes=int(getattr(config, "water_interval_minutes", 45)),
                snooze_minutes=10,
            )
        )
    if getattr(config, "break_enabled", True):
        reminders.append(
            Reminder(
                id="break",
                kind="break",
                title="Stretch break",
                icon="🧘",
                messages=BREAK_MESSAGES,
                interval_minutes=int(getattr(config, "break_interval_minutes", 60)),
                snooze_minutes=10,
            )
        )
    if getattr(config, "winddown_enabled", True):
        reminders.append(
            Reminder(
                id="winddown",
                kind="winddown",
                title="Wind down",
                icon="🌙",
                messages=WINDDOWN_MESSAGES,
                time_of_day=parse_hhmm(config.winddown_time, "23:00"),
                snooze_minutes=20,
            )
        )
    return reminders


class WellnessEngine:
    """Decides when a reminder is due and tracks done/snoozed state."""

    def __init__(
        self,
        config,  # noqa: ANN001 - duck-typed Config
        state: ReminderState | None = None,
        rng: random.Random | None = None,
        now_fn: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.state = state or ReminderState()
        self.rng = rng or random.Random()
        self.now_fn = now_fn
        self.reminders = build_reminders(config)
        self._sanitize()

    # ------------------------------------------------------------------ helpers
    def _sanitize(self) -> None:
        """Avoid instant nags after a long break or a config change."""
        now = self.now_fn()
        for reminder in self.reminders:
            if not reminder.interval_minutes:
                continue
            last = self.state.last_done.get(reminder.id)
            if last is None:
                self.state.last_done[reminder.id] = now
            elif last > now:
                self.state.last_done[reminder.id] = now
            elif now - last > timedelta(minutes=reminder.interval_minutes * 3):
                self.state.last_done[reminder.id] = now

    def active_hours_ok(self, now: datetime) -> bool:
        start = parse_hhmm(getattr(self.config, "active_start", "09:00"), "09:00")
        end = parse_hhmm(getattr(self.config, "active_end", "22:30"), "22:30")
        current = now.time()
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def enabled(self, reminder: Reminder) -> bool:
        return bool(getattr(self.config, "reminders_enabled", True))

    # -------------------------------------------------------------------- main
    def due(self, now: datetime | None = None) -> list[Reminder]:
        now = now or self.now_fn()
        if not self.enabled(None):  # type: ignore[arg-type]
            return []
        result: list[Reminder] = []
        grace = timedelta(minutes=int(getattr(self.config, "reminder_grace_minutes", 45)))
        for reminder in self.reminders:
            snooze = self.state.snooze_until.get(reminder.id)
            if snooze is not None:
                if now >= snooze:
                    self.state.snooze_until.pop(reminder.id, None)
                    result.append(reminder)
                continue
            if reminder.time_of_day is not None:
                scheduled = datetime.combine(now.date(), reminder.time_of_day)
                done = self.state.last_done.get(reminder.id)
                if done is not None and done.date() == now.date():
                    continue
                if scheduled <= now <= scheduled + grace:
                    result.append(reminder)
            elif reminder.interval_minutes:
                if not self.active_hours_ok(now):
                    continue
                last = self.state.last_done.get(reminder.id, now)
                if now - last >= timedelta(minutes=reminder.interval_minutes):
                    result.append(reminder)
        return result

    def mark_done(self, reminder: Reminder, now: datetime | None = None) -> None:
        now = now or self.now_fn()
        self.state.last_done[reminder.id] = now
        self.state.snooze_until.pop(reminder.id, None)

    def snooze(
        self, reminder: Reminder, minutes: int | None = None, now: datetime | None = None
    ) -> datetime:
        now = now or self.now_fn()
        delay = int(minutes or reminder.snooze_minutes)
        until = now + timedelta(minutes=delay)
        self.state.snooze_until[reminder.id] = until
        return until

    def find(self, key: str) -> Reminder | None:
        for reminder in self.reminders:
            if reminder.id == key or reminder.kind == key:
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
            if reminder.time_of_day is not None:
                scheduled = datetime.combine(now.date(), reminder.time_of_day)
                done = self.state.last_done.get(reminder.id)
                if (done is not None and done.date() == now.date()) or scheduled <= now:
                    scheduled += timedelta(days=1)
                entries.append((scheduled, reminder))
            elif reminder.interval_minutes:
                last = self.state.last_done.get(reminder.id, now)
                scheduled = last + timedelta(minutes=reminder.interval_minutes)
                if scheduled <= now:
                    scheduled = now + timedelta(
                        seconds=5
                    )  # due now; show it first
                entries.append((scheduled, reminder))
        entries.sort(key=lambda item: item[0])
        return entries[:count]
