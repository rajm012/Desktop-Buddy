"""Application entry point: CLI, controller, single-instance IPC."""

from __future__ import annotations

import argparse
import ctypes.util
import json
import logging
import os
import random
import signal
import sys
import time
from contextlib import suppress
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import APP_SLUG, __version__
from .character import Palette
from .config import CONFIG_PATH, LOG_PATH, SPECIES, STATE_DIR, Config
from .platform_utils import (
    autostart_enabled,
    autostart_file,
    battery_label,
    icon_path,
    on_battery,
    server_name,
    session_type,
    set_autostart,
    which_launcher,
)
from .prefs import PreferencesDialog
from .sound import play_chime
from .toast import ReminderToast
from .tray import BuddyTray
from .wellness import Reminder, ReminderState, WellnessEngine
from .window import BuddyWindow

log = logging.getLogger(__name__)

CONTROL_COMMANDS = (
    "quit",
    "show",
    "hide",
    "toggle",
    "pause",
    "resume",
    "settings",
    "dance",
)

_CORE_APP: QCoreApplication | None = None


class LocalCommandServer(QObject):
    """Small newline-delimited local IPC server used by the primary instance."""

    def __init__(
        self,
        name: str,
        handler: Callable[[str], str | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.handler = handler
        QLocalServer.removeServer(name)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        if not self.server.listen(name):
            log.error("IPC server failed to start: %s", self.server.errorString())

    @property
    def listening(self) -> bool:
        return self.server.isListening()

    def close(self) -> None:
        self.server.close()
        QLocalServer.removeServer(self.name)

    def _on_new_connection(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                return

            def read(sock: QLocalSocket = socket) -> None:
                data = bytes(sock.readAll()).decode("utf-8", "replace")
                for line in data.splitlines():
                    reply = self.handler(line.strip())
                    if reply:
                        sock.write((reply + "\n").encode("utf-8"))
                        sock.flush()

            socket.readyRead.connect(read)
            socket.disconnected.connect(socket.deleteLater)
            read(socket)


def setup_logging(verbose: bool = False) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _ensure_core_app() -> QCoreApplication:
    global _CORE_APP
    app = QCoreApplication.instance()
    if app is None:
        _CORE_APP = QCoreApplication([sys.argv[0]])
        app = _CORE_APP
    return app


def send_command(command: str, timeout_ms: int = 900) -> bool:
    """Send a control command to a running instance. False when not running."""
    _ensure_core_app()
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(command.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return True


def request_reply(command: str, timeout_ms: int = 1400) -> str | None:
    """Send a command to a running instance and read its reply."""
    _ensure_core_app()
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(timeout_ms):
        return None
    socket.write((command + "\n").encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    reply = b""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if socket.waitForReadyRead(200):
            reply += bytes(socket.readAll())
            if b"\n" in reply:
                break
    socket.disconnectFromServer()
    text = reply.decode("utf-8", "replace").strip()
    return text or None


def request_status(timeout_ms: int = 1400) -> str | None:
    """Ask a running instance for a one-line status report."""
    return request_reply("status", timeout_ms)


class Controller(QObject):
    """Glue between config, window, tray, preferences and IPC."""

    def __init__(
        self, app: QApplication, config: Config, first_run: bool = False
    ) -> None:
        super().__init__()
        self.app = app
        self.config = config
        self.config.autostart = autostart_enabled()
        self.window = BuddyWindow(config)
        self.window.config_changed_callback = self._schedule_save
        self.tray = BuddyTray(self)
        self.window.context_menu_requested.connect(self._show_context_menu)
        self._prefs: PreferencesDialog | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_config)
        self._rng = random.Random()
        self._wellness_path = STATE_DIR / "reminders.json"
        self._wellness = self._build_wellness()
        self._toast: ReminderToast | None = None
        self._toast_queue: list[tuple[Reminder, str]] = []
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(20_000)
        self._reminder_timer.timeout.connect(self._check_reminders)
        self._reminder_timer.start()
        self._server = self._start_ipc()

        if self.tray.icon is not None:
            self.tray.icon.show()
        self.window.show()
        QTimer.singleShot(6000, self._check_reminders)
        if first_run:
            QTimer.singleShot(1200, self._greet)

    # ------------------------------------------------------------------ config
    def _schedule_save(self) -> None:
        self._save_timer.start(500)

    def save_config(self) -> None:
        self._save_timer.stop()
        self.config.position_x = self.window.current_x
        self.config.paused = self.window.is_paused
        self.config.autostart = autostart_enabled()
        try:
            self.config.save()
        except OSError as exc:
            log.warning("Could not save config: %s", exc)

    def apply_snapshot(self, snapshot: dict) -> None:
        restored = Config.from_dict(snapshot)
        for field_info in fields(Config):
            setattr(self.config, field_info.name, getattr(restored, field_info.name))
        self.window.apply_config()
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()

    def reset_config(self) -> None:
        self.config.reset()
        self.window.apply_config()
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()

    # --------------------------------------------------------------- settings
    def set_paused(self, paused: bool) -> None:
        self.config.paused = bool(paused)
        self.window.set_paused(bool(paused))
        self.tray.refresh()
        self._schedule_save()

    def toggle_paused(self, *_args: object) -> None:
        self.set_paused(not self.window.is_paused)

    def set_always_on_top(self, enabled: bool) -> None:
        self.config.always_on_top = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_click_through(self, enabled: bool) -> None:
        self.config.click_through = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()
        if enabled:
            message = "Click-through is on. Undo via the tray or: desktop-buddy click-through off"
            self.window.say("I can't feel clicks now!", 4.0)
            self.tray.show_message("Desktop Buddy", message)

    def set_reduce_on_battery(self, enabled: bool) -> None:
        self.config.reduce_on_battery = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_playful(self, enabled: bool) -> None:
        self.config.playful = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_can_sleep(self, enabled: bool) -> None:
        self.config.can_sleep = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_speed(self, value: float) -> None:
        self.config.speed = float(value)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_scale(self, value: float) -> None:
        self.config.scale = float(value)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_fps(self, value: int) -> None:
        self.config.fps = int(value)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_theme(self, key: str) -> None:
        self.config.theme = str(key)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_sleep_after(self, seconds: float) -> None:
        self.config.sleep_after = float(seconds)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_name(self, name: str) -> None:
        self.config.name = name
        self.window.apply_config()
        self._schedule_save()

    def set_species(self, key: str) -> None:
        if key not in SPECIES:
            return
        previous_default = SPECIES.get(self.config.species, {}).get("default_name", "")
        self.config.species = key
        if not self.config.name or self.config.name == previous_default:
            self.config.name = SPECIES[key]["default_name"]
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()
        self.window.say(f"{SPECIES[key]['label']} reporting for duty!", 3.2)

    def dance(self) -> None:
        self.window.dance()

    def set_perch_on_windows(self, enabled: bool) -> None:
        self.config.perch_on_windows = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()
        if enabled:
            self.window.say("I'll keep an eye on your windows!", 3.0)

    # -------------------------------------------------------------- reminders
    def _build_wellness(self) -> WellnessEngine:
        state = ReminderState()
        try:
            if self._wellness_path.is_file():
                state = ReminderState.from_dict(
                    json.loads(self._wellness_path.read_text(encoding="utf-8"))
                )
        except (OSError, ValueError):
            state = ReminderState()
        return WellnessEngine(self.config, state, self._rng)

    def _rebuild_wellness(self) -> None:
        self._wellness = WellnessEngine(self.config, self._wellness.state, self._rng)

    def _save_wellness(self) -> None:
        try:
            self._wellness_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._wellness_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._wellness.state.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, self._wellness_path)
        except OSError as exc:
            log.warning("Could not save reminder state: %s", exc)

    def _check_reminders(self) -> None:
        if not self.config.reminders_enabled:
            return
        now = datetime.now()
        for reminder in self._wellness.due(now):
            self._wellness.mark_done(reminder, now)
            self._save_wellness()
            self._fire_reminder(reminder)

    def _fire_reminder(self, reminder: Reminder, manual: bool = False) -> None:
        message = reminder.pick_message(self._rng)
        short = {
            "water": "Water break! 💧",
            "meal": f"{reminder.title} time! {reminder.icon}",
            "break": "Stretch break! 🧘",
            "winddown": "Wind down 🌙",
        }.get(reminder.kind, f"{reminder.title}!")
        self.window.remind(reminder.kind, short)
        if self.config.reminder_sound:
            play_chime(reminder.kind, STATE_DIR)
        self._queue_toast(reminder, message)
        if manual:
            log.info("Manual reminder: %s", reminder.id)

    def remind_now(self, key: str) -> bool:
        reminder = self._wellness.find(key)
        if reminder is None:
            return False
        self._fire_reminder(reminder, manual=True)
        return True

    def _queue_toast(self, reminder: Reminder, message: str) -> None:
        log.info("Queueing reminder toast: %s", reminder.id)
        self._toast_queue.append((reminder, message))
        if self._toast is None:
            self._show_next_toast()

    def _show_next_toast(self) -> None:
        if self._toast is not None or not self._toast_queue:
            return
        reminder, message = self._toast_queue.pop(0)
        log.info("Showing reminder toast: %s", reminder.id)
        palette = Palette.from_colors(self.config.theme_colors())
        toast = ReminderToast(
            reminder,
            message,
            palette,
            self._buddy_anchor,
            self._toast_done,
            self._toast_snooze,
            self._toast_dismiss,
            snooze_minutes=self.config.snooze_minutes or reminder.snooze_minutes,
        )
        toast.closed.connect(self._on_toast_closed)
        self._toast = toast
        toast.show_near_buddy()

    def _on_toast_closed(self) -> None:
        self._toast = None
        QTimer.singleShot(500, self._show_next_toast)

    def _buddy_anchor(self) -> tuple[int, int, int, int]:
        window = self.window
        return (window.x(), window.y(), window.width(), window.height())

    def _toast_done(self, reminder: Reminder) -> None:
        self._wellness.mark_done(reminder)
        self._save_wellness()
        self.window.say("Noted! ✅", 3.0)

    def _toast_snooze(self, reminder: Reminder) -> None:
        minutes = self.config.snooze_minutes or reminder.snooze_minutes
        self._wellness.snooze(reminder, minutes)
        self._save_wellness()
        self.window.say(f"Snoozed {minutes} min 😴", 3.0)

    def _toast_dismiss(self, reminder: Reminder) -> None:
        self._wellness.mark_done(reminder)
        self._save_wellness()

    def reminders_summary(self, count: int = 6) -> str:
        if not self.config.reminders_enabled:
            return "Wellness reminders are off."
        entries = self._wellness.upcoming(count)
        if not entries:
            return "No reminders configured."
        lines = [
            f"{when.strftime('%a %H:%M')}   {reminder.icon} {reminder.title}"
            for when, reminder in entries
        ]
        return "Upcoming reminders:\n\n" + "\n".join(lines)

    def show_reminders(self, *_args: object) -> None:
        QMessageBox.information(
            None, "Desktop Buddy — Reminders", self.reminders_summary(7)
        )

    def set_reminders_enabled(self, enabled: bool) -> None:
        self.config.reminders_enabled = bool(enabled)
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()
        if enabled:
            self.window.say("I'll remind you to eat and drink! 🍎💧", 4.0)

    def set_reminder_sound(self, enabled: bool) -> None:
        self.config.reminder_sound = bool(enabled)
        self.tray.refresh()
        self._schedule_save()

    def set_meal_time(self, key: str, value: str) -> None:
        field = f"{key}_time"
        if not hasattr(self.config, field):
            return
        setattr(self.config, field, value)
        self.config.normalize()
        self._rebuild_wellness()
        self._schedule_save()

    def set_meal_enabled(self, key: str, enabled: bool) -> None:
        field = f"{key}_enabled"
        if not hasattr(self.config, field):
            return
        setattr(self.config, field, bool(enabled))
        self._rebuild_wellness()
        self._schedule_save()

    def set_water_interval(self, minutes: int) -> None:
        self.config.water_interval_minutes = int(minutes)
        self.config.normalize()
        self._rebuild_wellness()
        self._schedule_save()

    def set_break_interval(self, minutes: int) -> None:
        self.config.break_interval_minutes = int(minutes)
        self.config.normalize()
        self._rebuild_wellness()
        self._schedule_save()

    def set_autostart(self, enabled: bool) -> None:
        enabled = bool(enabled)
        try:
            set_autostart(enabled)
        except OSError as exc:
            log.warning("Could not update autostart: %s", exc)
            self.tray.show_message(
                "Desktop Buddy", f"Could not update autostart: {exc}"
            )
            return
        self.config.autostart = enabled
        self.tray.refresh()
        self.save_config()
        if enabled:
            self.window.say("See you at login!", 3.5)
        else:
            self.window.say("Okay, I'll stay put.", 3.5)

    def autostart_active(self) -> bool:
        return autostart_enabled()

    # ----------------------------------------------------------------- window
    def show_buddy(self, *_args: object) -> None:
        self.window.set_visible(True)
        self.tray.refresh()

    def hide_buddy(self, *_args: object) -> None:
        self.window.set_visible(False)
        self.tray.refresh()

    def toggle_visibility(self, *_args: object) -> None:
        self.window.set_visible(not self.window.isVisible())
        self.tray.refresh()

    def _show_context_menu(self, position) -> None:  # noqa: ANN001
        self.tray.refresh()
        self.tray.menu.popup(position)

    # ------------------------------------------------------------------ dialogs
    def open_settings(self, *_args: object) -> None:
        if self._prefs is not None and self._prefs.isVisible():
            self._prefs.raise_()
            self._prefs.activateWindow()
            return
        dialog = PreferencesDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result: setattr(self, "_prefs", None))
        self._prefs = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_about(self, *_args: object) -> None:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        QMessageBox.about(
            None,
            "About Desktop Buddy",
            (
                f"<h3>Desktop Buddy {__version__}</h3>"
                "<p>A tiny robot or creature that lives on your desktop.</p>"
                "<p><b>Tips</b><br>"
                "&bull; Drag the buddy anywhere with the left mouse button<br>"
                "&bull; Double-click: Bolt and Boo dance; Mochi hops<br>"
                "&bull; Right-click for the menu; Ctrl+wheel resizes<br>"
                "&bull; It perches on your browser and terminal windows<br>"
                "&bull; Switch characters from the tray menu<br>"
                "&bull; Tray icon → Preferences for themes and behaviour</p>"
                f"<p style='color:gray'>Python {sys.version.split()[0]} &middot; "
                f"Qt {QT_VERSION_STR} &middot; PyQt {PYQT_VERSION_STR} &middot; "
                f"session: {session_type()}</p>"
            ),
        )

    def quit(self, *_args: object) -> None:
        self.save_config()
        self._save_wellness()
        if self.tray.icon is not None:
            self.tray.icon.hide()
        self.app.quit()

    # -------------------------------------------------------------------- ipc
    def _start_ipc(self) -> LocalCommandServer:
        return LocalCommandServer(server_name(), self.handle_command, self)

    def handle_command(self, command: str) -> str | None:
        if not command:
            return None
        parts = command.split()
        verb = parts[0]
        log.info("IPC command: %s", command)
        if verb == "status":
            return self._status_text()
        if verb == "quit":
            self.quit()
        elif verb == "show":
            self.show_buddy()
        elif verb == "hide":
            self.hide_buddy()
        elif verb == "toggle":
            self.toggle_visibility()
        elif verb == "pause":
            self.set_paused(True)
        elif verb == "resume":
            self.set_paused(False)
        elif verb == "settings":
            self.open_settings()
        elif verb == "dance":
            self.dance()
        elif verb == "character" and len(parts) > 1:
            self.set_species(parts[1])
        elif verb == "remind" and len(parts) > 1:
            if self.remind_now(parts[1]):
                return f"reminder fired: {parts[1]}"
            return f"unknown reminder: {parts[1]}"
        elif verb == "reminders" and len(parts) > 1:
            if parts[1] == "status":
                return self.reminders_summary(6)
            if parts[1] in ("on", "off"):
                self.set_reminders_enabled(parts[1] == "on")
                return f"reminders {parts[1]}"
            return "usage: reminders on|off|status"
        elif verb == "click-through" and len(parts) > 1:
            self.set_click_through(parts[1] == "on")
        elif verb == "autostart" and len(parts) > 1:
            self.set_autostart(parts[1] == "on")
        return None

    def _status_text(self) -> str:
        brain = self.window._brain  # noqa: SLF001 - diagnostic view
        screen_ground = brain.screen_world.ground if brain.screen_world else -1.0
        cooldown = max(0.0, self.window._perch_cooldown_until - time.monotonic())
        toast = self._toast
        if toast is None:
            toast_info = "-"
        else:
            try:
                toast_id = hex(int(toast.winId()))
            except Exception:  # noqa: BLE001
                toast_id = "?"
            toast_info = (
                f"{'visible' if toast.isVisible() else 'hidden'} id={toast_id} "
                f"geom=({toast.x()},{toast.y()},{toast.width()}x{toast.height()})"
            )
        return (
            f"state={brain.state.value} x={brain.x:.0f} y={brain.y:.0f} "
            f"world=({brain.world.left:.0f}..{brain.world.right:.0f},"
            f"ground={brain.world.ground:.0f}) screen_ground={screen_ground:.0f} "
            f"perched={'yes' if brain.perched else 'no'} "
            f"perch_kind={brain.perch.kind if brain.perch else '-'} "
            f"cooldown={cooldown:.0f}s win=({self.window.x()},{self.window.y()}) "
            f"feet_local={self.window._feet_local_px:.1f} "  # noqa: SLF001
            f"dpr={self.window.devicePixelRatioF():.2f} "
            f"presses={self.window._press_count} "  # noqa: SLF001
            f"toast={toast_info} "
            f"species={self.config.species} visible={self.window.isVisible()} "
            f"paused={self.window.is_paused}"
        )

    def _greet(self) -> None:
        self.window.say(f"Hi, I'm {self.config.name}! Drag me or right-click me.", 7.0)
        self.tray.show_message(
            "Desktop Buddy", f"{self.config.name} has moved onto your desktop!"
        )


def _libxcb_cursor_available() -> bool:
    if ctypes.util.find_library("xcb-cursor"):
        return True
    for entry in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
        if entry and any(Path(entry).glob("libxcb-cursor.so.0*")):
            return True
    vendor = Path(__file__).resolve().parent.parent / "vendor" / "syslibs"
    return any(vendor.glob("libxcb-cursor.so.0*"))


def diagnose() -> int:
    """Print a support-friendly environment report."""

    def line(label: str, value: object) -> None:
        print(f"  {label:<16}: {value}", flush=True)

    print("Desktop Buddy diagnostics", flush=True)
    line("version", __version__)
    line("python", f"{sys.version.split()[0]} ({sys.executable})")
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        line("PyQt / Qt", f"{PYQT_VERSION_STR} / {QT_VERSION_STR}")
    except Exception as exc:  # noqa: BLE001
        line("PyQt / Qt", f"unavailable ({exc})")
    line("session", f"{session_type()} (compositor restrictions may apply on wayland)")
    line("DISPLAY", os.environ.get("DISPLAY", "-"))
    line("WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", "-"))
    line("libxcb-cursor", "available" if _libxcb_cursor_available() else "MISSING")
    line("battery", f"{battery_label()} | on battery: {on_battery()}")
    try:
        from .window_probe import X11WindowProbe, classify

        probe = X11WindowProbe()
        info = probe.active_window()
        if info is not None:
            line(
                "active window",
                f"{info.class_name or '?'} {info.width}x{info.height} "
                f"at ({info.x},{info.y}) kind={classify(info.class_name)}",
            )
        else:
            line("active window", "unavailable")
        probe.close()
    except Exception as exc:  # noqa: BLE001
        line("active window", f"error: {exc}")
    line("launcher", which_launcher())
    line("autostart", "enabled" if autostart_enabled() else "disabled")
    line("autostart file", autostart_file() if autostart_enabled() else "-")
    line("config", CONFIG_PATH)
    line("log", LOG_PATH)
    try:
        app = QApplication([sys.argv[0]])
    except Exception as exc:  # noqa: BLE001
        line("GUI probe", f"FAILED: {exc}")
        return 1
    line("Qt platform", app.platformName())
    for screen in app.screens():
        geometry = screen.geometry()
        line(
            "screen",
            f"{screen.name()} {geometry.width()}x{geometry.height()} "
            f"@ {screen.devicePixelRatio()}x",
        )
    if session_type() == "wayland":
        print(
            "  note            : Wayland blocks self-positioning/always-on-top; "
            "log in with 'Ubuntu on Xorg' for full behaviour.",
            flush=True,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="desktop-buddy",
        description="A tiny creature that lives on your desktop.",
    )
    parser.add_argument(
        "--version", action="version", version=f"desktop-buddy {__version__}"
    )
    parser.add_argument(
        "--reset-config", action="store_true", help="delete the saved settings"
    )
    parser.add_argument(
        "--diagnose", action="store_true", help="print environment diagnostics"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log to stdout")
    sub = parser.add_subparsers(dest="command")
    for name, help_text in (
        ("quit", "stop the running buddy"),
        ("show", "show the buddy"),
        ("hide", "hide the buddy"),
        ("toggle", "toggle visibility"),
        ("pause", "pause movement"),
        ("resume", "resume movement"),
        ("dance", "start a dance party"),
        ("status", "print what the buddy is doing"),
        ("settings", "open the preferences window"),
    ):
        sub.add_parser(name, help=help_text)
    remind = sub.add_parser("remind", help="fire a wellness reminder now")
    remind.add_argument(
        "value",
        choices=("breakfast", "lunch", "snack", "dinner", "water", "break", "winddown"),
    )
    reminders = sub.add_parser("reminders", help="manage wellness reminders")
    reminders.add_argument("value", choices=("on", "off", "status"))
    character = sub.add_parser("character", help="switch character")
    character.add_argument("value", choices=tuple(SPECIES))
    click = sub.add_parser("click-through", help="toggle input pass-through")
    click.add_argument("value", choices=("on", "off"))
    auto = sub.add_parser("autostart", help="manage login autostart")
    auto.add_argument("value", choices=("on", "off", "status"))
    return parser


def main(argv: list[str] | None = None) -> int:
    with suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.diagnose:
        return diagnose()

    setup_logging(args.verbose)

    if args.command is not None:
        if args.command == "remind":
            reply = request_reply(f"remind {args.value}")
            if reply:
                print(reply)
                return 0
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
        if args.command == "reminders":
            if args.value == "status":
                reply = request_reply("reminders status")
                if reply:
                    print(reply)
                    return 0
                print("Desktop Buddy is not running.", file=sys.stderr)
                return 1
            if send_command(f"reminders {args.value}"):
                print(f"Reminders {args.value}")
                return 0
            config = Config.load()
            config.reminders_enabled = args.value == "on"
            config.save()
            print(f"Reminders {args.value} (applies next time it starts)")
            return 0
        if args.command == "status":
            reply = request_status()
            if reply:
                print(reply)
                return 0
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
        if args.command in CONTROL_COMMANDS and send_command(args.command):
            return 0
        if args.command == "autostart":
            if args.value == "status":
                print("enabled" if autostart_enabled() else "disabled")
                return 0
            enabled = args.value == "on"
            try:
                set_autostart(enabled)
            except OSError as exc:
                print(f"Could not update autostart: {exc}", file=sys.stderr)
                return 1
            print(f"Autostart {'enabled' if enabled else 'disabled'}")
            return 0
        if args.command == "click-through":
            enabled = args.value == "on"
            config = Config.load()
            config.click_through = enabled
            config.save()
            print(f"Click-through {'enabled' if enabled else 'disabled'}")
            return 0
        if args.command == "character":
            if send_command(f"character {args.value}"):
                return 0
            config = Config.load()
            previous_default = SPECIES.get(config.species, {}).get("default_name", "")
            config.species = args.value
            if not config.name or config.name == previous_default:
                config.name = SPECIES[args.value]["default_name"]
            config.save()
            print(f"Character set to {SPECIES[args.value]['label']}")
            return 0
        print("Desktop Buddy is not running.", file=sys.stderr)
        return 1

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Desktop Buddy")
    app.setApplicationDisplayName("Desktop Buddy")
    app.setOrganizationName("DesktopBuddy")
    app.setDesktopFileName(APP_SLUG)
    if icon_path().is_file():
        icon = QIcon(str(icon_path()))
        if not icon.isNull():
            app.setWindowIcon(icon)
    app.setQuitOnLastWindowClosed(False)

    if args.reset_config:
        send_command("quit")
        time.sleep(0.6)
        with suppress(FileNotFoundError):
            CONFIG_PATH.unlink()
        print(f"Removed {CONFIG_PATH}")

    if request_reply("status", timeout_ms=700):
        send_command("show")
        print("Desktop Buddy is already running (showing it).")
        return 0

    config = Config.load()
    controller = Controller(app, config, first_run=not CONFIG_PATH.exists())

    def _quit(*_args: object) -> None:
        controller.quit()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
