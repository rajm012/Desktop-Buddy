"""Operating-system integration helpers (no Qt imports)."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

from . import APP_SLUG

_X_ERROR_HANDLER_TYPE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


@_X_ERROR_HANDLER_TYPE
def _ignore_x_errors(_display, _event):  # pragma: no cover - X11 callback
    """Swallow X11 errors so a stale window id can never kill the app."""
    return 0


def _install_error_handler(x11):
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    x11.XSetErrorHandler.argtypes = [_X_ERROR_HANDLER_TYPE]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    previous = x11.XSetErrorHandler(_ignore_x_errors)
    return previous


def _restore_error_handler(x11, display, previous) -> None:
    try:
        x11.XSync(display, 0)
        if previous:
            x11.XSetErrorHandler(ctypes.cast(previous, _X_ERROR_HANDLER_TYPE))
    except Exception:  # noqa: BLE001
        pass


def config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value) if value else Path.home() / ".config"


def autostart_file(base: Path | None = None) -> Path:
    return (base or config_home()) / "autostart" / f"{APP_SLUG}.desktop"


def autostart_enabled(base: Path | None = None) -> bool:
    return autostart_file(base).is_file()


def launcher_path() -> Path:
    return Path.home() / ".local" / "bin" / APP_SLUG


def launcher_command() -> str:
    """Command that starts the app, used inside .desktop files."""
    launcher = launcher_path()
    if launcher.is_file() and os.access(launcher, os.X_OK):
        return str(launcher)
    app_dir = Path(__file__).resolve().parent.parent
    venv_python = app_dir / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return f"{venv_python} -m desktop_buddy"
    return f"{sys.executable} -m desktop_buddy"


def icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "icon.svg"


def set_autostart(enabled: bool, base: Path | None = None) -> Path:
    """Create or remove the XDG autostart entry. Returns the entry path."""
    path = autostart_file(base)
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    icon = icon_path()
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=Desktop Buddy\n"
        "GenericName=Desktop pet\n"
        "Comment=A tiny creature that lives on your desktop\n"
        f"Exec={launcher_command()}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Utility;Game;\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=3\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def on_battery() -> bool:
    """True when any battery reports `Discharging`."""
    base = Path("/sys/class/power_supply")
    if not base.is_dir():
        return False
    for entry in base.glob("BAT*"):
        try:
            status = (entry / "status").read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if status == "discharging":
            return True
    return False


def battery_label() -> str:
    base = Path("/sys/class/power_supply")
    if not base.is_dir():
        return "no battery"
    for entry in sorted(base.glob("BAT*")):
        try:
            status = (entry / "status").read_text(encoding="utf-8").strip()
            capacity = (entry / "capacity").read_text(encoding="utf-8").strip()
            return f"{capacity}% ({status})"
        except OSError:
            continue
    return "unknown"


def session_type() -> str:
    session = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if session:
        return session
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def server_name() -> str:
    return f"{APP_SLUG}-{os.getuid()}"


def which_launcher() -> str:
    found = shutil.which(APP_SLUG)
    if found:
        return found
    launcher = launcher_path()
    if launcher.is_file() and os.access(launcher, os.X_OK):
        return f"{launcher} (not on PATH)"
    return "not installed"


def set_window_sticky(win_id: int) -> bool:
    """Best-effort: mark an X11 window as visible on all workspaces.

    Sets the EWMH `_NET_WM_DESKTOP` property to 0xFFFFFFFF, which Mutter
    interprets as "show on every workspace". Returns True on success.
    """
    if session_type() != "x11" or not win_id:
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
                ctypes.c_ulong(win_id),
                atom,
                ctypes.c_ulong(6),  # XA_CARDINAL
                32,
                0,  # PropModeReplace
                ctypes.byref(value),
                1,
            )
            x11.XFlush(display)
        finally:
            _restore_error_handler(x11, display, previous)
            x11.XCloseDisplay(display)
        return True
    except Exception:  # noqa: BLE001 - purely cosmetic, never fatal
        return False
