"""CLI parser and single-instance local IPC tests."""

from __future__ import annotations

import os
import time
import unittest
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtNetwork import QLocalSocket  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.app import Controller, LocalCommandServer, build_parser  # noqa: E402
from desktop_buddy.config import Config  # noqa: E402
from desktop_buddy.platforms.base import Capability  # noqa: E402


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

    def _schedule_save(self) -> None:
        return None


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
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = self.parser.parse_args(argv)
                self.assertEqual((args.command, args.value), expected)

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
