"""Probe the active X11 window (class + geometry) with ctypes.

No external tools are required. Used by the "perch on windows" feature so the
buddy can sit near the browser search bar or a terminal prompt.
"""

from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass

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


def classify(class_name: str) -> str | None:
    """Return 'browser', 'terminal' or None for a WM_CLASS string."""
    lowered = (class_name or "").lower()
    if any(key in lowered for key in BROWSER_KEYS):
        return "browser"
    if any(key in lowered for key in TERMINAL_KEYS):
        return "terminal"
    return None


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    class_name: str
    title: str
    x: int
    y: int
    width: int
    height: int
    hidden: bool = False


class X11WindowProbe:
    """Reads _NET_ACTIVE_WINDOW, WM_CLASS, _NET_WM_NAME and geometry."""

    def __init__(self) -> None:
        self._lib = None
        self._dpy = None
        self._root = 0
        self._atoms: dict[bytes, int] = {}
        if os.environ.get("XDG_SESSION_TYPE", "").lower() not in ("", "x11"):
            return
        if not os.environ.get("DISPLAY"):
            return
        try:
            lib = ctypes.CDLL("libX11.so.6")
        except OSError:
            return
        try:
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

    # ------------------------------------------------------------------ basics
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
        if not parts:
            return ""
        return parts[-1].decode("utf-8", "replace")

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
            value = ctypes.c_ulong.from_buffer_copy(chunk).value
            if int(value) == wanted:
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

    # ------------------------------------------------------------------- query
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
        title = self._string(
            window, self._atom(b"_NET_WM_NAME"), self._atom(b"UTF8_STRING")
        )
        hidden = self._has_atom(
            window,
            self._atom(b"_NET_WM_STATE"),
            self._atom(b"_NET_WM_STATE_HIDDEN"),
        )
        return WindowInfo(
            window_id=window,
            class_name=self._class_name(window),
            title=title,
            x=x,
            y=y,
            width=width,
            height=height,
            hidden=hidden,
        )
