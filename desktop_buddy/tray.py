"""System tray icon and the shared right-click menu."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction, QActionGroup, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .character import Palette, icon_pixmap
from .config import SPECIES, THEMES
from .platforms.base import Capability

log = logging.getLogger(__name__)

SPEEDS: tuple[tuple[str, float], ...] = (
    ("Slow", 0.7),
    ("Normal", 1.0),
    ("Fast", 1.5),
    ("Zoomies", 2.2),
)

SIZES: tuple[tuple[str, float], ...] = (
    ("Small", 0.6),
    ("Normal", 0.8),
    ("Large", 1.1),
    ("Extra large", 1.4),
)


class BuddyTray(QObject):
    """Owns the tray icon (when available) and the context menu."""

    def __init__(self, controller) -> None:  # noqa: ANN001 - duck-typed controller
        super().__init__(controller)
        self.controller = controller
        self.menu = QMenu()
        self._speed_actions: list[tuple[QAction, float]] = []
        self._size_actions: list[tuple[QAction, float]] = []
        self._theme_actions: list[tuple[QAction, str]] = []
        self._species_actions: list[tuple[QAction, str]] = []
        self._build_menu()

        self.icon: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon = QSystemTrayIcon(self._make_icon(), self)
            self.icon.setToolTip("Desktop Buddy")
            self.icon.setContextMenu(self.menu)
            self.icon.activated.connect(self._on_activated)
        else:
            log.info("System tray is unavailable; right-click the buddy for the menu.")
        self.refresh()

    # ------------------------------------------------------------------- build
    def _make_icon(self) -> QIcon:
        config = self.controller.config
        palette = Palette.from_colors(config.theme_colors())
        return QIcon(icon_pixmap(config.species, palette, 128, dpr=2.0))

    def _build_menu(self) -> None:
        controller = self.controller
        menu = self.menu

        self.act_visibility = menu.addAction("Hide", controller.toggle_visibility)
        self.act_pause = menu.addAction("Pause", controller.toggle_paused)
        self.act_pause.setCheckable(True)
        menu.addSeparator()

        self.act_top = menu.addAction("Always on top", controller.set_always_on_top)
        self.act_top.setCheckable(True)
        self.act_click = menu.addAction("Click-through", controller.set_click_through)
        self.act_click.setCheckable(True)
        self.act_battery = menu.addAction(
            "Reduce motion on battery", controller.set_reduce_on_battery
        )
        self.act_battery.setCheckable(True)
        self.act_playful = menu.addAction("Playful with cursor", controller.set_playful)
        self.act_playful.setCheckable(True)
        self.act_sleep = menu.addAction("Sleep when idle", controller.set_can_sleep)
        self.act_sleep.setCheckable(True)
        self.act_perch = menu.addAction(
            "Perch on browser/terminal", controller.set_perch_on_windows
        )
        self.act_perch.setCheckable(True)
        menu.addAction("Dance!", controller.dance)

        reminders_menu = menu.addMenu("Reminders")
        self.act_reminders = reminders_menu.addAction(
            "Wellness reminders", controller.set_reminders_enabled
        )
        self.act_reminders.setCheckable(True)
        self.act_chime = reminders_menu.addAction(
            "Gentle chime", controller.set_reminder_sound
        )
        self.act_chime.setCheckable(True)
        reminders_menu.addSeparator()
        reminders_menu.addAction("Water now", lambda: controller.remind_now("water"))
        reminders_menu.addAction("Stretch now", lambda: controller.remind_now("break"))
        reminders_menu.addAction("Upcoming…", controller.show_reminders)

        speed_menu = menu.addMenu("Speed")
        speed_group = QActionGroup(speed_menu)
        speed_group.setExclusive(True)
        for label, value in SPEEDS:
            action = speed_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, v=value: controller.set_speed(v))
            speed_group.addAction(action)
            self._speed_actions.append((action, value))

        size_menu = menu.addMenu("Size")
        size_group = QActionGroup(size_menu)
        size_group.setExclusive(True)
        for label, value in SIZES:
            action = size_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, v=value: controller.set_scale(v))
            size_group.addAction(action)
            self._size_actions.append((action, value))

        theme_menu = menu.addMenu("Theme")
        theme_group = QActionGroup(theme_menu)
        theme_group.setExclusive(True)
        for key, colors in THEMES.items():
            action = theme_menu.addAction(colors["label"])
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, k=key: controller.set_theme(k))
            theme_group.addAction(action)
            self._theme_actions.append((action, key))

        character_menu = menu.addMenu("Character")
        character_group = QActionGroup(character_menu)
        character_group.setExclusive(True)
        for key, info in SPECIES.items():
            action = character_menu.addAction(info["label"])
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, k=key: controller.set_species(k))
            character_group.addAction(action)
            self._species_actions.append((action, key))

        menu.addSeparator()
        self.act_autostart = menu.addAction("Start at login", controller.set_autostart)
        self.act_autostart.setCheckable(True)
        menu.addAction("Preferences…", controller.open_settings)
        menu.addAction("About", controller.show_about)
        menu.addSeparator()
        menu.addAction("Quit", controller.quit)
        self._apply_capabilities()

    def _apply_capabilities(self) -> None:
        controls = (
            (self.act_top, Capability.ALWAYS_ON_TOP),
            (self.act_click, Capability.CLICK_THROUGH),
            (self.act_battery, Capability.BATTERY),
            (self.act_perch, Capability.ACTIVE_WINDOW),
            (self.act_chime, Capability.AUDIO),
            (self.act_autostart, Capability.AUTOSTART),
        )
        for action, capability in controls:
            info = self.controller.backend.capability(capability)
            action.setEnabled(info.available)
            action.setToolTip(info.reason)

    # ----------------------------------------------------------------- refresh
    def refresh(self) -> None:
        config = self.controller.config
        paused = self.controller.window.is_paused
        self.act_pause.setChecked(paused)
        self.act_pause.setText("Resume" if paused else "Pause")
        self.act_visibility.setText(
            "Hide" if self.controller.window.isVisible() else "Show"
        )
        self.act_top.setChecked(config.always_on_top)
        self.act_click.setChecked(config.click_through)
        self.act_battery.setChecked(config.reduce_on_battery)
        self.act_playful.setChecked(config.playful)
        self.act_sleep.setChecked(config.can_sleep)
        self.act_perch.setChecked(config.perch_on_windows)
        self.act_reminders.setChecked(config.reminders_enabled)
        self.act_chime.setChecked(config.reminder_sound)
        self.act_autostart.setChecked(self.controller.autostart_active())
        for action, value in self._speed_actions:
            action.setChecked(abs(config.speed - value) < 0.01)
        for action, value in self._size_actions:
            action.setChecked(abs(config.scale - value) < 0.01)
        for action, key in self._theme_actions:
            action.setChecked(config.theme == key)
        for action, key in self._species_actions:
            action.setChecked(config.species == key)

    def show_message(self, title: str, message: str) -> None:
        if self.icon is not None and self.icon.isVisible():
            self.icon.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, 4000
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.controller.toggle_visibility()
