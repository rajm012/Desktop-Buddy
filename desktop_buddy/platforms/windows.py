"""Native Windows backend using Win32 APIs behind the platform contract."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Mapping, Protocol

from .. import APP_SLUG
from ..context import NetworkState, NetworkStatus
from .base import (
    ActiveWindowProbe,
    BatteryStatus,
    Capability,
    CapabilityInfo,
    PlatformBackend,
    WindowInfo,
)

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2

BROWSER_KEYS = (
    "chrome",
    "chromium",
    "firefox",
    "msedge",
    "brave",
    "opera",
    "vivaldi",
)
TERMINAL_KEYS = (
    "windowsterminal",
    "cascadia",
    "powershell",
    "cmd",
    "wezterm",
    "alacritty",
    "conhost",
)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def rect_covers_monitor(rect: RECT, bounds: RECT, tolerance: int = 2) -> bool:
    """Return whether a window covers its monitor, including negative origins."""
    return (
        rect.left <= bounds.left + tolerance
        and rect.top <= bounds.top + tolerance
        and rect.right >= bounds.right - tolerance
        and rect.bottom >= bounds.bottom - tolerance
    )


class WindowsApi(Protocol):
    available: bool
    keychain_available: bool
    network_available: bool

    def prepare_process(self) -> None: ...

    def active_window(self) -> WindowInfo | None: ...

    def battery_status(self) -> BatteryStatus: ...

    def idle_seconds(self) -> float | None: ...

    def network_status(self) -> NetworkStatus: ...

    def apply_window_behavior(
        self, window_id: int, *, always_on_top: bool, click_through: bool
    ) -> bool: ...

    def store_secret(self, key: str, value: str) -> bool: ...

    def read_secret(self, key: str) -> str | None: ...

    def delete_secret(self, key: str) -> bool: ...


class NativeWindowsApi:
    """Small ctypes wrapper that is instantiated only on Windows."""

    def __init__(self) -> None:
        self.available = False
        self.keychain_available = False
        self.network_available = False
        if os.name != "nt":
            return
        try:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
            self.wininet = ctypes.WinDLL("wininet", use_last_error=True)
            self._configure()
            self.available = True
            self.keychain_available = True
            self.network_available = True
        except (AttributeError, OSError):
            log.exception("Could not initialize Win32 APIs")

    def _configure(self) -> None:
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsIconic.restype = wintypes.BOOL
        self.user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user32.MonitorFromWindow.restype = wintypes.HANDLE
        self.user32.GetMonitorInfoW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(MONITORINFO),
        ]
        self.user32.GetMonitorInfoW.restype = wintypes.BOOL
        self.user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        self.user32.GetLastInputInfo.restype = wintypes.BOOL
        self.user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self.kernel32.GetSystemPowerStatus.argtypes = [
            ctypes.POINTER(SYSTEM_POWER_STATUS)
        ]
        self.kernel32.GetSystemPowerStatus.restype = wintypes.BOOL
        self.advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(CREDENTIALW),
            wintypes.DWORD,
        ]
        self.advapi32.CredWriteW.restype = wintypes.BOOL
        self.advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
        ]
        self.advapi32.CredReadW.restype = wintypes.BOOL
        self.advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.advapi32.CredDeleteW.restype = wintypes.BOOL
        self.advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self.wininet.InternetGetConnectedState.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        ]
        self.wininet.InternetGetConnectedState.restype = wintypes.BOOL

    def prepare_process(self) -> None:
        setter = getattr(self.user32, "SetProcessDpiAwarenessContext", None)
        if setter is None:
            return
        try:
            setter(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        except (OSError, ValueError):
            log.debug("Per-monitor DPI awareness was already configured", exc_info=True)

    def active_window(self) -> WindowInfo | None:
        if not self.available:
            return None
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        title_length = max(1, self.user32.GetWindowTextLengthW(hwnd) + 1)
        title_buffer = ctypes.create_unicode_buffer(title_length)
        self.user32.GetWindowTextW(hwnd, title_buffer, title_length)
        class_buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        fullscreen = False
        monitor = self.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if monitor:
            monitor_info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
            if self.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                bounds = monitor_info.rcMonitor
                fullscreen = rect_covers_monitor(rect, bounds)
        return WindowInfo(
            window_id=int(hwnd),
            class_name=class_buffer.value,
            title=title_buffer.value,
            x=int(rect.left),
            y=int(rect.top),
            width=max(0, int(rect.right - rect.left)),
            height=max(0, int(rect.bottom - rect.top)),
            hidden=not bool(self.user32.IsWindowVisible(hwnd))
            or bool(self.user32.IsIconic(hwnd)),
            fullscreen=fullscreen,
        )

    def battery_status(self) -> BatteryStatus:
        status = SYSTEM_POWER_STATUS()
        if not self.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return BatteryStatus(False, "unknown")
        percent = (
            None if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
        )
        on_battery = status.ACLineStatus == 0
        label = "AC power" if status.ACLineStatus == 1 else "Battery"
        if percent is not None:
            label = f"{percent}% ({label})"
        return BatteryStatus(on_battery, label, percent)

    def idle_seconds(self) -> float | None:
        info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = int(self.kernel32.GetTickCount64())
        return max(0.0, float(now - int(info.dwTime)) / 1000.0)

    def network_status(self) -> NetworkStatus:
        flags = wintypes.DWORD()
        online = bool(self.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))
        return NetworkStatus(
            NetworkState.ONLINE if online else NetworkState.OFFLINE,
            "windows",
        )

    def apply_window_behavior(
        self, window_id: int, *, always_on_top: bool, click_through: bool
    ) -> bool:
        if not self.available or not window_id:
            return False
        hwnd = wintypes.HWND(window_id)
        getter = getattr(self.user32, "GetWindowLongPtrW", self.user32.GetWindowLongW)
        setter = getattr(self.user32, "SetWindowLongPtrW", self.user32.SetWindowLongW)
        getter.argtypes = [wintypes.HWND, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        style = int(getter(hwnd, GWL_EXSTYLE))
        wanted = WS_EX_LAYERED | WS_EX_NOACTIVATE
        if click_through:
            wanted |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        setter(hwnd, GWL_EXSTYLE, style | wanted)
        insert_after = wintypes.HWND(-1 if always_on_top else -2)
        return bool(
            self.user32.SetWindowPos(
                hwnd,
                insert_after,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        )

    @staticmethod
    def _credential_target(key: str) -> str:
        return f"{APP_SLUG}/{str(key)[:200]}"

    def store_secret(self, key: str, value: str) -> bool:
        raw = str(value).encode("utf-16-le")
        blob = (wintypes.BYTE * len(raw)).from_buffer_copy(raw)
        credential = CREDENTIALW(
            Type=CRED_TYPE_GENERIC,
            TargetName=self._credential_target(key),
            CredentialBlobSize=len(raw),
            CredentialBlob=ctypes.cast(blob, ctypes.POINTER(wintypes.BYTE)),
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            UserName=APP_SLUG,
        )
        return bool(self.advapi32.CredWriteW(ctypes.byref(credential), 0))

    def read_secret(self, key: str) -> str | None:
        pointer = ctypes.POINTER(CREDENTIALW)()
        if not self.advapi32.CredReadW(
            self._credential_target(key), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            return None
        try:
            credential = pointer.contents
            raw = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return raw.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(pointer)

    def delete_secret(self, key: str) -> bool:
        return bool(
            self.advapi32.CredDeleteW(
                self._credential_target(key), CRED_TYPE_GENERIC, 0
            )
        )


class WindowsActiveWindowProbe(ActiveWindowProbe):
    def __init__(self, api: WindowsApi) -> None:
        self.api = api

    @property
    def available(self) -> bool:
        return self.api.available

    def active_window(self) -> WindowInfo | None:
        return self.api.active_window()


def classify_window(class_name: str) -> str | None:
    lowered = (class_name or "").lower()
    if any(key in lowered for key in BROWSER_KEYS):
        return "browser"
    if any(key in lowered for key in TERMINAL_KEYS):
        return "terminal"
    return None


class WindowsBackend(PlatformBackend):
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        startup_root: Path | None = None,
        api: WindowsApi | None = None,
    ) -> None:
        super().__init__()
        self.env = env if env is not None else os.environ
        self._startup_root = startup_root
        self.api = api or NativeWindowsApi()

    @property
    def name(self) -> str:
        return "windows"

    @property
    def adapt_exclusive_fullscreen(self) -> bool:
        return True

    def prepare_process(self) -> None:
        if self.api.available:
            self.api.prepare_process()

    def session_type(self) -> str:
        return "windows"

    def session_environment(self) -> Mapping[str, str]:
        return self.env

    def capabilities(self) -> dict[Capability, CapabilityInfo]:
        native_reason = "Native Win32 APIs are unavailable."
        native = CapabilityInfo(
            self.api.available, "" if self.api.available else native_reason
        )
        return {
            Capability.PATHS: CapabilityInfo(True),
            Capability.AUTOSTART: CapabilityInfo(True),
            Capability.BATTERY: native,
            Capability.ACTIVE_WINDOW: native,
            Capability.ALWAYS_ON_TOP: native,
            Capability.WORKSPACE_BEHAVIOR: CapabilityInfo(
                False,
                "Windows virtual desktops do not expose a supported all-workspaces API.",
            ),
            Capability.CLICK_THROUGH: native,
            Capability.AUDIO: CapabilityInfo(
                self.audio_available,
                "Qt Multimedia audio support is unavailable."
                if not self.audio_available
                else "",
            ),
            Capability.SESSION_DIAGNOSTICS: CapabilityInfo(True),
            Capability.IDLE_TIME: native,
            Capability.FULLSCREEN: native,
            Capability.NETWORK: CapabilityInfo(
                self.api.network_available,
                "Windows network state API is unavailable."
                if not self.api.network_available
                else "",
            ),
            Capability.MEDIA_CONTROLS: CapabilityInfo(
                False,
                "Windows media controls require a future System Media Transport Controls adapter.",
            ),
            Capability.KEYCHAIN: CapabilityInfo(
                self.api.keychain_available,
                "Windows Credential Manager is unavailable."
                if not self.api.keychain_available
                else "",
            ),
        }

    def autostart_path(self, base: Path | None = None) -> Path:
        if base is not None:
            root = base
        elif self._startup_root is not None:
            root = self._startup_root
        else:
            appdata = Path(self.env.get("APPDATA", str(Path.home())))
            root = appdata / "Microsoft/Windows/Start Menu/Programs/Startup"
        return root / "Desktop Buddy.vbs"

    def launcher_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        executable = Path(sys.executable)
        pythonw = executable.with_name("pythonw.exe")
        return [
            str(pythonw if pythonw.is_file() else executable),
            "-m",
            "desktop_buddy",
        ]

    def set_autostart(self, enabled: bool, base: Path | None = None) -> Path:
        path = self.autostart_path(base)
        if not enabled:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        command = subprocess.list2cmdline(self.launcher_command()).replace('"', '""')
        content = (
            'Set shell = CreateObject("WScript.Shell")\n'
            f'shell.Run "{command}", 0, False\n'
        )
        path.write_text(content, encoding="utf-8")
        return path

    def battery_status(self) -> BatteryStatus:
        return self.api.battery_status() if self.api.available else BatteryStatus()

    def create_active_window_probe(self) -> ActiveWindowProbe:
        return WindowsActiveWindowProbe(self.api)

    def classify_window(self, class_name: str) -> str | None:
        return classify_window(class_name)

    def idle_seconds(self) -> float | None:
        return self.api.idle_seconds() if self.api.available else None

    def network_status(self) -> NetworkStatus:
        return (
            self.api.network_status() if self.api.network_available else NetworkStatus()
        )

    def apply_window_behavior(
        self, native_window_id: int, *, always_on_top: bool, click_through: bool
    ) -> bool:
        return self.api.apply_window_behavior(
            native_window_id,
            always_on_top=always_on_top,
            click_through=click_through,
        )

    def store_secret(self, key: str, value: str) -> bool:
        return (
            self.api.store_secret(key, value) if self.api.keychain_available else False
        )

    def read_secret(self, key: str) -> str | None:
        return self.api.read_secret(key) if self.api.keychain_available else None

    def delete_secret(self, key: str) -> bool:
        return self.api.delete_secret(key) if self.api.keychain_available else False

    def diagnostics(self) -> dict[str, object]:
        info = self.api.active_window() if self.api.available else None
        battery = self.battery_status()
        return {
            "backend": self.name,
            "session": self.session_type(),
            "windows version": sys.getwindowsversion()
            if hasattr(sys, "getwindowsversion")
            else "unavailable",
            "battery": f"{battery.label} | on battery: {battery.on_battery}",
            "idle seconds": self.idle_seconds(),
            "network": self.network_status().state.value,
            "active window": (
                f"{info.class_name} {info.width}x{info.height} fullscreen={info.fullscreen}"
                if info
                else "unavailable"
            ),
            "autostart": "enabled" if self.autostart_enabled() else "disabled",
            "autostart file": self.autostart_path(),
            "credential manager": "available"
            if self.api.keychain_available
            else "unavailable",
        }
