"""Application entry point: CLI, controller, single-instance IPC."""

from __future__ import annotations

import argparse
import ctypes.util
import logging
import os
import signal
import sys
import time
from contextlib import suppress
from dataclasses import fields
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import APP_SLUG, __version__
from .config import CONFIG_PATH, LOG_PATH, Config
from .platform_utils import (
    autostart_enabled,
    autostart_file,
    battery_label,
    config_home,
    icon_path,
    launcher_command,
    on_battery,
    server_name,
    session_type,
    set_autostart,
    which_launcher,
)
from .prefs import PreferencesDialog
from .tray import BuddyTray
from .window import BuddyWindow

log = logging.getLogger(__name__)

CONTROL_COMMANDS = ("quit", "show", "hide", "toggle", "pause", "resume", "settings")

_CORE_APP: QCoreApplication | None = None


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


class Controller(QObject):
    """Glue between config, window, tray, preferences and IPC."""

    def __init__(self, app: QApplication, config: Config, first_run: bool = False) -> None:
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
        self._server = self._start_ipc()

        if self.tray.icon is not None:
            self.tray.icon.show()
        self.window.show()
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
        self.tray.refresh()
        self._schedule_save()

    def reset_config(self) -> None:
        self.config.reset()
        self.window.apply_config()
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

    def set_autostart(self, enabled: bool) -> None:
        enabled = bool(enabled)
        try:
            set_autostart(enabled)
        except OSError as exc:
            log.warning("Could not update autostart: %s", exc)
            self.tray.show_message("Desktop Buddy", f"Could not update autostart: {exc}")
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
                "<p>A tiny creature that lives on your desktop.</p>"
                "<p><b>Tips</b><br>"
                "&bull; Drag the buddy with the left mouse button<br>"
                "&bull; Double-click for a happy hop<br>"
                "&bull; Right-click for the menu; Ctrl+wheel resizes<br>"
                "&bull; Tray icon → Preferences for themes and behaviour</p>"
                f"<p style='color:gray'>Python {sys.version.split()[0]} &middot; "
                f"Qt {QT_VERSION_STR} &middot; PyQt {PYQT_VERSION_STR} &middot; "
                f"session: {session_type()}</p>"
            ),
        )

    def quit(self, *_args: object) -> None:
        self.save_config()
        if self.tray.icon is not None:
            self.tray.icon.hide()
        self.app.quit()

    # -------------------------------------------------------------------- ipc
    def _start_ipc(self) -> QLocalServer:
        QLocalServer.removeServer(server_name())
        server = QLocalServer(self)
        if not server.listen(server_name()):
            log.error("IPC server failed to start: %s", server.errorString())
        server.newConnection.connect(self._on_new_connection)
        return server

    def _on_new_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return

        def read(sock: QLocalSocket = socket) -> None:
            data = bytes(sock.readAll()).decode("utf-8", "replace")
            for line in data.splitlines():
                self.handle_command(line.strip())

        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
        read(socket)

    def handle_command(self, command: str) -> None:
        if not command:
            return
        parts = command.split()
        verb = parts[0]
        log.info("IPC command: %s", command)
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
        elif verb == "click-through" and len(parts) > 1:
            self.set_click_through(parts[1] == "on")
        elif verb == "autostart" and len(parts) > 1:
            self.set_autostart(parts[1] == "on")

    def _greet(self) -> None:
        self.window.say(
            f"Hi, I'm {self.config.name}! Drag me or right-click me.", 7.0
        )
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
        ("settings", "open the preferences window"),
    ):
        sub.add_parser(name, help=help_text)
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

    if send_command("show"):
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
