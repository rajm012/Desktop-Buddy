"""Unit tests for the platform-independent focus engine."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from desktop_buddy.focus import (
    CURRENT_FOCUS_SCHEMA_VERSION,
    FocusEngine,
    FocusEventType,
    FocusSettings,
    FocusState,
    FocusStatus,
    SessionKind,
    format_duration,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


class FocusEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock(datetime(2026, 11, 3, 9, 0, 0))
        self.settings = FocusSettings(
            focus_seconds=25 * 60,
            short_break_seconds=5 * 60,
            long_break_seconds=15 * 60,
            long_break_every=2,
        )
        self.engine = FocusEngine(self.settings, now_fn=self.clock)

    def test_start_uses_absolute_deadline(self) -> None:
        self.assertTrue(self.engine.start())
        self.assertEqual(self.engine.state.status, FocusStatus.RUNNING)
        self.assertEqual(
            self.engine.state.deadline, self.clock.value + timedelta(minutes=25)
        )
        self.clock.advance(minutes=24, seconds=59)
        self.assertEqual(self.engine.remaining_seconds(), 1)
        self.assertEqual(self.engine.tick(), [])

    def test_completion_survives_large_clock_jump(self) -> None:
        self.engine.start()
        self.clock.advance(hours=3)
        events = self.engine.tick()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, FocusEventType.COMPLETED)
        self.assertEqual(events[0].kind, SessionKind.FOCUS)
        self.assertEqual(events[0].next_kind, SessionKind.SHORT_BREAK)
        self.assertEqual(self.engine.state.status, FocusStatus.STOPPED)
        self.assertEqual(self.engine.today_seconds(), 25 * 60)

    def test_pause_resume_preserves_remaining_time(self) -> None:
        self.engine.start()
        self.clock.advance(minutes=10)
        self.assertTrue(self.engine.pause())
        self.assertEqual(self.engine.state.status, FocusStatus.PAUSED)
        self.assertEqual(self.engine.remaining_seconds(), 15 * 60)
        self.clock.advance(hours=2)
        self.assertEqual(self.engine.remaining_seconds(), 15 * 60)
        self.assertTrue(self.engine.resume())
        self.clock.advance(minutes=15)
        self.assertEqual(len(self.engine.tick()), 1)

    def test_invalid_actions_are_safe_no_ops(self) -> None:
        self.assertFalse(self.engine.pause())
        self.assertFalse(self.engine.resume())
        self.assertIsNone(self.engine.skip())
        self.assertFalse(self.engine.stop())
        self.assertTrue(self.engine.start())
        self.assertFalse(self.engine.start())

    def test_skip_advances_without_credit(self) -> None:
        self.engine.start()
        event = self.engine.skip()
        self.assertIsNotNone(event)
        self.assertEqual(event.type, FocusEventType.SKIPPED)
        self.assertEqual(self.engine.state.kind, SessionKind.SHORT_BREAK)
        self.assertEqual(self.engine.today_seconds(), 0)

    def test_long_break_cadence_counts_completed_focus_sessions(self) -> None:
        for expected_break in (SessionKind.SHORT_BREAK, SessionKind.LONG_BREAK):
            self.engine.start(SessionKind.FOCUS)
            self.clock.advance(minutes=25)
            event = self.engine.tick()[0]
            self.assertEqual(event.next_kind, expected_break)
            self.engine.start()
            self.clock.advance(seconds=self.settings.duration(expected_break))
            self.engine.tick()
        self.assertEqual(self.engine.state.completed_focus_sessions, 2)
        self.assertEqual(self.engine.today_seconds(), 50 * 60)

    def test_stop_resets_cycle_to_focus(self) -> None:
        self.engine.start(SessionKind.SHORT_BREAK)
        self.assertTrue(self.engine.stop())
        self.assertEqual(self.engine.state.status, FocusStatus.STOPPED)
        self.assertEqual(self.engine.state.kind, SessionKind.FOCUS)

    def test_config_changes_only_affect_future_sessions(self) -> None:
        self.engine.start()
        self.engine.set_settings(FocusSettings(focus_seconds=60))
        self.assertEqual(self.engine.state.session_duration_seconds, 25 * 60)
        self.engine.stop()
        self.engine.start()
        self.assertEqual(self.engine.state.session_duration_seconds, 60)

    def test_completion_is_credited_to_local_completion_day(self) -> None:
        self.clock.value = datetime(2026, 11, 3, 23, 50)
        self.engine.start()
        self.clock.advance(minutes=25)
        self.engine.tick()
        self.assertNotIn("2026-11-03", self.engine.state.history)
        self.assertEqual(self.engine.state.history["2026-11-04"], 25 * 60)

    def test_delayed_tick_credits_the_deadline_day(self) -> None:
        self.clock.value = datetime(2026, 11, 3, 23, 50)
        self.engine.start()
        self.clock.advance(days=2)
        self.engine.tick()
        self.assertEqual(self.engine.state.history, {"2026-11-04": 25 * 60})
        self.assertEqual(
            self.engine.state.last_completed_at, datetime(2026, 11, 4, 0, 15)
        )

    def test_recent_history_includes_empty_days(self) -> None:
        self.engine.state.history["2026-11-02"] = 1200
        history = self.engine.recent_history(3)
        self.assertEqual([seconds for _day, seconds in history], [0, 1200, 0])


class FocusStateTests(unittest.TestCase):
    def test_roundtrip_preserves_running_session_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "focus.json"
            state = FocusState(
                status=FocusStatus.RUNNING,
                kind=SessionKind.FOCUS,
                started_at=datetime(2026, 11, 3, 9, 0),
                deadline=datetime(2026, 11, 3, 9, 25),
                session_duration_seconds=1500,
                completed_focus_sessions=3,
                history={"2026-11-02": 3000},
            )
            state.save(path)
            loaded = FocusState.load(path)
        self.assertEqual(loaded.schema_version, CURRENT_FOCUS_SCHEMA_VERSION)
        self.assertEqual(loaded.status, FocusStatus.RUNNING)
        self.assertEqual(loaded.deadline, datetime(2026, 11, 3, 9, 25))
        self.assertEqual(loaded.history, {"2026-11-02": 3000})

    def test_corrupt_and_invalid_state_falls_back_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "focus.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(FocusState.load(path).status, FocusStatus.STOPPED)
        state = FocusState.from_dict(
            {"status": "running", "deadline": None, "history": {"bad": "x"}}
        )
        self.assertEqual(state.status, FocusStatus.STOPPED)
        self.assertEqual(state.history, {})

    def test_paused_state_restores_remaining_time(self) -> None:
        state = FocusState.from_dict(
            {
                "schema_version": 1,
                "status": "paused",
                "kind": "focus",
                "paused_remaining_seconds": 42,
                "session_duration_seconds": 60,
            }
        )
        engine = FocusEngine(FocusSettings(focus_seconds=60), state)
        self.assertEqual(engine.remaining_seconds(), 42)

    def test_duration_format(self) -> None:
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "1:01:01")


if __name__ == "__main__":
    unittest.main()
