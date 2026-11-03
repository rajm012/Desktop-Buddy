"""Windows backend contract tests that run without a Windows host."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_buddy.context import NetworkState, NetworkStatus
from desktop_buddy.platforms.base import BatteryStatus, Capability, WindowInfo
from desktop_buddy.platforms.windows import (
    RECT,
    WindowsBackend,
    classify_window,
    rect_covers_monitor,
)


class FakeWindowsApi:
    available = True
    keychain_available = True
    network_available = True

    def __init__(self) -> None:
        self.prepared = False
        self.behavior: tuple[int, bool, bool] | None = None
        self.secrets: dict[str, str] = {}

    def prepare_process(self) -> None:
        self.prepared = True

    def active_window(self) -> WindowInfo:
        return WindowInfo(
            101,
            "Chrome_WidgetWin_1",
            "Desktop Buddy test",
            -1920,
            0,
            1920,
            1080,
            fullscreen=True,
        )

    def battery_status(self) -> BatteryStatus:
        return BatteryStatus(True, "37% (Battery)", 37)

    def idle_seconds(self) -> float:
        return 12.5

    def network_status(self) -> NetworkStatus:
        return NetworkStatus(NetworkState.ONLINE, "windows")

    def apply_window_behavior(
        self, window_id: int, *, always_on_top: bool, click_through: bool
    ) -> bool:
        self.behavior = (window_id, always_on_top, click_through)
        return True

    def store_secret(self, key: str, value: str) -> bool:
        self.secrets[key] = value
        return True

    def read_secret(self, key: str) -> str | None:
        return self.secrets.get(key)

    def delete_secret(self, key: str) -> bool:
        return self.secrets.pop(key, None) is not None


class WindowsBackendTests(unittest.TestCase):
    def test_native_capabilities_and_probe_are_exposed(self) -> None:
        api = FakeWindowsApi()
        backend = WindowsBackend(api=api)
        for capability in (
            Capability.AUTOSTART,
            Capability.BATTERY,
            Capability.ACTIVE_WINDOW,
            Capability.ALWAYS_ON_TOP,
            Capability.CLICK_THROUGH,
            Capability.IDLE_TIME,
            Capability.FULLSCREEN,
            Capability.NETWORK,
            Capability.KEYCHAIN,
        ):
            with self.subTest(capability=capability):
                self.assertTrue(backend.supports(capability))
        self.assertFalse(backend.supports(Capability.WORKSPACE_BEHAVIOR))
        probe = backend.create_active_window_probe()
        self.assertTrue(probe.available)
        self.assertTrue(probe.active_window().fullscreen)
        self.assertEqual(backend.battery_status().percent, 37)
        self.assertEqual(backend.idle_seconds(), 12.5)
        self.assertEqual(backend.network_status().state, NetworkState.ONLINE)

    def test_process_window_and_credential_calls_delegate_to_native_api(self) -> None:
        api = FakeWindowsApi()
        backend = WindowsBackend(api=api)
        backend.prepare_process()
        self.assertTrue(api.prepared)
        self.assertTrue(
            backend.apply_window_behavior(55, always_on_top=False, click_through=True)
        )
        self.assertEqual(api.behavior, (55, False, True))
        self.assertTrue(backend.store_secret("calendar", "token"))
        self.assertEqual(backend.read_secret("calendar"), "token")
        self.assertTrue(backend.delete_secret("calendar"))

    def test_startup_folder_autostart_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = WindowsBackend(startup_root=root, api=FakeWindowsApi())
            path = backend.set_autostart(True)
            self.assertEqual(path, root / "Desktop Buddy.vbs")
            text = path.read_text(encoding="utf-8")
            self.assertIn("WScript.Shell", text)
            self.assertIn("desktop_buddy", text)
            self.assertTrue(backend.autostart_enabled())
            backend.set_autostart(False)
            self.assertFalse(backend.autostart_enabled())

    def test_fullscreen_geometry_supports_secondary_monitor_origins(self) -> None:
        monitor = RECT(-1920, 0, 0, 1080)
        self.assertTrue(rect_covers_monitor(RECT(-1920, 0, 0, 1080), monitor))
        self.assertTrue(rect_covers_monitor(RECT(-1921, -1, 1, 1081), monitor))
        self.assertFalse(rect_covers_monitor(RECT(-1800, 20, -20, 1000), monitor))

    def test_windows_window_classification(self) -> None:
        self.assertEqual(classify_window("Chrome_WidgetWin_1"), "browser")
        self.assertEqual(classify_window("CASCADIA_HOSTING_WINDOW_CLASS"), "terminal")
        self.assertIsNone(classify_window("CabinetWClass"))

    def test_backend_selection_uses_windows_backend(self) -> None:
        import desktop_buddy.platforms as platforms

        with patch.object(platforms.sys, "platform", "win32"):
            platforms.set_backend_for_tests(None)
            try:
                self.assertEqual(platforms.get_backend().name, "windows")
            finally:
                platforms.set_backend_for_tests(None)


if __name__ == "__main__":
    unittest.main()
