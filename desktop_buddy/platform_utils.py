"""Compatibility wrappers for the platform backend API."""

from __future__ import annotations

from pathlib import Path

from .platforms import get_backend


def config_home() -> Path:
    return get_backend().paths().config_dir.parent


def autostart_file(base: Path | None = None) -> Path:
    path = get_backend().autostart_path(base)
    if path is None:
        raise OSError("Autostart is unavailable on this platform.")
    return path


def autostart_enabled(base: Path | None = None) -> bool:
    return get_backend().autostart_enabled(base)


def set_autostart(enabled: bool, base: Path | None = None) -> Path:
    path = get_backend().set_autostart(enabled, base)
    if path is None:
        raise OSError("Autostart is unavailable on this platform.")
    return path


def icon_path() -> Path:
    return get_backend().icon_path()


def on_battery() -> bool:
    return get_backend().battery_status().on_battery


def battery_label() -> str:
    return get_backend().battery_status().label


def session_type() -> str:
    return get_backend().session_type()


def server_name() -> str:
    return get_backend().server_name()


def set_window_sticky(win_id: int) -> bool:
    return get_backend().apply_workspace_behavior(win_id)


def which_launcher() -> str:
    backend = get_backend()
    description = getattr(backend, "launcher_description", None)
    return description() if callable(description) else "not installed"
