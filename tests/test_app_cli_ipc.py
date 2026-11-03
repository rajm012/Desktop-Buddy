"""CLI parser and single-instance local IPC tests."""

from __future__ import annotations

import os
import time
import unittest
import uuid
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtNetwork import QLocalSocket  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.actions import ActionDefinition, ActionRegistry, ActionType  # noqa: E402
from desktop_buddy.app import Controller, LocalCommandServer, build_parser  # noqa: E402
from desktop_buddy.config import Config  # noqa: E402
from desktop_buddy.focus import (  # noqa: E402
    FocusEngine,
    FocusSettings,
    FocusStatus,
    SessionKind,
)
from desktop_buddy.platforms.base import (  # noqa: E402
    ActiveWindowProbe,
    Capability,
    WindowInfo,
)
from desktop_buddy.wellness import HistoryStatus, WellnessEngine  # noqa: E402


class _ToggleBackend:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def supports(self, capability: Capability) -> bool:
        return capability is Capability.AUTOSTART

    def autostart_enabled(self) -> bool:
        return self.enabled

    def set_autostart(self, enabled: bool) -> None:
        self.enabled = enabled


class _RefreshTarget:
    def apply_config(self) -> None:
        return None

    def refresh(self) -> None:
        return None


class _ControllerHarness:
    def __init__(self, autostart: bool) -> None:
        self.config = Config(autostart=autostart)
        self.backend = _ToggleBackend(autostart)
        self.window = _RefreshTarget()
        self.tray = _RefreshTarget()

    def _rebuild_wellness(self) -> None:
        return None

    def _rebuild_focus(self) -> None:
        return None

    def _schedule_save(self) -> None:
        return None


class _FocusWindow:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def focus_started(self, _kind, message: str) -> None:  # noqa: ANN001
        self.messages.append(message)

    def say(self, message: str, _seconds: float) -> None:
        self.messages.append(message)


class _FocusControllerHarness:
    focus_start = Controller.focus_start
    focus_pause = Controller.focus_pause
    focus_resume = Controller.focus_resume
    focus_skip = Controller.focus_skip
    focus_stop = Controller.focus_stop
    focus_summary = Controller.focus_summary
    handle_command = Controller.handle_command

    def __init__(self) -> None:
        self.config = Config()
        self._focus = FocusEngine(FocusSettings(focus_seconds=60))
        self.window = _FocusWindow()

    def _save_focus(self) -> None:
        return None

    def _sync_focus_ui(self) -> None:
        return None


class _ReminderWindow:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def say(self, message: str, _seconds: float) -> None:
        self.messages.append(message)


class _ReminderControllerHarness:
    handle_command = Controller.handle_command
    _check_reminders = Controller._check_reminders
    _toast_done = Controller._toast_done
    _toast_dismiss = Controller._toast_dismiss
    reminders_summary = Controller.reminders_summary
    reminder_history_summary = Controller.reminder_history_summary
    add_reminder = Controller.add_reminder
    save_reminder_definition = Controller.save_reminder_definition
    remove_reminder = Controller.remove_reminder
    mark_reminder_done = Controller.mark_reminder_done
    snooze_reminder = Controller.snooze_reminder
    actions_summary = Controller.actions_summary
    run_action = Controller.run_action
    _unique_config_id = staticmethod(Controller._unique_config_id)

    def __init__(self) -> None:
        scheduled = datetime.now() - timedelta(minutes=1)
        self.config = Config(
            active_start="00:00",
            active_end="23:59",
            reminders=[
                {
                    "id": "test",
                    "title": "Test",
                    "kind": "custom",
                    "icon": "⏰",
                    "message": "Test reminder",
                    "recurrence": "one_time",
                    "one_time_at": scheduled.isoformat(),
                    "enabled": True,
                    "urgent": False,
                    "snooze_minutes": 10,
                }
            ],
        )
        self._wellness = WellnessEngine(self.config)
        self._actions = ActionRegistry()
        self.window = _ReminderWindow()
        self.tray = _RefreshTarget()
        self.fired = []

    def _fire_reminder(self, reminder) -> None:  # noqa: ANN001
        self.fired.append(reminder)

    def _save_wellness(self) -> None:
        self._wellness.dirty = False

    def _rebuild_wellness(self) -> None:
        self._wellness = WellnessEngine(self.config, self._wellness.state)

    def _schedule_save(self) -> None:
        return None


class _FullscreenProbe(ActiveWindowProbe):
    @property
    def available(self) -> bool:
        return True

    def active_window(self) -> WindowInfo:
        return WindowInfo(1, "app", "App", 0, 0, 1920, 1080, fullscreen=True)


class _FullscreenBackend:
    def supports(self, capability: Capability) -> bool:
        return capability is Capability.ACTIVE_WINDOW

    def create_active_window_probe(self) -> ActiveWindowProbe:
        return _FullscreenProbe()


class CliParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_control_commands_parse(self) -> None:
        for command in (
            "quit",
            "show",
            "hide",
            "toggle",
            "pause",
            "resume",
            "dance",
            "status",
            "settings",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.parser.parse_args([command]).command, command)

    def test_commands_with_values_parse(self) -> None:
        cases = (
            (["character", "robot"], ("character", "robot")),
            (["remind", "water"], ("remind", "water")),
            (["reminders", "status"], ("reminders", "status")),
            (["click-through", "on"], ("click-through", "on")),
            (["autostart", "off"], ("autostart", "off")),
            (["focus", "start", "long-break"], ("focus", "start")),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = self.parser.parse_args(argv)
                value = getattr(args, "value", getattr(args, "action", None))
                self.assertEqual((args.command, value), expected)

    def test_focus_commands_parse(self) -> None:
        args = self.parser.parse_args(["focus", "start", "short-break"])
        self.assertEqual(args.command, "focus")
        self.assertEqual(args.action, "start")
        self.assertEqual(args.kind, "short-break")

    def test_phase_four_commands_parse(self) -> None:
        reminder = self.parser.parse_args(
            ["reminders", "add", "Stand up", "weekdays at 9"]
        )
        self.assertEqual(reminder.value, "add")
        self.assertEqual(reminder.title, "Stand up")
        self.assertEqual(reminder.schedule, "weekdays at 9")
        action = self.parser.parse_args(["actions", "run", "dance"])
        self.assertEqual((action.action, action.action_id), ("run", "dance"))

    def test_global_flags_parse(self) -> None:
        args = self.parser.parse_args(["--diagnose", "--reset-config", "-v"])
        self.assertTrue(args.diagnose)
        self.assertTrue(args.reset_config)
        self.assertTrue(args.verbose)


class ConfigTransactionTests(unittest.TestCase):
    def test_snapshot_restores_external_autostart_state(self) -> None:
        harness = _ControllerHarness(autostart=True)
        snapshot = harness.config.to_dict()
        harness.config.autostart = False
        harness.backend.set_autostart(False)
        Controller.apply_snapshot(harness, snapshot)
        self.assertTrue(harness.config.autostart)
        self.assertTrue(harness.backend.autostart_enabled())

    def test_reset_disables_external_autostart_state(self) -> None:
        harness = _ControllerHarness(autostart=True)
        Controller.reset_config(harness)
        self.assertFalse(harness.config.autostart)
        self.assertFalse(harness.backend.autostart_enabled())


class FocusControllerTests(unittest.TestCase):
    def test_focus_actions_are_available_through_ipc_dispatch(self) -> None:
        harness = _FocusControllerHarness()
        self.assertEqual(harness.handle_command("focus start"), "focus started")
        self.assertEqual(harness._focus.state.status, FocusStatus.RUNNING)
        self.assertEqual(harness.handle_command("focus pause"), "focus paused")
        self.assertEqual(harness._focus.state.status, FocusStatus.PAUSED)
        self.assertEqual(harness.handle_command("focus resume"), "focus resumed")
        self.assertEqual(harness.handle_command("focus skip"), "focus skipped")
        self.assertEqual(harness._focus.state.kind, SessionKind.SHORT_BREAK)
        self.assertIn("Today:", harness.handle_command("focus status"))

    def test_focus_start_accepts_explicit_break_kind(self) -> None:
        harness = _FocusControllerHarness()
        reply = harness.handle_command("focus start long-break")
        self.assertEqual(reply, "focus started")
        self.assertEqual(harness._focus.state.kind, SessionKind.LONG_BREAK)

    def test_attention_is_suppressed_for_dnd_quiet_hours_and_fullscreen(self) -> None:
        class Wellness:
            allowed = True

            def active_hours_ok(self, _now: datetime) -> bool:
                return self.allowed

        harness = _FocusControllerHarness()
        harness._wellness = Wellness()
        harness.backend = _FullscreenBackend()
        harness.config.focus_suppress_fullscreen = True
        harness.config.focus_respect_quiet_hours = False
        self.assertFalse(
            Controller._focus_attention_allowed(harness, datetime(2026, 11, 3, 12, 0))
        )
        harness.config.do_not_disturb = False
        harness.config.focus_respect_quiet_hours = True
        harness._wellness.allowed = False
        self.assertFalse(
            Controller._focus_attention_allowed(harness, datetime(2026, 11, 3, 23, 30))
        )
        harness.config.focus_suppress_fullscreen = False
        harness.config.do_not_disturb = True
        self.assertFalse(
            Controller._focus_attention_allowed(harness, datetime(2026, 11, 3, 12, 0))
        )


class ReminderControllerTests(unittest.TestCase):
    def test_due_reminder_is_not_marked_done_before_user_response(self) -> None:
        harness = _ReminderControllerHarness()
        harness._check_reminders()
        self.assertEqual([item.id for item in harness.fired], ["test"])
        self.assertIn("test", harness._wellness.state.last_triggered)
        self.assertEqual(harness._wellness.recent_history(), [])

        harness._toast_done(harness.fired[0])
        self.assertEqual(
            harness._wellness.recent_history()[0].status, HistoryStatus.DONE
        )

    def test_dismiss_records_missed_status(self) -> None:
        harness = _ReminderControllerHarness()
        harness._check_reminders()
        harness._toast_dismiss(harness.fired[0])
        self.assertEqual(
            harness._wellness.recent_history()[0].status, HistoryStatus.MISSED
        )

    def test_reminders_are_managed_through_quoted_ipc_commands(self) -> None:
        harness = _ReminderControllerHarness()
        reply = harness.handle_command('reminders add "Stand up" "weekdays at 9"')
        self.assertEqual(reply, "reminder added: stand-up")
        self.assertIn("Stand up", harness.handle_command("reminders list"))
        self.assertEqual(
            harness.handle_command("reminders snooze stand-up 15"),
            "reminder snoozed: stand-up",
        )
        self.assertEqual(
            harness.handle_command("reminders remove stand-up"),
            "reminder removed: stand-up",
        )

    def test_ipc_never_runs_an_unapproved_command(self) -> None:
        harness = _ReminderControllerHarness()
        calls: list[list[str]] = []
        action = ActionDefinition(
            "unsafe", "Unsafe", ActionType.COMMAND, "printf unsafe", approved=False
        )
        harness._actions = ActionRegistry(
            [action], run_command=lambda parts: calls.append(parts) or True
        )
        reply = harness.handle_command("actions run unsafe")
        self.assertIn("not approved", reply)
        self.assertEqual(calls, [])


class LocalIpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _wait_until(self, predicate, timeout: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        self.app.processEvents()
        return bool(predicate())

    def test_command_roundtrip_over_local_socket(self) -> None:
        seen: list[str] = []

        def handle(command: str) -> str | None:
            seen.append(command)
            return f"reply:{command}"

        name = f"desktop-buddy-test-{uuid.uuid4().hex}"
        server = LocalCommandServer(name, handle)
        client = QLocalSocket()
        try:
            if not server.listening and server.server.errorString().endswith("error 1"):
                self.skipTest("sandbox does not permit Unix-domain socket binding")
            self.assertTrue(server.listening)
            client.connectToServer(name)
            self.assertTrue(
                self._wait_until(
                    lambda: (
                        client.state() == QLocalSocket.LocalSocketState.ConnectedState
                    )
                )
            )
            client.write(b"status\n")
            client.flush()
            self.assertTrue(self._wait_until(lambda: client.bytesAvailable() > 0))
            self.assertEqual(bytes(client.readAll()), b"reply:status\n")
            self.assertEqual(seen, ["status"])
        finally:
            client.disconnectFromServer()
            self._wait_until(
                lambda: client.state() == QLocalSocket.LocalSocketState.UnconnectedState
            )
            server.close()


if __name__ == "__main__":
    unittest.main()
