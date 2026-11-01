"""CLI parser and single-instance local IPC tests."""

from __future__ import annotations

import os
import time
import unittest
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtNetwork import QLocalSocket  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.app import LocalCommandServer, build_parser  # noqa: E402


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
