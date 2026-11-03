"""Built-in plugins shipped with Desktop Buddy.

Built-ins use exactly the same public context as external plugins. The example is
disabled by default and doubles as an integration fixture and API reference.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .calendar_integration import current_event, read_calendar_files, upcoming_events
from .plugins import PluginContext, PluginMetadata, PluginPermission

EXAMPLE_PLUGIN_METADATA = PluginMetadata(
    id="example-routine",
    name="Example Routine",
    version="1.0.0",
    description="Demonstrates actions, reminders, tray items, settings, and events.",
    api_version=1,
    min_app_version="1.6.0",
    permissions=(
        PluginPermission.ACTIONS,
        PluginPermission.REMINDERS,
        PluginPermission.TRAY,
        PluginPermission.SETTINGS,
        PluginPermission.EVENTS,
    ),
    builtin=True,
)

CALENDAR_PLUGIN_METADATA = PluginMetadata(
    id="local-calendar",
    name="Local Calendar",
    version="1.0.0",
    description=(
        "Reads configured local iCalendar files for upcoming reminders and "
        "meeting-aware quiet mode. It never modifies calendar data."
    ),
    api_version=1,
    min_app_version="1.7.0",
    permissions=(
        PluginPermission.CALENDAR,
        PluginPermission.REMINDERS,
        PluginPermission.SETTINGS,
        PluginPermission.EVENTS,
    ),
    data_access=(
        "Configured local .ics/.ical file contents",
        "Event title, start time, and end time",
        "No contacts, attendees, descriptions, or calendar writes",
    ),
    builtin=True,
)


class ExampleRoutinePlugin:
    """Small optional built-in that demonstrates every limited contribution API."""

    def __init__(self) -> None:
        self.context: PluginContext | None = None
        self.cheers = 0
        self.started_events = 0

    def activate(self, context: PluginContext) -> None:
        self.context = context
        action_id = context.register_action("cheer", "Example cheer", self.cheer)
        context.register_reminder(
            {
                "id": "posture",
                "title": "Example posture check",
                "kind": "custom",
                "icon": "🧍",
                "message": "Relax your shoulders and sit comfortably.",
                "recurrence": "interval",
                "interval_minutes": 240,
                "enabled": True,
                "urgent": False,
                "snooze_minutes": 10,
                "action_id": action_id,
            }
        )
        context.register_tray_item("cheer", "Example cheer", self.cheer)
        context.register_settings_page(
            "about", "Example Routine", self.create_settings_page
        )
        context.on("app.started", self.on_started)

    def deactivate(self) -> None:
        self.context = None

    def cheer(self) -> None:
        self.cheers += 1
        if self.context is not None:
            self.context.emit("example.cheered", count=self.cheers)

    def on_started(self, _event) -> None:  # noqa: ANN001
        self.started_events += 1

    def create_settings_page(self, parent=None):  # noqa: ANN001, ANN201
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

        page = QWidget(parent)
        layout = QVBoxLayout(page)
        title = QLabel("Example Routine plugin")
        title.setStyleSheet("font-size:16px;font-weight:600;")
        body = QLabel(
            "This optional built-in demonstrates the stable plugin API. It adds a "
            "four-hour posture reminder, a safe action, a tray item, this settings "
            "page, and event subscriptions."
        )
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch()
        return page


class LocalCalendarPlugin:
    """Opt-in, read-only local calendar integration."""

    def __init__(self, config, changed) -> None:  # noqa: ANN001
        self.config = config
        self.changed = changed
        self.context: PluginContext | None = None
        self._registered: set[str] = set()
        self._last_refresh = 0.0

    def activate(self, context: PluginContext) -> None:
        self.context = context
        context.register_settings_page(
            "calendar", "Local Calendar", self.create_settings_page
        )
        context.on("system.context", self._on_context)
        self.refresh(force=True)

    def deactivate(self) -> None:
        self.context = None
        self._registered.clear()

    def _on_context(self, _event) -> None:  # noqa: ANN001
        self.refresh()

    def refresh(self, *, force: bool = False) -> None:
        now_tick = time.monotonic()
        if not force and now_tick - self._last_refresh < 60.0:
            return
        self._last_refresh = now_tick
        now = datetime.now()
        events = read_calendar_files(self.config.calendar_sources)
        context = self.context
        if context is None:
            return
        reminder_delta = timedelta(minutes=self.config.calendar_reminder_minutes)
        for event in upcoming_events(events, now):
            reminder_id = event.reminder_id
            if reminder_id in self._registered:
                continue
            remind_at = event.start - reminder_delta
            if remind_at < now:
                continue
            context.register_reminder(
                {
                    "id": reminder_id,
                    "title": event.title,
                    "kind": "calendar",
                    "icon": "📅",
                    "message": f"Upcoming: {event.title}",
                    "recurrence": "one_time",
                    "one_time_at": remind_at.isoformat(),
                    "enabled": True,
                    "urgent": False,
                    "snooze_minutes": 5,
                }
            )
            self._registered.add(reminder_id)
            context.emit(
                "calendar.upcoming",
                title=event.title,
                start=event.start.isoformat(),
            )
        meeting = current_event(events, now)
        context.emit(
            "calendar.meeting",
            active=bool(meeting),
            title=meeting.title if meeting else "",
        )

    def create_settings_page(self, parent=None):  # noqa: ANN001, ANN201
        from PyQt6.QtWidgets import (
            QCheckBox,
            QFormLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        page = QWidget(parent)
        layout = QVBoxLayout(page)
        notice = QLabel(
            "Read-only access: Desktop Buddy reads only the configured local "
            ".ics/.ical files and uses event titles and times. It does not read "
            "attendees or descriptions, contact a server, or modify calendars."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        paths = QLineEdit("; ".join(self.config.calendar_sources))
        paths.setPlaceholderText("/home/me/calendar.ics; /home/me/work.ics")
        minutes = QSpinBox()
        minutes.setRange(0, 240)
        minutes.setSuffix(" min")
        minutes.setValue(self.config.calendar_reminder_minutes)
        quiet = QCheckBox("Silence non-urgent interruptions during meetings")
        quiet.setChecked(self.config.calendar_meeting_quiet)
        form.addRow("Calendar files", paths)
        form.addRow("Remind before", minutes)
        form.addRow("Meeting-aware quiet", quiet)
        layout.addLayout(form)
        save = QPushButton("Save calendar settings")

        def persist() -> None:
            self.config.calendar_sources = [
                item.strip() for item in paths.text().split(";") if item.strip()
            ]
            self.config.calendar_reminder_minutes = minutes.value()
            self.config.calendar_meeting_quiet = quiet.isChecked()
            self.config.normalize()
            self.changed()
            self.refresh(force=True)

        save.clicked.connect(persist)
        layout.addWidget(save)
        layout.addStretch()
        return page


BUILTIN_PLUGINS = ((EXAMPLE_PLUGIN_METADATA, ExampleRoutinePlugin),)


def builtins_for(config, changed):  # noqa: ANN001, ANN201
    return (
        *BUILTIN_PLUGINS,
        (CALENDAR_PLUGIN_METADATA, lambda: LocalCalendarPlugin(config, changed)),
    )
