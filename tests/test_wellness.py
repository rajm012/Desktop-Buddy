"""Tests for the wellness reminder scheduler."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta

from desktop_buddy.config import Config
from desktop_buddy.wellness import (
    CURRENT_WELLNESS_SCHEMA_VERSION,
    HistoryStatus,
    Recurrence,
    Reminder,
    ReminderState,
    WellnessEngine,
    parse_reminder_phrase,
)


def engine_at(
    moment: datetime, config: Config | None = None, state=None
) -> WellnessEngine:
    return WellnessEngine(
        config or Config(), state, random.Random(3), now_fn=lambda: moment
    )


def update_reminder(config: Config, reminder_id: str, **changes: object) -> None:
    for reminder in config.reminders:
        if reminder.get("id") == reminder_id:
            reminder.update(changes)
            return
    raise AssertionError(f"missing reminder {reminder_id}")


class MealReminderTests(unittest.TestCase):
    def test_breakfast_due_at_its_time(self) -> None:
        engine = engine_at(datetime(2026, 10, 3, 9, 0))
        self.assertIn("breakfast", [r.id for r in engine.due()])

    def test_breakfast_not_due_before_its_time(self) -> None:
        engine = engine_at(datetime(2026, 10, 3, 8, 50))
        self.assertNotIn("breakfast", [r.id for r in engine.due()])

    def test_grace_window_limits_late_nags(self) -> None:
        late = engine_at(datetime(2026, 10, 3, 9, 30))
        self.assertIn("breakfast", [r.id for r in late.due()])
        too_late = engine_at(datetime(2026, 10, 3, 10, 30))
        self.assertNotIn("breakfast", [r.id for r in too_late.due()])

    def test_meal_does_not_fire_twice_a_day(self) -> None:
        engine = engine_at(datetime(2026, 10, 3, 9, 0))
        reminder = engine.find("breakfast")
        self.assertIsNotNone(reminder)
        engine.mark_done(reminder, datetime(2026, 10, 3, 9, 0))
        later = engine_at(datetime(2026, 10, 3, 9, 20), Config(), engine.state)
        self.assertNotIn("breakfast", [r.id for r in later.due()])

    def test_snooze_refires_after_delay(self) -> None:
        engine = engine_at(datetime(2026, 10, 3, 13, 30))
        lunch = engine.find("lunch")
        self.assertIsNotNone(lunch)
        engine.snooze(lunch, 10, datetime(2026, 10, 3, 13, 30))
        self.assertNotIn(
            "lunch", [r.id for r in engine.due(datetime(2026, 10, 3, 13, 35))]
        )
        self.assertIn(
            "lunch", [r.id for r in engine.due(datetime(2026, 10, 3, 13, 41))]
        )

    def test_disabled_meals_are_skipped(self) -> None:
        config = Config()
        update_reminder(config, "lunch", enabled=False)
        engine = engine_at(datetime(2026, 10, 3, 13, 30), config)
        self.assertNotIn("lunch", [r.id for r in engine.due()])

    def test_reminders_can_be_switched_off(self) -> None:
        config = Config()
        config.reminders_enabled = False
        engine = engine_at(datetime(2026, 10, 3, 13, 30), config)
        self.assertEqual(engine.due(), [])


class IntervalReminderTests(unittest.TestCase):
    def test_water_fires_after_interval(self) -> None:
        config = Config()
        update_reminder(config, "water", interval_minutes=30)
        state = ReminderState()
        state.last_done["water"] = datetime(2026, 10, 3, 11, 0)
        engine = engine_at(datetime(2026, 10, 3, 11, 40), config, state)
        self.assertIn("water", [r.id for r in engine.due()])

    def test_water_waits_for_interval(self) -> None:
        config = Config()
        update_reminder(config, "water", interval_minutes=30)
        state = ReminderState()
        state.last_done["water"] = datetime(2026, 10, 3, 11, 30)
        engine = engine_at(datetime(2026, 10, 3, 11, 40), config, state)
        self.assertNotIn("water", [r.id for r in engine.due()])

    def test_water_respects_active_hours(self) -> None:
        config = Config()
        update_reminder(config, "water", interval_minutes=30)
        state = ReminderState()
        state.last_done["water"] = datetime(2026, 10, 3, 2, 20)
        engine = engine_at(datetime(2026, 10, 3, 3, 0), config, state)
        self.assertNotIn("water", [r.id for r in engine.due()])

    def test_first_interval_starts_at_launch(self) -> None:
        config = Config()
        update_reminder(config, "water", interval_minutes=45)
        engine = engine_at(datetime(2026, 10, 3, 12, 0), config)
        self.assertNotIn("water", [r.id for r in engine.due()])
        self.assertIn(
            "water", [r.id for r in engine.due(datetime(2026, 10, 3, 12, 50))]
        )


class UpcomingTests(unittest.TestCase):
    def test_upcoming_is_sorted(self) -> None:
        engine = engine_at(datetime(2026, 10, 3, 10, 0))
        entries = engine.upcoming(6)
        self.assertTrue(entries)
        times = [when for when, _ in entries]
        self.assertEqual(times, sorted(times))

    def test_state_roundtrip(self) -> None:
        state = ReminderState()
        state.last_done["water"] = datetime(2026, 10, 3, 10, 0)
        state.snooze_until["lunch"] = datetime(2026, 10, 3, 13, 45)
        restored = ReminderState.from_dict(state.to_dict())
        self.assertEqual(restored.schema_version, CURRENT_WELLNESS_SCHEMA_VERSION)
        self.assertEqual(restored.last_done["water"], state.last_done["water"])
        self.assertEqual(restored.snooze_until["lunch"], state.snooze_until["lunch"])

    def test_legacy_state_gets_schema_version(self) -> None:
        restored = ReminderState.from_dict(
            {"last_done": {"water": "2026-10-03T10:00:00"}}
        )
        self.assertEqual(restored.schema_version, CURRENT_WELLNESS_SCHEMA_VERSION)
        self.assertEqual(restored.last_done["water"], datetime(2026, 10, 3, 10, 0))

    def test_state_handles_garbage(self) -> None:
        restored = ReminderState.from_dict(
            {"last_done": {"water": "not a date"}, "snooze_until": {}}
        )
        self.assertEqual(restored.last_done, {})


class PhraseParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 11, 3, 10, 0)

    def test_relative_one_time_phrase(self) -> None:
        spec = parse_reminder_phrase("in 20 minutes", self.now)
        self.assertEqual(spec.recurrence, Recurrence.ONE_TIME)
        self.assertEqual(spec.one_time_at, self.now + timedelta(minutes=20))

    def test_weekday_phrase(self) -> None:
        spec = parse_reminder_phrase("weekdays at 9", self.now)
        self.assertEqual(spec.recurrence, Recurrence.WEEKDAYS)
        self.assertEqual(spec.time_of_day.hour, 9)
        self.assertEqual(spec.weekdays, (0, 1, 2, 3, 4))

    def test_daily_meridiem_and_interval_phrases(self) -> None:
        daily = parse_reminder_phrase("daily at 9:30 pm", self.now)
        interval = parse_reminder_phrase("every 2 hours", self.now)
        self.assertEqual((daily.time_of_day.hour, daily.time_of_day.minute), (21, 30))
        self.assertEqual(interval.interval_minutes, 120)

    def test_invalid_phrase_has_helpful_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "in 20 minutes"):
            parse_reminder_phrase("whenever", self.now)


class GeneralReminderTests(unittest.TestCase):
    def test_one_time_reminder_only_fires_once(self) -> None:
        config = Config()
        config.reminders = [
            {
                "id": "medicine",
                "title": "Medicine",
                "message": "Take medicine",
                "recurrence": "one_time",
                "one_time_at": "2026-11-03T10:20:00",
            }
        ]
        engine = engine_at(datetime(2026, 11, 3, 10, 20), config)
        occurrence = engine.due()[0]
        engine.mark_triggered(occurrence)
        engine.mark_done(occurrence.reminder, datetime(2026, 11, 3, 10, 21))
        self.assertEqual(engine.due(datetime(2026, 11, 3, 10, 30)), [])

    def test_weekday_reminder_skips_weekends(self) -> None:
        config = Config()
        config.reminders = [
            {
                "id": "standup",
                "title": "Stand-up",
                "recurrence": "weekdays",
                "time": "09:00",
            }
        ]
        friday = engine_at(datetime(2026, 11, 6, 9, 0), config)
        saturday = engine_at(datetime(2026, 11, 7, 9, 0), config)
        self.assertEqual([item.id for item in friday.due()], ["standup"])
        self.assertEqual(saturday.due(), [])

    def test_quiet_hours_block_nonurgent_but_not_urgent(self) -> None:
        config = Config()
        config.reminders = [
            {
                "id": "quiet",
                "title": "Quiet",
                "recurrence": "daily",
                "time": "03:00",
                "urgent": False,
            },
            {
                "id": "urgent",
                "title": "Urgent",
                "recurrence": "daily",
                "time": "03:00",
                "urgent": True,
            },
        ]
        engine = engine_at(datetime(2026, 11, 3, 3, 0), config)
        self.assertEqual([item.id for item in engine.due()], ["urgent"])

    def test_missed_and_snoozed_history_is_recorded(self) -> None:
        config = Config()
        config.reminder_grace_minutes = 5
        config.reminders = [
            {
                "id": "call",
                "title": "Call",
                "recurrence": "daily",
                "time": "10:00",
                "urgent": True,
            }
        ]
        engine = engine_at(datetime(2026, 11, 3, 10, 10), config)
        self.assertEqual(engine.due(), [])
        self.assertEqual(engine.state.history[-1].status, HistoryStatus.MISSED)

        reminder = Reminder.from_dict(config.reminders[0])
        self.assertIsNotNone(reminder)
        engine.state.last_triggered["call"] = datetime(2026, 11, 4, 10, 0)
        engine.snooze(reminder, 10, datetime(2026, 11, 4, 10, 0))
        self.assertEqual(engine.state.history[-1].status, HistoryStatus.SNOOZED)

    def test_local_wall_clock_schedule_is_deterministic(self) -> None:
        spec = parse_reminder_phrase("tomorrow at 8 pm", datetime(2026, 11, 3, 23, 55))
        self.assertEqual(spec.one_time_at, datetime(2026, 11, 4, 20, 0))

    def test_state_handles_non_mapping_json(self) -> None:
        restored = ReminderState.from_dict([])
        self.assertEqual(restored.schema_version, CURRENT_WELLNESS_SCHEMA_VERSION)
        self.assertEqual(restored.last_done, {})


if __name__ == "__main__":
    unittest.main()
