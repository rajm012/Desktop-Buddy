"""Application entry point: CLI, controller, single-instance IPC."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shlex
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import fields
from datetime import date, datetime
from typing import Callable

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import APP_SLUG, __version__
from .actions import ActionDefinition, ActionRegistry
from .character import Palette
from .config import CONFIG_PATH, LOG_PATH, SPECIES, Config
from .context import ContextEngine, NetworkStatus, profiles_from_config
from .focus import (
    FocusEngine,
    FocusEvent,
    FocusEventType,
    FocusSettings,
    FocusState,
    SessionKind,
    format_duration,
    kind_label,
)
from .platforms import get_backend
from .platforms.base import Capability, PlatformBackend
from .plugins import (
    PLUGIN_API_VERSION,
    PluginHost,
    PluginManager,
    PluginPermission,
    PluginStatus,
)
from .prefs import OnboardingDialog, PreferencesDialog
from .sound import chime_path
from .toast import ReminderToast
from .tray import BuddyTray
from .wellness import (
    Reminder,
    ReminderState,
    WellnessEngine,
    parse_reminder_phrase,
)
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
    socket.connectToServer(get_backend().server_name())
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
    socket.connectToServer(get_backend().server_name())
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
        self,
        app: QApplication,
        config: Config,
        first_run: bool = False,
        backend: PlatformBackend | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.backend = backend or get_backend()
        self.config = config
        self.config.autostart = self.backend.autostart_enabled()
        self.window = BuddyWindow(config, backend=self.backend)
        self.window.config_changed_callback = self._schedule_save
        self._rng = random.Random()
        self._state_dir = self.backend.paths().state_dir
        self._wellness_path = self._state_dir / "reminders.json"
        self._focus_path = self._state_dir / "focus.json"
        self._plugin_actions: dict[str, tuple[str, Callable[[], object]]] = {}
        self._plugin_reminders: dict[str, dict[str, object]] = {}
        self._plugin_tray_items: dict[str, tuple[str, str, Callable[[], object]]] = {}
        self._plugin_settings_pages: dict[
            str, tuple[str, str, Callable[..., object]]
        ] = {}
        self._meeting_active = False
        self._meeting_title = ""
        self._context = Controller._build_context_engine(self)
        self._context_paused = False
        self._wellness = self._build_wellness()
        self._focus = FocusEngine(
            FocusSettings.from_config(self.config),
            FocusState.load(self._focus_path),
        )
        self._actions = self._build_actions()
        self.window.set_focus_state(
            self._focus.state.kind,
            self._focus.state.status,
            self._focus.remaining_seconds(),
        )
        self.tray = BuddyTray(self)
        self.window.context_menu_requested.connect(self._show_context_menu)
        self._prefs: PreferencesDialog | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_config)
        self._plugins = self._build_plugins()
        self._plugins.events.emit(
            "system.capabilities",
            {"available": sorted(self._plugins.available_capabilities)},
        )
        self._plugins.events.emit("app.started", {"version": __version__})
        self._toast: ReminderToast | None = None
        self._toast_queue: list[tuple[Reminder, str]] = []
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(20_000)
        self._reminder_timer.timeout.connect(self._check_reminders)
        self._reminder_timer.start()
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(1000)
        self._focus_timer.timeout.connect(self._check_focus)
        self._focus_timer.start()
        self._context_timer = QTimer(self)
        self._context_timer.setInterval(15_000)
        self._context_timer.timeout.connect(self._check_context)
        self._context_timer.start()
        self._server = self._start_ipc()

        if self.tray.icon is not None:
            self.tray.icon.show()
        self.window.show()
        QTimer.singleShot(200, self._check_focus)
        QTimer.singleShot(1200, self._check_context)
        QTimer.singleShot(6000, self._check_reminders)
        if first_run:
            QTimer.singleShot(700, self.open_onboarding)

    # ------------------------------------------------------------------ config
    def _schedule_save(self) -> None:
        self._save_timer.start(500)

    def save_config(self) -> None:
        self._save_timer.stop()
        self.config.position_x = self.window.current_x
        self.config.paused = self.window.is_paused
        self.config.autostart = self.backend.autostart_enabled()
        try:
            self.config.save()
        except OSError as exc:
            log.warning("Could not save config: %s", exc)

    def apply_snapshot(self, snapshot: dict) -> None:
        restored = Config.from_dict(snapshot)
        requested_autostart = restored.autostart
        for field_info in fields(Config):
            setattr(self.config, field_info.name, getattr(restored, field_info.name))
        if (
            self.backend.supports(Capability.AUTOSTART)
            and self.backend.autostart_enabled() != requested_autostart
        ):
            try:
                self.backend.set_autostart(requested_autostart)
            except OSError as exc:
                log.warning("Could not restore autostart setting: %s", exc)
        self.config.autostart = self.backend.autostart_enabled()
        self.window.apply_config()
        getattr(self, "_reload_plugins", lambda: None)()
        self._rebuild_wellness()
        self._rebuild_focus()
        getattr(self, "_rebuild_actions", lambda: None)()
        self._context = Controller._build_context_engine(self)
        self.tray.refresh()
        self._schedule_save()

    def reset_config(self) -> None:
        self.config.reset()
        if self.backend.supports(Capability.AUTOSTART):
            try:
                self.backend.set_autostart(False)
            except OSError as exc:
                log.warning("Could not reset autostart setting: %s", exc)
        self.config.autostart = self.backend.autostart_enabled()
        self.window.apply_config()
        getattr(self, "_reload_plugins", lambda: None)()
        self._rebuild_wellness()
        self._rebuild_focus()
        getattr(self, "_rebuild_actions", lambda: None)()
        self._context = Controller._build_context_engine(self)
        self.tray.refresh()
        self._schedule_save()

    # ---------------------------------------------------------------- plugins
    def _build_plugins(self) -> PluginManager:
        from .builtin_plugins import builtins_for

        available = {
            capability.value
            for capability, info in self.backend.capabilities().items()
            if info.available
        }
        host = PluginHost(
            register_action=self._register_plugin_action,
            register_reminder=self._register_plugin_reminder,
            register_tray_item=self._register_plugin_tray_item,
            register_settings_page=self._register_plugin_settings_page,
        )
        manager = PluginManager(
            app_version=__version__,
            config_state=self.config.plugins,
            available_capabilities=available,
            host=host,
            state_changed=self._plugin_state_changed,
            logger=log,
        )
        manager.events.subscribe("__core__", "calendar.meeting", self._calendar_event)
        for metadata, factory in builtins_for(self.config, self._schedule_save):
            manager.register_builtin(metadata, factory)
        manager.discover_external([self.backend.paths().config_dir / "plugins"])
        manager.load_enabled()
        return manager

    def _reload_plugins(self) -> None:
        old = getattr(self, "_plugins", None)
        if old is not None:
            old.unload()
        self._plugin_actions.clear()
        self._plugin_reminders.clear()
        self._plugin_tray_items.clear()
        self._plugin_settings_pages.clear()
        self._plugins = self._build_plugins()
        self._plugins.events.emit("app.started", {"version": __version__})

    def _plugin_state_changed(self) -> None:
        self._schedule_save()
        if hasattr(self, "tray"):
            self.tray.refresh()
        prefs = getattr(self, "_prefs", None)
        if prefs is not None and hasattr(prefs, "refresh_plugins"):
            prefs.refresh_plugins()

    def _register_plugin_action(
        self,
        _plugin_id: str,
        action_id: str,
        name: str,
        callback: Callable[[], object],
    ) -> Callable[[], None]:
        if action_id in self._plugin_actions:
            raise ValueError(f"Duplicate plugin action: {action_id}")
        self._plugin_actions[action_id] = (name, callback)
        if hasattr(self, "_actions"):
            self._rebuild_actions()
        if hasattr(self, "tray"):
            self.tray.refresh()

        def cleanup() -> None:
            self._plugin_actions.pop(action_id, None)
            if hasattr(self, "_actions"):
                self._rebuild_actions()
            if hasattr(self, "tray"):
                self.tray.refresh()

        return cleanup

    def _register_plugin_reminder(
        self, _plugin_id: str, definition: dict[str, object]
    ) -> Callable[[], None]:
        reminder = Reminder.from_dict(definition)
        if reminder is None:
            raise ValueError("Plugin supplied an invalid reminder definition.")
        if reminder.id in self._plugin_reminders:
            raise ValueError(f"Duplicate plugin reminder: {reminder.id}")
        self._plugin_reminders[reminder.id] = reminder.to_dict()
        if hasattr(self, "_wellness"):
            self._rebuild_wellness()

        def cleanup() -> None:
            self._plugin_reminders.pop(reminder.id, None)
            if hasattr(self, "_wellness"):
                self._rebuild_wellness()

        return cleanup

    def _register_plugin_tray_item(
        self,
        plugin_id: str,
        item_id: str,
        label: str,
        callback: Callable[[], object],
    ) -> Callable[[], None]:
        if item_id in self._plugin_tray_items:
            raise ValueError(f"Duplicate plugin tray item: {item_id}")
        self._plugin_tray_items[item_id] = (plugin_id, label, callback)
        if hasattr(self, "tray"):
            self.tray.refresh()

        def cleanup() -> None:
            self._plugin_tray_items.pop(item_id, None)
            if hasattr(self, "tray"):
                self.tray.refresh()

        return cleanup

    def _register_plugin_settings_page(
        self,
        plugin_id: str,
        page_id: str,
        title: str,
        factory: Callable[..., object],
    ) -> Callable[[], None]:
        if page_id in self._plugin_settings_pages:
            raise ValueError(f"Duplicate plugin settings page: {page_id}")
        self._plugin_settings_pages[page_id] = (plugin_id, title, factory)

        def cleanup() -> None:
            self._plugin_settings_pages.pop(page_id, None)

        return cleanup

    def plugin_settings_pages(
        self,
    ) -> list[tuple[str, str, str, Callable[..., object]]]:
        return [
            (page_id, plugin_id, title, factory)
            for page_id, (
                plugin_id,
                title,
                factory,
            ) in self._plugin_settings_pages.items()
        ]

    def set_plugin_permissions(self, plugin_id: str, values: list[str]) -> bool:
        permissions: set[PluginPermission] = set()
        try:
            permissions = {PluginPermission(value) for value in values}
        except ValueError:
            return False
        return self._plugins.set_permissions(plugin_id, permissions)

    def set_plugin_enabled(
        self, plugin_id: str, enabled: bool, permissions: list[str] | None = None
    ) -> bool:
        if not enabled:
            changed = self._plugins.disable(plugin_id)
        else:
            granted = None
            if permissions is not None:
                try:
                    granted = {PluginPermission(value) for value in permissions}
                except ValueError:
                    return False
            changed = self._plugins.enable(plugin_id, granted)
        self._rebuild_wellness()
        self._rebuild_actions()
        self.tray.refresh()
        return changed

    def plugins_summary(self) -> str:
        return self._plugins.summary()

    def plugin_info(self, plugin_id: str) -> str:
        record = self._plugins.records.get(plugin_id)
        if record is None:
            return f"Unknown plugin: {plugin_id}"
        metadata = record.metadata
        granted = self._plugins.granted_permissions(plugin_id)
        requested = ", ".join(item.value for item in metadata.permissions) or "none"
        granted_text = ", ".join(sorted(item.value for item in granted)) or "none"
        capabilities = ", ".join(metadata.required_capabilities) or "none"
        data_access = "; ".join(metadata.data_access) or "none declared"
        return (
            f"{metadata.name} {metadata.version} ({metadata.id})\n"
            f"Status: {record.status.value}\n"
            f"Origin: {'built-in' if metadata.builtin else record.source}\n"
            f"Permissions requested: {requested}\n"
            f"Permissions granted: {granted_text}\n"
            f"Required capabilities: {capabilities}\n"
            f"Data read: {data_access}\n"
            f"{metadata.description}"
            + (f"\nError: {record.error}" if record.error else "")
        )

    def _emit_plugin_event(self, event_name: str, **payload: object) -> None:
        manager = getattr(self, "_plugins", None)
        if manager is not None:
            manager.events.emit(event_name, payload)

    def _calendar_event(self, event) -> None:  # noqa: ANN001
        self._meeting_active = bool(event.payload.get("active", False))
        self._meeting_title = str(event.payload.get("title", ""))[:120]

    def _build_context_engine(self) -> ContextEngine:
        return ContextEngine(
            profiles_from_config(self.config.application_profiles),
            self.config.low_battery_percent,
        )

    def _check_context(self) -> None:
        if not self.config.context_enabled:
            if self.backend.adapt_exclusive_fullscreen:
                self.window.set_platform_fullscreen(self.backend.fullscreen_active())
            self._emit_plugin_event(
                "system.context", timestamp=datetime.now().isoformat()
            )
            return
        active_class = ""
        active_title = ""
        fullscreen = False
        if self.backend.supports(Capability.ACTIVE_WINDOW):
            probe = self.backend.create_active_window_probe()
            try:
                info = probe.active_window() if probe.available else None
                if info is not None:
                    active_class = info.class_name
                    active_title = info.title
                    fullscreen = info.fullscreen
            finally:
                probe.close()
        idle_seconds = (
            self.backend.idle_seconds()
            if self.backend.supports(Capability.IDLE_TIME)
            else None
        )
        battery = self.backend.battery_status()
        network = (
            self.backend.network_status()
            if self.config.context_network_events
            and self.backend.supports(Capability.NETWORK)
            else NetworkStatus()
        )
        changes = self._context.update(
            idle_seconds=idle_seconds,
            fullscreen=fullscreen,
            active_class=active_class,
            active_title=active_title,
            on_battery=battery.on_battery,
            battery_percent=battery.percent,
            network=network,
            meeting_active=self._meeting_active,
            meeting_title=self._meeting_title,
        )
        for change in changes:
            if (
                change.name == "system.network"
                and not self.config.context_network_events
            ):
                continue
            if (
                change.name == "system.low_battery"
                and not self.config.context_low_battery_events
            ):
                continue
            if change.name != "calendar.meeting":
                self._plugins.events.emit(change.name, change.payload)
        state = self._context.snapshot
        self.window.set_platform_fullscreen(state.fullscreen)
        should_pause = state.profile_pauses_animation
        if should_pause != self._context_paused:
            self._context_paused = should_pause
            self.window.set_paused(self.config.paused or should_pause)
            self.tray.refresh()
        self._emit_plugin_event(
            "system.context",
            idle_seconds=state.idle_seconds,
            fullscreen=state.fullscreen,
            active_class=state.active_class,
            active_title=state.active_title,
            profile_id=state.profile_id,
            network=state.network.value,
            low_battery=state.low_battery,
        )

    # --------------------------------------------------------------- settings
    def set_paused(self, paused: bool) -> None:
        self.config.paused = bool(paused)
        self.window.set_paused(bool(paused) or self._context_paused)
        self.tray.refresh()
        self._schedule_save()

    def toggle_paused(self, *_args: object) -> None:
        self.set_paused(not self.window.is_paused)

    def set_always_on_top(self, enabled: bool) -> None:
        if enabled and not self.backend.supports(Capability.ALWAYS_ON_TOP):
            self._show_unavailable(Capability.ALWAYS_ON_TOP)
            return
        self.config.always_on_top = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_click_through(self, enabled: bool) -> None:
        if enabled and not self.backend.supports(Capability.CLICK_THROUGH):
            self._show_unavailable(Capability.CLICK_THROUGH)
            return
        self.config.click_through = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()
        if enabled:
            message = "Click-through is on. Undo via the tray or: desktop-buddy click-through off"
            self.window.say("I can't feel clicks now!", 4.0)
            self.tray.show_message("Desktop Buddy", message)

    def set_reduce_on_battery(self, enabled: bool) -> None:
        if enabled and not self.backend.supports(Capability.BATTERY):
            self._show_unavailable(Capability.BATTERY)
            return
        self.config.reduce_on_battery = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_reduced_motion(self, enabled: bool) -> None:
        self.config.reduced_motion = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()

    def set_silent_mode(self, enabled: bool) -> None:
        self.config.silent_mode = bool(enabled)
        self.tray.refresh()
        self._schedule_save()

    def set_do_not_disturb(self, enabled: bool) -> None:
        self.config.do_not_disturb = bool(enabled)
        self.tray.refresh()
        self._schedule_save()

    def set_context_setting(self, name: str, value: object) -> None:
        if name not in {
            "context_enabled",
            "context_suppress_fullscreen",
            "context_network_events",
            "context_low_battery_events",
            "low_battery_percent",
            "media_controls_enabled",
            "calendar_meeting_quiet",
        }:
            return
        setattr(self.config, name, value)
        self.config.normalize()
        self._context = self._build_context_engine()
        self._schedule_save()
        QTimer.singleShot(0, self._check_context)

    def add_application_profile(
        self, name: str, class_contains: str, title_contains: str = ""
    ) -> bool:
        if not str(name).strip() or not (
            str(class_contains).strip() or str(title_contains).strip()
        ):
            return False
        existing = {
            str(item.get("id", ""))
            for item in self.config.application_profiles
            if isinstance(item, dict)
        }
        index = len(existing) + 1
        profile_id = f"profile-{index}"
        while profile_id in existing:
            index += 1
            profile_id = f"profile-{index}"
        self.config.application_profiles.append(
            {
                "id": profile_id,
                "name": str(name).strip()[:80],
                "class_contains": str(class_contains).strip()[:120],
                "title_contains": str(title_contains).strip()[:120],
                "suppress_notifications": True,
                "pause_animation": False,
                "enabled": True,
            }
        )
        self.config.normalize()
        self._context = self._build_context_engine()
        self._schedule_save()
        return True

    def remove_application_profile(self, profile_id: str) -> bool:
        before = len(self.config.application_profiles)
        self.config.application_profiles = [
            item
            for item in self.config.application_profiles
            if not isinstance(item, dict) or item.get("id") != profile_id
        ]
        if len(self.config.application_profiles) == before:
            return False
        self._context = self._build_context_engine()
        self._schedule_save()
        return True

    def media_command(self, action: str) -> str:
        if not self.config.media_controls_enabled:
            return "media controls are disabled"
        if not self.backend.supports(Capability.MEDIA_CONTROLS):
            return self.backend.capability(Capability.MEDIA_CONTROLS).reason
        if action == "status":
            status = self.backend.media_status()
            if not status.available:
                return "no compatible media player is active"
            return f"{status.playback}: {status.player}"
        return (
            f"media {action} sent"
            if self.backend.media_control(action)
            else "no compatible media player accepted the command"
        )

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
        if enabled and not self.backend.supports(Capability.ACTIVE_WINDOW):
            self._show_unavailable(Capability.ACTIVE_WINDOW)
            return
        self.config.perch_on_windows = bool(enabled)
        self.window.apply_config()
        self.tray.refresh()
        self._schedule_save()
        if enabled:
            self.window.say("I'll keep an eye on your windows!", 3.0)

    # -------------------------------------------------------------- reminders
    def _wellness_config(self) -> Config:
        if not self._plugin_reminders:
            return self.config
        combined = self.config.copy()
        combined.reminders.extend(
            dict(definition) for definition in self._plugin_reminders.values()
        )
        return combined

    def _build_wellness(self) -> WellnessEngine:
        state = ReminderState()
        try:
            if self._wellness_path.is_file():
                state = ReminderState.from_dict(
                    json.loads(self._wellness_path.read_text(encoding="utf-8"))
                )
        except (OSError, ValueError):
            state = ReminderState()
        return WellnessEngine(self._wellness_config(), state, self._rng)

    def _rebuild_wellness(self) -> None:
        self._wellness = WellnessEngine(
            self._wellness_config(), self._wellness.state, self._rng
        )

    def _save_wellness(self) -> None:
        try:
            self._wellness_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._wellness_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._wellness.state.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, self._wellness_path)
            self._wellness.dirty = False
        except OSError as exc:
            log.warning("Could not save reminder state: %s", exc)

    def _check_reminders(self) -> None:
        if not self.config.reminders_enabled or self.config.do_not_disturb:
            if self._wellness.dirty:
                self._save_wellness()
            return
        now = datetime.now()
        occurrences = self._wellness.due(now)
        for occurrence in occurrences:
            if not Controller._context_attention_allowed(
                self, occurrence.reminder.urgent
            ):
                continue
            self._wellness.mark_triggered(occurrence)
            self._fire_reminder(occurrence.reminder)
        if self._wellness.dirty:
            self._save_wellness()

    def _fire_reminder(self, reminder: Reminder, manual: bool = False) -> None:
        message = reminder.pick_message(self._rng)
        short = {
            "water": "Water break! 💧",
            "meal": f"{reminder.title} time! {reminder.icon}",
            "break": "Stretch break! 🧘",
            "winddown": "Wind down 🌙",
        }.get(reminder.kind, f"{reminder.title}!")
        self.window.remind(reminder.kind, short)
        if (
            self.config.reminder_sound
            and not self.config.silent_mode
            and self.backend.supports(Capability.AUDIO)
        ):
            self.backend.play_audio(chime_path(reminder.kind, self._state_dir))
        self._queue_toast(reminder, message)
        self._emit_plugin_event(
            "reminder.triggered", reminder_id=reminder.id, manual=manual
        )
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
        if reminder.action_id:
            result = self.run_action(reminder.action_id, announce=False)
            self.window.say(
                result.message if not result.ok else "Done — action run! ✅", 4.0
            )
        else:
            self.window.say("Noted! ✅", 3.0)
        self._emit_plugin_event("reminder.done", reminder_id=reminder.id)

    def _toast_snooze(self, reminder: Reminder) -> None:
        minutes = self.config.snooze_minutes or reminder.snooze_minutes
        self._wellness.snooze(reminder, minutes)
        self._save_wellness()
        self.window.say(f"Snoozed {minutes} min 😴", 3.0)
        self._emit_plugin_event(
            "reminder.snoozed", reminder_id=reminder.id, minutes=minutes
        )

    def _toast_dismiss(self, reminder: Reminder) -> None:
        self._wellness.mark_missed(reminder)
        self._save_wellness()
        self._emit_plugin_event("reminder.missed", reminder_id=reminder.id)

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

    def reminder_history_summary(self, count: int = 20) -> str:
        entries = self._wellness.recent_history(count)
        if not entries:
            return "No reminder history yet."
        return "Reminder history:\n\n" + "\n".join(
            f"{entry.handled_at.strftime('%Y-%m-%d %H:%M')}  "
            f"{entry.status.value:<7}  {entry.title}"
            for entry in entries
        )

    @staticmethod
    def _unique_config_id(title: str, existing: set[str]) -> str:
        base = (
            "".join(
                char if char.isalnum() or char in "_-" else "-"
                for char in title.strip().lower()
            ).strip("-")[:48]
            or "item"
        )
        candidate = base
        suffix = 2
        while candidate in existing:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def save_reminder_definition(
        self, data: dict[str, object], existing_id: str | None = None
    ) -> str:
        candidate = dict(data)
        existing_ids = {
            str(item.get("id", ""))
            for item in self.config.reminders
            if isinstance(item, dict) and str(item.get("id", "")) != existing_id
        }
        candidate["id"] = existing_id or self._unique_config_id(
            str(candidate.get("title", "Reminder")), existing_ids
        )
        reminder = Reminder.from_dict(candidate)
        if reminder is None:
            raise ValueError("The reminder definition is incomplete or invalid.")
        serialized = reminder.to_dict()
        replaced = False
        updated: list[dict[str, object]] = []
        for item in self.config.reminders:
            if isinstance(item, dict) and item.get("id") == existing_id:
                updated.append(serialized)
                replaced = True
            elif isinstance(item, dict):
                updated.append(item)
        if not replaced:
            updated.append(serialized)
        self.config.reminders = updated
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()
        return reminder.id

    def add_reminder(self, title: str, schedule_text: str) -> str:
        schedule = parse_reminder_phrase(schedule_text)
        data: dict[str, object] = {
            "title": title.strip()[:80] or "Reminder",
            "kind": "custom",
            "icon": "⏰",
            "message": title.strip()[:500] or "Reminder!",
            "enabled": True,
            "urgent": False,
            "snooze_minutes": self.config.snooze_minutes,
            "recurrence": schedule.recurrence.value,
        }
        if schedule.time_of_day is not None:
            data["time"] = schedule.time_of_day.strftime("%H:%M")
        if schedule.one_time_at is not None:
            data["one_time_at"] = schedule.one_time_at.isoformat()
        if schedule.interval_minutes is not None:
            data["interval_minutes"] = schedule.interval_minutes
        if schedule.weekdays:
            data["weekdays"] = list(schedule.weekdays)
        return self.save_reminder_definition(data)

    def remove_reminder(self, reminder_id: str) -> bool:
        before = len(self.config.reminders)
        self.config.reminders = [
            item
            for item in self.config.reminders
            if not isinstance(item, dict) or item.get("id") != reminder_id
        ]
        if len(self.config.reminders) == before:
            return False
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()
        return True

    def mark_reminder_done(self, reminder_id: str) -> bool:
        reminder = self._wellness.find(reminder_id)
        if reminder is None:
            return False
        self._wellness.mark_done(reminder)
        self._save_wellness()
        return True

    def snooze_reminder(self, reminder_id: str, minutes: int | None = None) -> bool:
        reminder = self._wellness.find(reminder_id)
        if reminder is None:
            return False
        self._wellness.snooze(reminder, minutes)
        self._save_wellness()
        return True

    def set_reminders_enabled(self, enabled: bool) -> None:
        self.config.reminders_enabled = bool(enabled)
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()
        if enabled:
            self.window.say("I'll remind you to eat and drink! 🍎💧", 4.0)

    def set_reminder_sound(self, enabled: bool) -> None:
        if enabled and not self.backend.supports(Capability.AUDIO):
            self._show_unavailable(Capability.AUDIO)
            return
        self.config.reminder_sound = bool(enabled)
        self.tray.refresh()
        self._schedule_save()

    def set_meal_time(self, key: str, value: str) -> None:
        field = f"{key}_time"
        if not hasattr(self.config, field):
            return
        setattr(self.config, field, value)
        self.config.normalize()
        for reminder in self.config.reminders:
            if isinstance(reminder, dict) and reminder.get("id") == key:
                reminder["time"] = getattr(self.config, field)
        self._rebuild_wellness()
        self._schedule_save()

    def set_meal_enabled(self, key: str, enabled: bool) -> None:
        field = f"{key}_enabled"
        if not hasattr(self.config, field):
            return
        setattr(self.config, field, bool(enabled))
        for reminder in self.config.reminders:
            if isinstance(reminder, dict) and reminder.get("id") == key:
                reminder["enabled"] = bool(enabled)
        self._rebuild_wellness()
        self._schedule_save()

    def set_water_interval(self, minutes: int) -> None:
        self.config.water_interval_minutes = int(minutes)
        self.config.normalize()
        for reminder in self.config.reminders:
            if isinstance(reminder, dict) and reminder.get("id") == "water":
                reminder["interval_minutes"] = self.config.water_interval_minutes
        self._rebuild_wellness()
        self._schedule_save()

    def set_break_interval(self, minutes: int) -> None:
        self.config.break_interval_minutes = int(minutes)
        self.config.normalize()
        for reminder in self.config.reminders:
            if isinstance(reminder, dict) and reminder.get("id") == "break":
                reminder["interval_minutes"] = self.config.break_interval_minutes
        self._rebuild_wellness()
        self._schedule_save()

    # ---------------------------------------------------------------- actions
    @staticmethod
    def _spawn_process(parts: list[str]) -> bool:
        if not parts:
            return False
        subprocess.Popen(parts, start_new_session=True)  # noqa: S603
        return True

    def _build_actions(self) -> ActionRegistry:
        plugin_builtins = {
            action_id: callback
            for action_id, (_name, callback) in self._plugin_actions.items()
        }
        return ActionRegistry.from_config(
            self.config.actions,
            builtins={
                "dance": self.dance,
                "show-buddy": self.show_buddy,
                "open-settings": self.open_settings,
                "start-focus": self.focus_start,
                "stop-focus": self.focus_stop,
                **plugin_builtins,
            },
            open_url=lambda target: QDesktopServices.openUrl(QUrl(target)),
            launch_application=self._spawn_process,
            run_command=self._spawn_process,
        )

    def _rebuild_actions(self) -> None:
        self._actions = self._build_actions()

    def save_action_definition(
        self, data: dict[str, object], existing_id: str | None = None
    ) -> str:
        candidate = dict(data)
        existing_ids = {
            str(item.get("id", ""))
            for item in self.config.actions
            if isinstance(item, dict) and str(item.get("id", "")) != existing_id
        }
        candidate["id"] = existing_id or self._unique_config_id(
            str(candidate.get("name", "Action")), existing_ids
        )
        action = ActionDefinition.from_dict(candidate)
        if action is None:
            raise ValueError("The action definition is incomplete or invalid.")
        updated: list[dict[str, object]] = []
        replaced = False
        for item in self.config.actions:
            if isinstance(item, dict) and item.get("id") == existing_id:
                updated.append(action.to_dict())
                replaced = True
            elif isinstance(item, dict):
                updated.append(item)
        if not replaced:
            updated.append(action.to_dict())
        self.config.actions = updated
        self._rebuild_actions()
        self.tray.refresh()
        self._schedule_save()
        return action.id

    def remove_action(self, action_id: str) -> bool:
        before = len(self.config.actions)
        self.config.actions = [
            item
            for item in self.config.actions
            if not isinstance(item, dict) or item.get("id") != action_id
        ]
        if len(self.config.actions) == before:
            return False
        for reminder in self.config.reminders:
            if isinstance(reminder, dict) and reminder.get("action_id") == action_id:
                reminder.pop("action_id", None)
        self._rebuild_actions()
        self._rebuild_wellness()
        self.tray.refresh()
        self._schedule_save()
        return True

    def run_action(self, action_id: str, announce: bool = True):  # noqa: ANN201
        result = self._actions.execute(action_id)
        if announce:
            self.window.say(result.message, 4.0)
        self._emit_plugin_event(
            "action.executed", action_id=action_id, ok=result.ok, message=result.message
        )
        return result

    def actions_summary(self) -> str:
        builtins = ("dance", "show-buddy", "open-settings", "start-focus", "stop-focus")
        lines = [f"{action_id}  builtin" for action_id in builtins]
        lines.extend(
            f"{action_id}  plugin  {name}"
            for action_id, (name, _callback) in sorted(self._plugin_actions.items())
        )
        lines.extend(
            f"{action.id}  {action.type.value}  {action.name}"
            for action in self._actions.list_actions()
        )
        return "Available actions:\n" + "\n".join(lines)

    # ------------------------------------------------------------------- focus
    def _rebuild_focus(self) -> None:
        self._focus.set_settings(FocusSettings.from_config(self.config))
        self._sync_focus_ui()

    def _save_focus(self) -> None:
        try:
            self._focus.state.save(self._focus_path)
        except OSError as exc:
            log.warning("Could not save focus state: %s", exc)

    def _sync_focus_ui(self) -> None:
        self.window.set_focus_state(
            self._focus.state.kind,
            self._focus.state.status,
            self._focus.remaining_seconds(),
        )
        self.tray.refresh()
        if self._prefs is not None:
            self._prefs.refresh_focus_status()

    def set_focus_setting(self, key: str, value: int | bool) -> None:
        if key not in {
            "focus_minutes",
            "short_break_minutes",
            "long_break_minutes",
            "long_break_every",
            "focus_respect_quiet_hours",
            "focus_suppress_fullscreen",
        }:
            return
        setattr(self.config, key, value)
        self.config.normalize()
        self._rebuild_focus()
        self._schedule_save()

    def focus_start(self, kind: SessionKind | str | None = None) -> bool:
        if isinstance(kind, str):
            try:
                kind = SessionKind(kind.replace("-", "_"))
            except ValueError:
                return False
        changed = self._focus.start(kind)
        if not changed:
            return False
        self._save_focus()
        self._sync_focus_ui()
        label = kind_label(self._focus.state.kind)
        self.window.focus_started(self._focus.state.kind, f"{label} started")
        self._emit_plugin_event(
            "focus.changed",
            status=self._focus.state.status.value,
            kind=self._focus.state.kind.value,
        )
        return True

    def focus_pause(self) -> bool:
        changed = self._focus.pause()
        if changed:
            self._save_focus()
            self._sync_focus_ui()
            self.window.say("Focus timer paused", 3.0)
            self._emit_plugin_event(
                "focus.changed",
                status=self._focus.state.status.value,
                kind=self._focus.state.kind.value,
            )
        return changed

    def focus_resume(self) -> bool:
        changed = self._focus.resume()
        if changed:
            self._save_focus()
            self._sync_focus_ui()
            self.window.say("Back to it!", 3.0)
            self._emit_plugin_event(
                "focus.changed",
                status=self._focus.state.status.value,
                kind=self._focus.state.kind.value,
            )
        return changed

    def focus_skip(self) -> bool:
        event = self._focus.skip()
        if event is None:
            return False
        self._save_focus()
        self._sync_focus_ui()
        self.window.say(f"Next: {kind_label(event.next_kind)}", 3.0)
        self._emit_plugin_event(
            "focus.changed",
            status=self._focus.state.status.value,
            kind=self._focus.state.kind.value,
        )
        return True

    def focus_stop(self) -> bool:
        changed = self._focus.stop()
        if changed:
            self._save_focus()
            self._sync_focus_ui()
            self.window.say("Focus cycle stopped", 3.0)
            self._emit_plugin_event(
                "focus.changed",
                status=self._focus.state.status.value,
                kind=self._focus.state.kind.value,
            )
        return changed

    def _check_focus(self) -> None:
        events = self._focus.tick()
        remaining = self._focus.remaining_seconds()
        self.window.set_focus_state(
            self._focus.state.kind, self._focus.state.status, remaining
        )
        if not events:
            if self._prefs is not None:
                self._prefs.refresh_focus_status()
            return
        self._save_focus()
        for event in events:
            self._handle_focus_event(event)
        self._sync_focus_ui()

    def _handle_focus_event(self, event: FocusEvent) -> None:
        if event.type is not FocusEventType.COMPLETED:
            return
        self._emit_plugin_event(
            "focus.completed",
            kind=event.kind.value,
            next_kind=event.next_kind.value,
            at=event.at.isoformat(),
        )
        if event.kind is SessionKind.FOCUS:
            message = f"Focus complete — next: {kind_label(event.next_kind)}"
            sound_kind = "break"
        else:
            message = "Break complete — ready to focus"
            sound_kind = "default"
        if not self._focus_attention_allowed(event.at):
            log.info("Focus completion notification suppressed: %s", message)
            return
        self.window.focus_completed(event.kind, event.next_kind, message)
        self.tray.show_message("Desktop Buddy — Focus", message)
        if not self.config.silent_mode and self.backend.supports(Capability.AUDIO):
            self.backend.play_audio(chime_path(sound_kind, self._state_dir))

    def _focus_attention_allowed(self, now: datetime) -> bool:
        if self.config.do_not_disturb:
            return False
        if self.config.focus_respect_quiet_hours and not self._wellness.active_hours_ok(
            now
        ):
            return False
        if self.config.calendar_meeting_quiet and getattr(
            self, "_meeting_active", False
        ):
            return False
        context = getattr(self, "_context", None)
        if (
            self.config.context_enabled
            and context is not None
            and not context.attention_allowed(
                suppress_fullscreen=self.config.focus_suppress_fullscreen,
                suppress_meetings=self.config.calendar_meeting_quiet,
            )
        ):
            return False
        if (
            not self.config.context_enabled
            and self.config.focus_suppress_fullscreen
            and self.backend.supports(Capability.ACTIVE_WINDOW)
        ):
            probe = self.backend.create_active_window_probe()
            try:
                info = probe.active_window() if probe.available else None
                if info is not None and info.fullscreen:
                    return False
            finally:
                probe.close()
        return True

    def _context_attention_allowed(self, urgent: bool = False) -> bool:
        if urgent:
            return True
        if self.config.calendar_meeting_quiet and getattr(
            self, "_meeting_active", False
        ):
            return False
        if not self.config.context_enabled:
            return True
        context = getattr(self, "_context", None)
        if context is None:
            return True
        return context.attention_allowed(
            suppress_fullscreen=self.config.context_suppress_fullscreen,
            suppress_meetings=self.config.calendar_meeting_quiet,
        )

    def focus_summary(self) -> str:
        state = self._focus.state
        label = kind_label(state.kind)
        remaining = format_duration(self._focus.remaining_seconds())
        status = state.status.value
        today_minutes = self._focus.today_seconds() // 60
        return (
            f"{status}: {label} {remaining}\n"
            f"Today: {today_minutes} focused minutes · "
            f"{state.completed_focus_sessions} completed sessions"
        )

    def focus_history(self, days: int = 7) -> list[tuple[date, int]]:
        return self._focus.recent_history(days)

    def set_autostart(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled and not self.backend.supports(Capability.AUTOSTART):
            self._show_unavailable(Capability.AUTOSTART)
            return
        try:
            self.backend.set_autostart(enabled)
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
        return self.backend.autostart_enabled()

    def _show_unavailable(self, capability: Capability) -> None:
        info = self.backend.capability(capability)
        message = info.reason or f"{capability.value} is unavailable."
        log.info("Unavailable capability %s: %s", capability.value, message)
        self.tray.show_message("Desktop Buddy", message)

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

    def open_onboarding(self) -> None:
        dialog = OnboardingDialog(self)
        dialog.exec()
        self.save_config()
        self._greet()

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
                f"session: {self.backend.session_type()}</p>"
            ),
        )

    def quit(self, *_args: object) -> None:
        manager = getattr(self, "_plugins", None)
        if manager is not None:
            manager.shutdown()
        self.save_config()
        self._save_wellness()
        self._save_focus()
        if self.tray.icon is not None:
            self.tray.icon.hide()
        self.app.quit()

    # -------------------------------------------------------------------- ipc
    def _start_ipc(self) -> LocalCommandServer:
        return LocalCommandServer(self.backend.server_name(), self.handle_command, self)

    def handle_command(self, command: str) -> str | None:
        if not command:
            return None
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return f"invalid command: {exc}"
        if not parts:
            return None
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
            action = parts[1]
            if action in {"status", "list"}:
                return self.reminders_summary(6)
            if action == "history":
                return self.reminder_history_summary()
            if action in ("on", "off"):
                self.set_reminders_enabled(action == "on")
                return f"reminders {action}"
            if action == "add" and len(parts) >= 4:
                try:
                    reminder_id = self.add_reminder(parts[2], parts[3])
                except ValueError as exc:
                    return f"could not add reminder: {exc}"
                return f"reminder added: {reminder_id}"
            if action == "remove" and len(parts) >= 3:
                return (
                    f"reminder removed: {parts[2]}"
                    if self.remove_reminder(parts[2])
                    else f"unknown reminder: {parts[2]}"
                )
            if action == "done" and len(parts) >= 3:
                return (
                    f"reminder done: {parts[2]}"
                    if self.mark_reminder_done(parts[2])
                    else f"unknown reminder: {parts[2]}"
                )
            if action == "snooze" and len(parts) >= 3:
                try:
                    minutes = int(parts[3]) if len(parts) >= 4 else None
                except ValueError:
                    return "snooze minutes must be a number"
                return (
                    f"reminder snoozed: {parts[2]}"
                    if self.snooze_reminder(parts[2], minutes)
                    else f"unknown reminder: {parts[2]}"
                )
            return (
                "usage: reminders on|off|status|list|history|"
                "add TITLE SCHEDULE|remove ID|done ID|snooze ID [MINUTES]"
            )
        elif verb == "actions" and len(parts) > 1:
            if parts[1] == "list":
                return self.actions_summary()
            if parts[1] == "run" and len(parts) >= 3:
                return self.run_action(parts[2], announce=False).message
            return "usage: actions list|run ID"
        elif verb == "plugins" and len(parts) > 1:
            action = parts[1]
            if action == "list":
                return self.plugins_summary()
            if action == "info" and len(parts) >= 3:
                return self.plugin_info(parts[2])
            if action == "grant" and len(parts) >= 3:
                return (
                    f"plugin permissions updated: {parts[2]}"
                    if self.set_plugin_permissions(parts[2], parts[3:])
                    else f"could not update plugin permissions: {parts[2]}"
                )
            if action == "enable" and len(parts) >= 3:
                permissions = parts[3:] or None
                if self.set_plugin_enabled(parts[2], True, permissions):
                    return f"plugin enabled: {parts[2]}"
                return self.plugin_info(parts[2])
            if action == "disable" and len(parts) >= 3:
                return (
                    f"plugin disabled: {parts[2]}"
                    if self.set_plugin_enabled(parts[2], False)
                    else f"unknown plugin: {parts[2]}"
                )
            return "usage: plugins list|info ID|enable ID [PERMISSIONS...]|disable ID|grant ID [PERMISSIONS...]"
        elif verb == "focus" and len(parts) > 1:
            action = parts[1]
            if action == "status":
                return self.focus_summary()
            if action == "start":
                kind = parts[2] if len(parts) > 2 else None
                return "focus started" if self.focus_start(kind) else "focus unchanged"
            actions = {
                "pause": self.focus_pause,
                "resume": self.focus_resume,
                "skip": self.focus_skip,
                "stop": self.focus_stop,
            }
            handler = actions.get(action)
            if handler is None:
                return "usage: focus start [focus|short-break|long-break]|pause|resume|skip|stop|status"
            replies = {
                "pause": "focus paused",
                "resume": "focus resumed",
                "skip": "focus skipped",
                "stop": "focus stopped",
            }
            return replies[action] if handler() else "focus unchanged"
        elif verb == "media" and len(parts) > 1:
            return self.media_command(parts[1])
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
            f" focus={self._focus.state.status.value}:{self._focus.state.kind.value}"
            f" plugins={sum(record.status is PluginStatus.ACTIVE for record in self._plugins.records.values())}"
            f" context={'on' if self.config.context_enabled else 'off'}"
            f" fullscreen={'yes' if self._context.snapshot.fullscreen else 'no'}"
            f" profile={self._context.snapshot.profile_id or '-'}"
            f" network={self._context.snapshot.network.value}"
            f" meeting={'yes' if self._meeting_active else 'no'}"
        )

    def _greet(self) -> None:
        self.window.say(f"Hi, I'm {self.config.name}! Drag me or right-click me.", 7.0)
        self.tray.show_message(
            "Desktop Buddy", f"{self.config.name} has moved onto your desktop!"
        )


def diagnose() -> int:
    """Print a support-friendly environment report."""

    def line(label: str, value: object) -> None:
        print(f"  {label:<16}: {value}", flush=True)

    print("Desktop Buddy diagnostics", flush=True)
    backend = get_backend()
    backend.prepare_process()
    line("version", __version__)
    line("python", f"{sys.version.split()[0]} ({sys.executable})")
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        line("PyQt / Qt", f"{PYQT_VERSION_STR} / {QT_VERSION_STR}")
    except Exception as exc:  # noqa: BLE001
        line("PyQt / Qt", f"unavailable ({exc})")
    for label, value in backend.diagnostics().items():
        line(label, value)
    for capability, info in backend.capabilities().items():
        value = "available" if info.available else f"unavailable ({info.reason})"
        line(f"cap:{capability.value}", value)
    line("config", CONFIG_PATH)
    line("log", LOG_PATH)
    line("plugin API", PLUGIN_API_VERSION)
    line("plugin directory", backend.paths().config_dir / "plugins")
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
    if backend.session_type() == "wayland":
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
    remind = sub.add_parser("remind", help="fire a reminder now")
    remind.add_argument("value", help="reminder ID")
    reminders = sub.add_parser("reminders", help="manage reminders")
    reminders.add_argument(
        "value",
        choices=(
            "on",
            "off",
            "status",
            "list",
            "history",
            "add",
            "remove",
            "done",
            "snooze",
        ),
    )
    reminders.add_argument("title", nargs="?", help="title or reminder ID")
    reminders.add_argument(
        "schedule", nargs="?", help="schedule phrase or snooze minutes"
    )
    actions = sub.add_parser("actions", help="list or run quick actions")
    actions.add_argument("action", choices=("list", "run"))
    actions.add_argument("action_id", nargs="?")
    plugins = sub.add_parser("plugins", help="manage optional plugins")
    plugins.add_argument(
        "action", choices=("list", "info", "enable", "disable", "grant")
    )
    plugins.add_argument("plugin_id", nargs="?")
    plugins.add_argument(
        "permissions",
        nargs="*",
        choices=tuple(permission.value for permission in PluginPermission),
    )
    focus = sub.add_parser("focus", help="control the focus timer")
    focus.add_argument(
        "action", choices=("start", "pause", "resume", "skip", "stop", "status")
    )
    media = sub.add_parser("media", help="control an opt-in MPRIS media player")
    media.add_argument(
        "action", choices=("status", "play-pause", "next", "previous", "stop")
    )
    focus.add_argument(
        "kind",
        nargs="?",
        choices=("focus", "short-break", "long-break"),
        help="session type when starting",
    )
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
    backend = get_backend()
    backend.prepare_process()

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
            if args.value in {"status", "list", "history"}:
                reply = request_reply(f"reminders {args.value}")
                if reply:
                    print(reply)
                    return 0
                print("Desktop Buddy is not running.", file=sys.stderr)
                return 1
            if args.value in {"on", "off"} and send_command(f"reminders {args.value}"):
                print(f"Reminders {args.value}")
                return 0
            if args.value in {"on", "off"}:
                config = Config.load()
                config.reminders_enabled = args.value == "on"
                config.save()
                print(f"Reminders {args.value} (applies next time it starts)")
                return 0
            if not args.title:
                parser.error(f"reminders {args.value} requires a reminder ID or title")
            if args.value == "add":
                if not args.schedule:
                    parser.error("reminders add requires TITLE and SCHEDULE")
                command = "reminders add " + " ".join(
                    (shlex.quote(args.title), shlex.quote(args.schedule))
                )
            elif args.value == "snooze":
                command = f"reminders snooze {shlex.quote(args.title)}"
                if args.schedule:
                    command += f" {shlex.quote(args.schedule)}"
            else:
                command = f"reminders {args.value} {shlex.quote(args.title)}"
            reply = request_reply(command)
            if reply:
                print(reply)
                return (
                    0
                    if not reply.startswith(("unknown", "could not", "invalid"))
                    else 1
                )
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
        if args.command == "actions":
            if args.action == "run" and not args.action_id:
                parser.error("actions run requires an action ID")
            command = f"actions {args.action}"
            if args.action_id:
                command += f" {shlex.quote(args.action_id)}"
            reply = request_reply(command)
            if reply:
                print(reply)
                return (
                    0
                    if not reply.startswith(
                        ("Unknown", "Command action", "Action failed", "Could not")
                    )
                    else 1
                )
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
        if args.command == "plugins":
            if args.action != "list" and not args.plugin_id:
                parser.error(f"plugins {args.action} requires a plugin ID")
            command = f"plugins {args.action}"
            if args.plugin_id:
                command += f" {shlex.quote(args.plugin_id)}"
            if args.permissions:
                command += " " + " ".join(
                    shlex.quote(permission) for permission in args.permissions
                )
            reply = request_reply(command)
            if reply:
                print(reply)
                return (
                    1
                    if reply.startswith(("Unknown", "unknown", "could not"))
                    or "Status: blocked" in reply
                    or "Status: incompatible" in reply
                    or "Status: failed" in reply
                    else 0
                )
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
        if args.command == "focus":
            command = f"focus {args.action}"
            if args.kind:
                command += f" {args.kind}"
            reply = request_reply(command)
            if reply:
                print(reply)
                return 0
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
        if args.command == "media":
            reply = request_reply(f"media {args.action}")
            if reply:
                print(reply)
                return (
                    0
                    if not reply.startswith(("media controls", "no compatible"))
                    else 1
                )
            print("Desktop Buddy is not running.", file=sys.stderr)
            return 1
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
                if not backend.supports(Capability.AUTOSTART):
                    print(
                        f"unavailable: {backend.capability(Capability.AUTOSTART).reason}"
                    )
                    return 1
                print("enabled" if backend.autostart_enabled() else "disabled")
                return 0
            enabled = args.value == "on"
            if enabled and not backend.supports(Capability.AUTOSTART):
                print(backend.capability(Capability.AUTOSTART).reason, file=sys.stderr)
                return 1
            if send_command(f"autostart {args.value}"):
                print(f"Autostart {'enabled' if enabled else 'disabled'}")
                return 0
            try:
                backend.set_autostart(enabled)
            except OSError as exc:
                print(f"Could not update autostart: {exc}", file=sys.stderr)
                return 1
            print(f"Autostart {'enabled' if enabled else 'disabled'}")
            return 0
        if args.command == "click-through":
            enabled = args.value == "on"
            if enabled and not backend.supports(Capability.CLICK_THROUGH):
                print(
                    backend.capability(Capability.CLICK_THROUGH).reason,
                    file=sys.stderr,
                )
                return 1
            if send_command(f"click-through {args.value}"):
                print(f"Click-through {'enabled' if enabled else 'disabled'}")
                return 0
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
    icon_path = backend.icon_path()
    if icon_path.is_file():
        icon = QIcon(str(icon_path))
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
    controller = Controller(
        app, config, first_run=not CONFIG_PATH.exists(), backend=backend
    )

    def _quit(*_args: object) -> None:
        controller.quit()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
