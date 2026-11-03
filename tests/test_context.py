"""Phase 6 context-policy and calendar integration tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from desktop_buddy.builtin_plugins import (
    CALENDAR_PLUGIN_METADATA,
    LocalCalendarPlugin,
)
from desktop_buddy.calendar_integration import (
    current_event,
    parse_icalendar,
    upcoming_events,
)
from desktop_buddy.config import Config
from desktop_buddy.context import (
    ApplicationProfile,
    ContextEngine,
    NetworkState,
    NetworkStatus,
    profiles_from_config,
)
from desktop_buddy.plugins import PluginHost, PluginManager, PluginStatus


class ContextEngineTests(unittest.TestCase):
    def test_profile_fullscreen_battery_and_network_changes_are_stable(self) -> None:
        profile = ApplicationProfile(
            "calls", "Video calls", class_contains="zoom", pause_animation=True
        )
        engine = ContextEngine([profile], low_battery_percent=25)
        changes = engine.update(
            idle_seconds=42,
            fullscreen=True,
            active_class="us.zoom.Zoom",
            active_title="Daily call",
            on_battery=True,
            battery_percent=20,
            network=NetworkStatus(NetworkState.ONLINE, "wlan0"),
        )
        self.assertEqual(engine.snapshot.profile_id, "calls")
        self.assertTrue(engine.snapshot.profile_pauses_animation)
        self.assertTrue(engine.snapshot.low_battery)
        self.assertFalse(
            engine.attention_allowed(suppress_fullscreen=True, suppress_meetings=True)
        )
        self.assertTrue(
            engine.attention_allowed(
                suppress_fullscreen=True, suppress_meetings=True, urgent=True
            )
        )
        self.assertIn("system.network", {change.name for change in changes})
        self.assertEqual(
            engine.update(
                idle_seconds=43,
                fullscreen=True,
                active_class="us.zoom.Zoom",
                active_title="Daily call",
                on_battery=True,
                battery_percent=20,
                network=NetworkStatus(NetworkState.ONLINE, "wlan0"),
            ),
            [],
        )

    def test_invalid_and_duplicate_profiles_are_removed(self) -> None:
        raw = [
            {"id": "work", "name": "Work", "class_contains": "code"},
            {"id": "work", "name": "Duplicate", "class_contains": "other"},
            {"id": "", "name": "Invalid", "class_contains": "x"},
        ]
        profiles = profiles_from_config(raw)
        self.assertEqual([profile.id for profile in profiles], ["work"])


class CalendarIntegrationTests(unittest.TestCase):
    def test_parser_unfolds_text_and_finds_current_and_upcoming_events(self) -> None:
        text = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "UID:daily\n"
            "SUMMARY:Daily\\, sync\n"
            "DTSTART:20261103T120000\n"
            "DTEND:20261103T123000\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        events = parse_icalendar(text, "work.ics")
        self.assertEqual(events[0].title, "Daily, sync")
        now = datetime(2026, 11, 3, 12, 10)
        self.assertEqual(current_event(events, now), events[0])
        self.assertEqual(upcoming_events(events, datetime(2026, 11, 3, 11, 0)), events)

    def test_calendar_plugin_is_read_only_permissioned_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now().replace(microsecond=0)
            start = now + timedelta(minutes=30)
            end = start + timedelta(minutes=30)
            path = Path(tmp) / "calendar.ics"
            path.write_text(
                "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:future\n"
                f"SUMMARY:Planning\nDTSTART:{start:%Y%m%dT%H%M%S}\n"
                f"DTEND:{end:%Y%m%dT%H%M%S}\nEND:VEVENT\nEND:VCALENDAR\n",
                encoding="utf-8",
            )
            config = Config(calendar_sources=[str(path)], calendar_reminder_minutes=5)
            reminders: dict[str, dict[str, object]] = {}
            settings: dict[str, object] = {}

            def register_reminder(_plugin: str, definition: dict[str, object]):
                reminder_id = str(definition["id"])
                reminders[reminder_id] = definition
                return lambda: reminders.pop(reminder_id, None)

            def register_settings(_plugin: str, page_id: str, _title: str, factory):
                settings[page_id] = factory
                return lambda: settings.pop(page_id, None)

            host = PluginHost(
                lambda *_args: lambda: None,
                register_reminder,
                lambda *_args: lambda: None,
                register_settings,
            )
            manager = PluginManager(
                app_version="1.7.0",
                config_state={},
                available_capabilities=set(),
                host=host,
            )
            manager.register_builtin(
                CALENDAR_PLUGIN_METADATA,
                lambda: LocalCalendarPlugin(config, lambda: None),
            )
            self.assertTrue(
                manager.enable(
                    CALENDAR_PLUGIN_METADATA.id,
                    set(CALENDAR_PLUGIN_METADATA.permissions),
                )
            )
            self.assertEqual(
                manager.records[CALENDAR_PLUGIN_METADATA.id].status,
                PluginStatus.ACTIVE,
            )
            self.assertEqual(len(reminders), 1)
            self.assertIn("local-calendar-calendar", settings)
            manager.set_permissions(CALENDAR_PLUGIN_METADATA.id, set())
            self.assertEqual(reminders, {})
            self.assertEqual(settings, {})


if __name__ == "__main__":
    unittest.main()
