"""Unit tests for platform capability and Linux backend isolation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from desktop_buddy.context import NetworkState
from desktop_buddy.platforms.base import Capability
from desktop_buddy.platforms.linux import LinuxBackend, classify_window


class LinuxBackendTests(unittest.TestCase):
    def test_backend_paths_use_injected_standard_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = LinuxBackend(
                env={"XDG_SESSION_TYPE": "x11", "DISPLAY": ":1"},
                config_root=root / "config",
                state_root=root / "state",
                power_supply_root=root / "power",
            )
            paths = backend.paths()
            self.assertEqual(paths.config_dir, root / "config" / "desktop-buddy")
            self.assertEqual(paths.state_dir, root / "state" / "desktop-buddy")
            self.assertEqual(paths.config_file.name, "config.json")
            self.assertEqual(paths.log_file.name, "desktop-buddy.log")

    def test_autostart_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            backend = LinuxBackend(config_root=base)
            self.assertFalse(backend.autostart_enabled(base))
            path = backend.set_autostart(True, base)
            self.assertTrue(backend.autostart_enabled(base))
            self.assertIn("[Desktop Entry]", path.read_text(encoding="utf-8"))
            backend.set_autostart(False, base)
            self.assertFalse(backend.autostart_enabled(base))

    def test_battery_status_reads_linux_power_supply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            power = Path(tmp)
            battery = power / "BAT0"
            battery.mkdir()
            (battery / "status").write_text("Discharging\n", encoding="utf-8")
            (battery / "capacity").write_text("73\n", encoding="utf-8")
            status = LinuxBackend(power_supply_root=power).battery_status()
            self.assertTrue(status.on_battery)
            self.assertEqual(status.label, "73% (Discharging)")
            self.assertEqual(status.percent, 73)

    def test_network_status_reads_linux_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            network = Path(tmp)
            interface = network / "wlan0"
            interface.mkdir()
            (interface / "operstate").write_text("up\n", encoding="utf-8")
            (interface / "carrier").write_text("1\n", encoding="utf-8")
            status = LinuxBackend(network_root=network).network_status()
            self.assertEqual(status.state, NetworkState.ONLINE)
            self.assertEqual(status.interface, "wlan0")

    def test_wayland_exposes_unavailable_window_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = LinuxBackend(
                env={"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
                power_supply_root=Path(tmp),
            )
            for capability in (
                Capability.ACTIVE_WINDOW,
                Capability.ALWAYS_ON_TOP,
                Capability.WORKSPACE_BEHAVIOR,
                Capability.CLICK_THROUGH,
            ):
                with self.subTest(capability=capability):
                    info = backend.capability(capability)
                    self.assertFalse(info.available)
                    self.assertIn("Wayland", info.reason)

    def test_x11_keeps_linux_desktop_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = LinuxBackend(
                env={"XDG_SESSION_TYPE": "x11", "DISPLAY": ":1"},
                power_supply_root=Path(tmp),
            )
            for capability in (
                Capability.ALWAYS_ON_TOP,
                Capability.WORKSPACE_BEHAVIOR,
                Capability.CLICK_THROUGH,
                Capability.AUTOSTART,
            ):
                with self.subTest(capability=capability):
                    self.assertTrue(backend.supports(capability))
            active_window = backend.capability(Capability.ACTIVE_WINDOW)
            if active_window.available:
                self.assertTrue(backend.supports(Capability.ACTIVE_WINDOW))
            else:
                self.assertEqual(active_window.reason, "Xlib is unavailable.")
            audio = backend.capability(Capability.AUDIO)
            self.assertEqual(audio.available, backend.audio_available)
            if not audio.available:
                self.assertEqual(
                    audio.reason, "Qt Multimedia audio support is unavailable."
                )

    def test_server_name_is_scoped_to_user_session_without_uid(self) -> None:
        first = LinuxBackend(env={"XDG_SESSION_ID": "session-a"}).server_name()
        second = LinuxBackend(env={"XDG_SESSION_ID": "session-b"}).server_name()
        self.assertTrue(first.startswith("desktop-buddy-"))
        self.assertNotEqual(first, second)

    def test_window_classification(self) -> None:
        self.assertEqual(classify_window("google-chrome.Google-chrome"), "browser")
        self.assertEqual(classify_window("org.gnome.Terminal"), "terminal")
        self.assertIsNone(classify_window("org.gnome.Nautilus"))

    def test_non_platform_modules_contain_no_native_linux_calls(self) -> None:
        root = Path(__file__).resolve().parent.parent / "desktop_buddy"
        for name in (
            "app.py",
            "config.py",
            "platform_utils.py",
            "sound.py",
            "window.py",
        ):
            text = (root / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotIn("ctypes", text)
                self.assertNotIn("libX11", text)
                self.assertNotIn("/sys/", text)
                self.assertNotIn("platforms.linux", text)


if __name__ == "__main__":
    unittest.main()
