"""CLI parser and single-instance local IPC tests."""

from __future__ import annotations

import os
import time
import unittest
import uuid
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtNetwork import QLocalSocket  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

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
