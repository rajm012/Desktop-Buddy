"""Read-only local iCalendar parsing for the optional calendar plugin."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class CalendarEvent:
    uid: str
    title: str
    start: datetime
    end: datetime
    source: str = ""

    @property
    def reminder_id(self) -> str:
        value = f"{self.uid}\0{self.start.isoformat()}".encode()
        return "event-" + hashlib.sha256(value).hexdigest()[:16]


def read_calendar_files(paths: list[str]) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    for value in paths:
        path = Path(value).expanduser()
        if not path.is_file() or path.suffix.lower() not in {".ics", ".ical"}:
            continue
        try:
            events.extend(parse_icalendar(path.read_text(encoding="utf-8"), str(path)))
        except OSError:
            continue
    events.sort(key=lambda item: item.start)
    return events


def parse_icalendar(text: str, source: str = "") -> list[CalendarEvent]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    current: dict[str, str] | None = None
    events: list[CalendarEvent] = []
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                event = _event_from_fields(current, source)
                if event is not None:
                    events.append(event)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.upper()] = _unescape(value)
    return events


def upcoming_events(
    events: list[CalendarEvent],
    now: datetime,
    horizon: timedelta = timedelta(days=7),
) -> list[CalendarEvent]:
    end = now + horizon
    return [event for event in events if now <= event.start <= end]


def current_event(events: list[CalendarEvent], now: datetime) -> CalendarEvent | None:
    return next((event for event in events if event.start <= now < event.end), None)


def _event_from_fields(fields: dict[str, str], source: str) -> CalendarEvent | None:
    start_pair = next(
        ((key, value) for key, value in fields.items() if key.startswith("DTSTART")),
        None,
    )
    if start_pair is None:
        return None
    end_pair = next(
        ((key, value) for key, value in fields.items() if key.startswith("DTEND")),
        None,
    )
    start = _parse_ical_datetime(*start_pair)
    if start is None:
        return None
    end = _parse_ical_datetime(*end_pair) if end_pair else None
    if end is None or end <= start:
        end = start + timedelta(hours=1)
    title = fields.get("SUMMARY", "Calendar event").strip()[:120] or "Calendar event"
    uid = fields.get("UID", f"{title}-{start.isoformat()}").strip()[:200]
    return CalendarEvent(uid, title, start, end, source)


def _parse_ical_datetime(key: str, value: str) -> datetime | None:
    value = value.strip()
    formats = ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d")
    for pattern in formats:
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        if value.endswith("Z"):
            parsed = (
                parsed.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
            )
        return parsed
    return None


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )
