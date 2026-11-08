"""Linux/X11 implementation of the platform backend."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from .. import APP_SLUG
from ..context import MediaStatus, NetworkState, NetworkStatus
from .base import (
    ActiveWindowProbe,
    BatteryStatus,
    Capability,
    CapabilityInfo,
    PlatformBackend,
    PlatformPaths,
    WindowInfo,
)

log = logging.getLogger(__name__)

XA_ATOM = 4
XA_STRING = 31
XA_WINDOW = 33
XA_CARDINAL = 6

BROWSER_KEYS = (
    "firefox",
    "chrome",
    "chromium",
    "brave",
    "edge",
    "opera",
    "vivaldi",
    "epiphany",
    "zen",
)
TERMINAL_KEYS = (
    "terminal",
    "konsole",
    "kitty",
    "alacritty",
    "xterm",
    "terminator",
    "tilix",
    "wezterm",
    "guake",
    "foot",
)

_X_ERROR_HANDLER_TYPE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("event_mask", ctypes.c_ulong),
    ]


@_X_ERROR_HANDLER_TYPE
def _ignore_x_errors(_display, _event):  # pragma: no cover - X11 callback
    return 0


def _install_error_handler(x11):  # noqa: ANN001
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    x11.XSetErrorHandler.argtypes = [_X_ERROR_HANDLER_TYPE]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return x11.XSetErrorHandler(_ignore_x_errors)


def _restore_error_handler(x11, display, previous) -> None:  # noqa: ANN001
    try:
        x11.XSync(display, 0)
        if previous:
            x11.XSetErrorHandler(ctypes.cast(previous, _X_ERROR_HANDLER_TYPE))
    except Exception:  # noqa: BLE001
        pass


def classify_window(class_name: str) -> str | None:
    lowered = (class_name or "").lower()
    if any(key in lowered for key in BROWSER_KEYS):
        return "browser"
    if any(key in lowered for key in TERMINAL_KEYS):
        return "terminal"
    return None


class X11WindowProbe(ActiveWindowProbe):
    """Reads active-window metadata and geometry through Xlib."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env or os.environ
        self._lib = None
        self._dpy = None
        self._root = 0
        self._atoms: dict[bytes, int] = {}
        session = self._env.get("XDG_SESSION_TYPE", "").lower()
        if session not in ("", "x11") or not self._env.get("DISPLAY"):
            return
        try:
            lib = ctypes.CDLL("libX11.so.6")
            self._configure(lib)
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            display = lib.XOpenDisplay(None)
            if not display:
                return
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            self._lib = lib
            self._dpy = display
            self._root = lib.XDefaultRootWindow(display)
        except Exception:  # noqa: BLE001
            log.debug("X11 probe unavailable", exc_info=True)

    @staticmethod
    def _configure(lib) -> None:  # noqa: ANN001
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.XGetWindowProperty.restype = ctypes.c_int
        lib.XGetGeometry.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XGetGeometry.restype = ctypes.c_int
        lib.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        lib.XTranslateCoordinates.restype = ctypes.c_int
        lib.XFree.argtypes = [ctypes.c_void_p]

    @property
    def available(self) -> bool:
        return self._lib is not None and self._dpy is not None

    def close(self) -> None:
        if self._lib is not None and self._dpy is not None:
            try:
                self._lib.XCloseDisplay(self._dpy)
            except Exception:  # noqa: BLE001
                pass
        self._lib = None
        self._dpy = None

    def _atom(self, name: bytes) -> int:
        if name not in self._atoms:
            self._atoms[name] = int(self._lib.XInternAtom(self._dpy, name, 0))
        return self._atoms[name]

    def _property(
        self, window: int, prop: int, req_type: int, length: int = 1024
    ) -> tuple[int, int, bytes] | None:
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        after = ctypes.c_ulong()
        data = ctypes.c_void_p()
        status = self._lib.XGetWindowProperty(
            self._dpy,
            ctypes.c_ulong(window),
            ctypes.c_ulong(prop),
            0,
            length,
            0,
            ctypes.c_ulong(req_type),
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(nitems),
            ctypes.byref(after),
            ctypes.byref(data),
        )
        if status != 0 or not data or nitems.value == 0:
            if data:
                self._lib.XFree(data)
            return None
        try:
            stride = ctypes.sizeof(ctypes.c_ulong) if actual_format.value == 32 else 1
            raw = ctypes.string_at(data, nitems.value * stride)
        finally:
            self._lib.XFree(data)
        return actual_format.value, int(nitems.value), raw

    def _first_cardinal(self, window: int, atom: int, req_type: int) -> int | None:
        result = self._property(window, atom, req_type, 4)
        if result is None:
            return None
        fmt, nitems, raw = result
        if fmt != 32 or nitems < 1 or len(raw) < ctypes.sizeof(ctypes.c_ulong):
            return None
        value = ctypes.c_ulong.from_buffer_copy(raw[: ctypes.sizeof(ctypes.c_ulong)])
        return int(value.value) & 0xFFFFFFFF

    def _string(self, window: int, atom: int, req_type: int) -> str:
        result = self._property(window, atom, req_type)
        if result is None:
            return ""
        _fmt, _nitems, raw = result
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")

    def _class_name(self, window: int) -> str:
        result = self._property(window, self._atom(b"WM_CLASS"), XA_STRING)
        if result is None:
            return ""
        _fmt, _nitems, raw = result
        parts = [part for part in raw.split(b"\0") if part]
        return parts[-1].decode("utf-8", "replace") if parts else ""

    def _has_atom(self, window: int, list_atom: int, wanted: int) -> bool:
        result = self._property(window, list_atom, XA_ATOM)
        if result is None:
            return False
        fmt, nitems, raw = result
        if fmt != 32:
            return False
        stride = ctypes.sizeof(ctypes.c_ulong)
        for index in range(nitems):
            chunk = raw[index * stride : (index + 1) * stride]
            if len(chunk) < stride:
                break
            if int(ctypes.c_ulong.from_buffer_copy(chunk).value) == wanted:
                return True
        return False

    def _geometry(self, window: int) -> tuple[int, int, int, int] | None:
        root = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        width = ctypes.c_uint()
        height = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        status = self._lib.XGetGeometry(
            self._dpy,
            ctypes.c_ulong(window),
            ctypes.byref(root),
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(width),
            ctypes.byref(height),
            ctypes.byref(border),
            ctypes.byref(depth),
        )
        if not status or width.value == 0 or height.value == 0:
            return None
        dest_x = ctypes.c_int()
        dest_y = ctypes.c_int()
        child = ctypes.c_ulong()
        ok = self._lib.XTranslateCoordinates(
            self._dpy,
            ctypes.c_ulong(window),
            ctypes.c_ulong(self._root),
            0,
            0,
            ctypes.byref(dest_x),
            ctypes.byref(dest_y),
            ctypes.byref(child),
        )
        if not ok:
            return None
        return (dest_x.value, dest_y.value, int(width.value), int(height.value))

    def active_window(self) -> WindowInfo | None:
        if not self.available:
            return None
        window = self._first_cardinal(
            self._root, self._atom(b"_NET_ACTIVE_WINDOW"), XA_WINDOW
        )
        if not window:
            return None
        geometry = self._geometry(window)
        if geometry is None:
            return None
        x, y, width, height = geometry
        return WindowInfo(
            window_id=window,
            class_name=self._class_name(window),
            title=self._string(
                window, self._atom(b"_NET_WM_NAME"), self._atom(b"UTF8_STRING")
            ),
            x=x,
            y=y,
            width=width,
            height=height,
            hidden=self._has_atom(
                window,
                self._atom(b"_NET_WM_STATE"),
                self._atom(b"_NET_WM_STATE_HIDDEN"),
            ),
            fullscreen=self._has_atom(
                window,
                self._atom(b"_NET_WM_STATE"),
                self._atom(b"_NET_WM_STATE_FULLSCREEN"),
            ),
        )


class LinuxBackend(PlatformBackend):
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        config_root: Path | None = None,
        state_root: Path | None = None,
        power_supply_root: Path = Path("/sys/class/power_supply"),
        network_root: Path = Path("/sys/class/net"),
    ) -> None:
        super().__init__()
        self.env = env if env is not None else os.environ
        self._config_root = config_root
        self._state_root = state_root
        self.power_supply_root = power_supply_root
        self.network_root = network_root

    @property
    def name(self) -> str:
        return "linux"

    def paths(self) -> PlatformPaths:
        paths = super().paths()
        config_dir = (
            self._config_root / APP_SLUG
            if self._config_root is not None
            else paths.config_dir
        )
        state_dir = (
            self._state_root / APP_SLUG
            if self._state_root is not None
            else paths.state_dir
        )
        return PlatformPaths(config_dir, state_dir, paths.cache_dir)

    def session_type(self) -> str:
        session = self.env.get("XDG_SESSION_TYPE", "").strip().lower()
        if session:
            return session
        if self.env.get("WAYLAND_DISPLAY"):
            return "wayland"
        if self.env.get("DISPLAY"):
            return "x11"
        return "unknown"

    def session_environment(self) -> Mapping[str, str]:
        return self.env

    def capabilities(self) -> dict[Capability, CapabilityInfo]:
        session = self.session_type()
        x11 = session == "x11" and bool(self.env.get("DISPLAY"))
        active_window = x11 and ctypes.util.find_library("X11") is not None
        idle_time = active_window and ctypes.util.find_library("Xss") is not None
        gdbus = shutil.which("gdbus") is not None
        secret_tool = shutil.which("secret-tool") is not None
        wayland_reason = (
            "The current Wayland session does not expose this window-control "
            "capability; use an X11 session for full support."
        )
        x11_reason = "This feature requires a working Linux/X11 session."
        x11_status = CapabilityInfo(
            x11, "" if x11 else wayland_reason if session == "wayland" else x11_reason
        )
        return {
            Capability.PATHS: CapabilityInfo(True),
            Capability.AUTOSTART: CapabilityInfo(True),
            Capability.BATTERY: CapabilityInfo(
                self.power_supply_root.is_dir(),
                "Linux power-supply information is unavailable."
                if not self.power_supply_root.is_dir()
                else "",
            ),
            Capability.ACTIVE_WINDOW: CapabilityInfo(
                active_window,
                "" if active_window else x11_status.reason or "Xlib is unavailable.",
            ),
            Capability.ALWAYS_ON_TOP: x11_status,
            Capability.WORKSPACE_BEHAVIOR: x11_status,
            Capability.CLICK_THROUGH: x11_status,
            Capability.AUDIO: CapabilityInfo(
                self.audio_available,
                "Qt Multimedia audio support is unavailable."
                if not self.audio_available
                else "",
            ),
            Capability.SESSION_DIAGNOSTICS: CapabilityInfo(True),
            Capability.IDLE_TIME: CapabilityInfo(
                idle_time,
                "Idle time requires the XScreenSaver extension on Linux/X11."
                if not idle_time
                else "",
            ),
            Capability.FULLSCREEN: CapabilityInfo(
                active_window,
                "Fullscreen detection requires active-window access on Linux/X11."
                if not active_window
                else "",
            ),
            Capability.NETWORK: CapabilityInfo(
                self.network_root.is_dir(),
                "Linux network interface state is unavailable."
                if not self.network_root.is_dir()
                else "",
            ),
            Capability.MEDIA_CONTROLS: CapabilityInfo(
                gdbus,
                "Media controls require the gdbus command and an MPRIS player."
                if not gdbus
                else "",
            ),
            Capability.KEYCHAIN: CapabilityInfo(
                secret_tool,
                "Secure credential storage requires Secret Service and secret-tool."
                if not secret_tool
                else "",
            ),
        }

    def launcher_path(self) -> Path:
        return Path.home() / ".local" / "bin" / APP_SLUG

    def launcher_command(self) -> str:
        if getattr(sys, "frozen", False):
            return self._desktop_exec_arg(sys.executable)
        launcher = self.launcher_path()
        if launcher.is_file() and os.access(launcher, os.X_OK):
            return self._desktop_exec_arg(str(launcher))
        app_dir = Path(__file__).resolve().parent.parent.parent
        venv_python = app_dir / ".venv" / "bin" / "python"
        if venv_python.is_file():
            return f"{self._desktop_exec_arg(str(venv_python))} -m desktop_buddy"
        return f"{self._desktop_exec_arg(sys.executable)} -m desktop_buddy"

    @staticmethod
    def _desktop_exec_arg(value: str) -> str:
        for char in ("\\", '"', "`", "$"):
            value = value.replace(char, "\\" + char)
        return '"' + value.replace("%", "%%") + '"'

    def launcher_description(self) -> str:
        found = shutil.which(APP_SLUG)
        if found:
            return found
        launcher = self.launcher_path()
        if launcher.is_file() and os.access(launcher, os.X_OK):
            return f"{launcher} (not on PATH)"
        return "not installed"

    def autostart_path(self, base: Path | None = None) -> Path:
        config_root = base or self.paths().config_dir.parent
        return config_root / "autostart" / f"{APP_SLUG}.desktop"

    def set_autostart(self, enabled: bool, base: Path | None = None) -> Path:
        path = self.autostart_path(base)
        if not enabled:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.0\n"
            "Name=Desktop Buddy\n"
            "GenericName=Desktop pet\n"
            "Comment=A tiny creature that lives on your desktop\n"
            f"Exec={self.launcher_command()}\n"
            f"Icon={self.icon_path()}\n"
            "Terminal=false\n"
            "Categories=Utility;Game;\n"
            "StartupNotify=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-GNOME-Autostart-Delay=3\n"
        )
        path.write_text(content, encoding="utf-8")
        return path

    def battery_status(self) -> BatteryStatus:
        if not self.power_supply_root.is_dir():
            return BatteryStatus(False, "no battery")
        for entry in sorted(self.power_supply_root.glob("BAT*")):
            try:
                status = (entry / "status").read_text(encoding="utf-8").strip()
                capacity = (entry / "capacity").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            return BatteryStatus(
                status.lower() == "discharging",
                f"{capacity}% ({status})",
                int(capacity) if capacity.isdigit() else None,
            )
        return BatteryStatus(False, "unknown")

    def idle_seconds(self) -> float | None:
        if not self.supports(Capability.IDLE_TIME):
            return None
        x11 = None
        display = None
        info = None
        try:
            x11 = ctypes.CDLL("libX11.so.6")
            xss = ctypes.CDLL("libXss.so.1")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
            xss.XScreenSaverQueryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(_XScreenSaverInfo),
            ]
            xss.XScreenSaverQueryInfo.restype = ctypes.c_int
            x11.XFree.argtypes = [ctypes.c_void_p]
            display = x11.XOpenDisplay(None)
            if not display:
                return None
            info = xss.XScreenSaverAllocInfo()
            if not info:
                return None
            root = x11.XDefaultRootWindow(display)
            if not xss.XScreenSaverQueryInfo(display, root, info):
                return None
            return max(0.0, float(info.contents.idle) / 1000.0)
        except Exception:  # noqa: BLE001 - native capability boundary
            log.debug("Could not query X11 idle time", exc_info=True)
            return None
        finally:
            if info is not None and x11 is not None:
                x11.XFree(info)
            if display is not None and x11 is not None:
                x11.XCloseDisplay(display)

    def network_status(self) -> NetworkStatus:
        if not self.network_root.is_dir():
            return NetworkStatus()
        candidates: list[str] = []
        for entry in sorted(self.network_root.iterdir()):
            if entry.name == "lo":
                continue
            try:
                state = (entry / "operstate").read_text(encoding="utf-8").strip()
                carrier_path = entry / "carrier"
                carrier = (
                    carrier_path.read_text(encoding="utf-8").strip()
                    if carrier_path.is_file()
                    else "1"
                )
            except OSError:
                continue
            candidates.append(entry.name)
            if state in {"up", "unknown"} and carrier != "0":
                return NetworkStatus(NetworkState.ONLINE, entry.name)
        return NetworkStatus(
            NetworkState.OFFLINE,
            candidates[0] if candidates else "",
        )

    def _mpris_player(self) -> str | None:
        if not self.supports(Capability.MEDIA_CONTROLS):
            return None
        result = self._run_command(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.ListNames",
            ]
        )
        if result is None:
            return None
        marker = "org.mpris.MediaPlayer2."
        names = [part.strip(" '[](),") for part in result.split(",")]
        return next((name for name in names if name.startswith(marker)), None)

    def media_status(self) -> MediaStatus:
        player = self._mpris_player()
        if not player:
            return MediaStatus()
        result = self._run_command(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                player,
                "--object-path",
                "/org/mpris/MediaPlayer2",
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.mpris.MediaPlayer2.Player",
                "PlaybackStatus",
            ]
        )
        playback = "unknown"
        if result:
            for value in ("Playing", "Paused", "Stopped"):
                if value in result:
                    playback = value.lower()
                    break
        return MediaStatus(True, player, playback)

    def media_control(self, action: str) -> bool:
        methods = {
            "play-pause": "PlayPause",
            "next": "Next",
            "previous": "Previous",
            "stop": "Stop",
        }
        method = methods.get(str(action))
        player = self._mpris_player()
        if not method or not player:
            return False
        return (
            self._run_command(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    player,
                    "--object-path",
                    "/org/mpris/MediaPlayer2",
                    "--method",
                    f"org.mpris.MediaPlayer2.Player.{method}",
                ]
            )
            is not None
        )

    def store_secret(self, key: str, value: str) -> bool:
        if not self.supports(Capability.KEYCHAIN):
            return False
        try:
            result = subprocess.run(
                [
                    "secret-tool",
                    "store",
                    "--label=Desktop Buddy integration",
                    "application",
                    APP_SLUG,
                    "key",
                    str(key),
                ],
                input=str(value),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def read_secret(self, key: str) -> str | None:
        if not self.supports(Capability.KEYCHAIN):
            return None
        return self._run_command(
            ["secret-tool", "lookup", "application", APP_SLUG, "key", str(key)]
        )

    def delete_secret(self, key: str) -> bool:
        if not self.supports(Capability.KEYCHAIN):
            return False
        return (
            self._run_command(
                ["secret-tool", "clear", "application", APP_SLUG, "key", str(key)]
            )
            is not None
        )

    @staticmethod
    def _run_command(command: list[str]) -> str | None:
        try:
            result = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=4,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def create_active_window_probe(self) -> ActiveWindowProbe:
        return X11WindowProbe(self.env)

    def classify_window(self, class_name: str) -> str | None:
        return classify_window(class_name)

    def apply_workspace_behavior(self, native_window_id: int) -> bool:
        if not self.supports(Capability.WORKSPACE_BEHAVIOR) or not native_window_id:
            return False
        try:
            x11 = ctypes.CDLL("libX11.so.6")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XInternAtom.restype = ctypes.c_ulong
            x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            x11.XChangeProperty.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            x11.XFlush.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            display = x11.XOpenDisplay(None)
            if not display:
                return False
            previous = _install_error_handler(x11)
            try:
                atom = x11.XInternAtom(display, b"_NET_WM_DESKTOP", 0)
                if not atom:
                    return False
                value = ctypes.c_ulong(0xFFFFFFFF)
                x11.XChangeProperty(
                    display,
                    ctypes.c_ulong(native_window_id),
                    atom,
                    ctypes.c_ulong(XA_CARDINAL),
                    32,
                    0,
                    ctypes.byref(value),
                    1,
                )
                x11.XFlush(display)
            finally:
                _restore_error_handler(x11, display, previous)
                x11.XCloseDisplay(display)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _libxcb_cursor_available(self) -> bool:
        if ctypes.util.find_library("xcb-cursor"):
            return True
        for entry in self.env.get("LD_LIBRARY_PATH", "").split(":"):
            if entry and any(Path(entry).glob("libxcb-cursor.so.0*")):
                return True
        vendor = Path(__file__).resolve().parent.parent.parent / "vendor" / "syslibs"
        return any(vendor.glob("libxcb-cursor.so.0*"))

    def diagnostics(self) -> dict[str, object]:
        status = self.battery_status()
        probe = self.create_active_window_probe()
        try:
            info = probe.active_window()
            active = (
                f"{info.class_name or '?'} {info.width}x{info.height} "
                f"at ({info.x},{info.y}) kind={self.classify_window(info.class_name)}"
                if info is not None
                else "unavailable"
            )
        finally:
            probe.close()
        autostart = self.autostart_enabled()
        return {
            "backend": self.name,
            "session": self.session_type(),
            "DISPLAY": self.env.get("DISPLAY", "-"),
            "WAYLAND_DISPLAY": self.env.get("WAYLAND_DISPLAY", "-"),
            "libxcb-cursor": "available"
            if self._libxcb_cursor_available()
            else "MISSING",
            "battery": f"{status.label} | on battery: {status.on_battery}",
            "idle seconds": self.idle_seconds(),
            "network": self.network_status().state.value,
            "media": self.media_status().playback,
            "keychain": "available"
            if self.supports(Capability.KEYCHAIN)
            else "unavailable",
            "active window": active,
            "launcher": self.launcher_description(),
            "autostart": "enabled" if autostart else "disabled",
            "autostart file": self.autostart_path() if autostart else "-",
        }
