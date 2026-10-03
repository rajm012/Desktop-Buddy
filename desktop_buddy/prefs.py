"""Preferences dialog with a live character preview."""

from __future__ import annotations

import time

from PyQt6.QtCore import QRectF, QTime, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .behavior import Brain, State, World
from .character import Palette, make_character
from .config import SPECIES, THEMES


class CharacterPreview(QWidget):
    """Small animated preview that mirrors the effect of the current settings."""

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.setMinimumHeight(170)
        self._brain = Brain(world=World(left=-400.0, right=400.0, ground=0.0))
        self._brain.playful = False
        self._brain.can_sleep = False
        self._palette = Palette.from_colors(controller.config.theme_colors())
        self._species = controller.config.species
        self._character = make_character(self._species, self._palette)
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def refresh(self) -> None:
        self._palette = Palette.from_colors(self.controller.config.theme_colors())
        if self._species != self.controller.config.species:
            self._species = self.controller.config.species
            self._character = make_character(self._species, self._palette)
        self._character.set_palette(self._palette)
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        self._brain.step(dt)
        # Keep the preview standing in place: show idle cosmetics only.
        self._brain.state = State.IDLE
        self._brain.y = self._brain.world.ground
        self._brain.vy = 0.0
        self._brain.vx = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor("#d0d3da"), 1.0))
        painter.setBrush(QColor("#f7f8fb"))
        painter.drawRoundedRect(rect, 10.0, 10.0)
        scale = max(0.5, min(1.2, self.controller.config.scale))
        width = int(150 * scale * 1.6)
        height = min(self.height() - 16, int(260 * scale * 0.62))
        painter.translate((self.width() - width) / 2.0, self.height() - 8.0 - height)
        self._character.paint(painter, self._brain, width, height)
        painter.end()


class PreferencesDialog(QDialog):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self._snapshot = controller.config.to_dict()
        self.setWindowTitle("Desktop Buddy Preferences")
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        self.preview = CharacterPreview(controller, self)
        layout.addWidget(self.preview)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = QLineEdit(controller.config.name)
        self.name_edit.setMaxLength(24)
        self.name_edit.textEdited.connect(self._on_name)
        form.addRow("Name", self.name_edit)

        self.scale_slider, self.scale_label, scale_row = self._slider_row(
            50, 180, int(controller.config.scale * 100), "%"
        )
        self.scale_slider.valueChanged.connect(self._on_scale)
        form.addRow("Size", scale_row)

        self.speed_slider, self.speed_label, speed_row = self._slider_row(
            40, 250, int(controller.config.speed * 100), "%"
        )
        self.speed_slider.valueChanged.connect(self._on_speed)
        form.addRow("Speed", speed_row)

        self.fps_slider, self.fps_label, fps_row = self._slider_row(
            15, 60, int(controller.config.fps), " fps"
        )
        self.fps_slider.valueChanged.connect(self._on_fps)
        form.addRow("Frame rate", fps_row)

        self.sleep_slider, self.sleep_label, sleep_row = self._slider_row(
            30, 600, int(controller.config.sleep_after), " s"
        )
        self.sleep_slider.valueChanged.connect(self._on_sleep)
        form.addRow("Sleep after idle", sleep_row)

        self.theme_combo = QComboBox()
        for key, colors in THEMES.items():
            self.theme_combo.addItem(colors["label"], userData=key)
        index = self.theme_combo.findData(controller.config.theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self.theme_combo.currentIndexChanged.connect(self._on_theme)
        form.addRow("Theme", self.theme_combo)

        self.species_combo = QComboBox()
        for key, info in SPECIES.items():
            self.species_combo.addItem(info["label"], userData=key)
        index = self.species_combo.findData(controller.config.species)
        if index >= 0:
            self.species_combo.setCurrentIndex(index)
        self.species_combo.currentIndexChanged.connect(self._on_species)
        form.addRow("Character", self.species_combo)
        layout.addLayout(form)

        self.check_top = QCheckBox("Always on top")
        self.check_click = QCheckBox("Click-through (use tray/CLI to undo)")
        self.check_battery = QCheckBox("Reduce motion when on battery")
        self.check_playful = QCheckBox("Playful with the cursor")
        self.check_sleep = QCheckBox("Sleep when idle")
        self.check_perch = QCheckBox("Perch on browser/terminal windows")
        for box in (
            self.check_top,
            self.check_click,
            self.check_battery,
            self.check_playful,
            self.check_sleep,
            self.check_perch,
        ):
            layout.addWidget(box)
        self.check_top.toggled.connect(controller.set_always_on_top)
        self.check_click.toggled.connect(controller.set_click_through)
        self.check_battery.toggled.connect(controller.set_reduce_on_battery)
        self.check_playful.toggled.connect(controller.set_playful)
        self.check_sleep.toggled.connect(controller.set_can_sleep)
        self.check_perch.toggled.connect(controller.set_perch_on_windows)

        reminders_group = QGroupBox("Wellness reminders")
        reminders_grid = QGridLayout(reminders_group)
        self.check_reminders = QCheckBox("Remind me to eat, drink and stretch")
        self.check_chime = QCheckBox("Gentle chime")
        reminders_grid.addWidget(self.check_reminders, 0, 0, 1, 3)
        reminders_grid.addWidget(self.check_chime, 1, 0, 1, 3)
        self.check_reminders.toggled.connect(self._on_reminders_enabled)
        self.check_chime.toggled.connect(self._on_reminder_sound)
        self.meal_widgets: dict[str, tuple[QCheckBox, QTimeEdit]] = {}
        meals = (
            ("breakfast", "Breakfast"),
            ("lunch", "Lunch"),
            ("snack", "Snack"),
            ("dinner", "Dinner"),
            ("winddown", "Wind down"),
        )
        for row, (key, label) in enumerate(meals, start=2):
            check = QCheckBox(label)
            edit = QTimeEdit()
            edit.setDisplayFormat("HH:mm")
            check.toggled.connect(
                lambda value, k=key: self._on_meal_enabled(k, value)
            )
            edit.timeChanged.connect(lambda value, k=key: self._on_meal_time(k, value))
            reminders_grid.addWidget(check, row, 0)
            reminders_grid.addWidget(edit, row, 1)
            self.meal_widgets[key] = (check, edit)

        self.water_slider, self.water_label, water_row = self._slider_row(
            10, 180, int(controller.config.water_interval_minutes), " min"
        )
        self.water_slider.valueChanged.connect(self._on_water_interval)
        self.break_slider, self.break_label, break_row = self._slider_row(
            20, 240, int(controller.config.break_interval_minutes), " min"
        )
        self.break_slider.valueChanged.connect(self._on_break_interval)
        row = len(meals) + 2
        reminders_grid.addWidget(QLabel("Water every"), row, 0)
        reminders_grid.addWidget(water_row, row, 1, 1, 2)
        reminders_grid.addWidget(QLabel("Stretch every"), row + 1, 0)
        reminders_grid.addWidget(break_row, row + 1, 1, 1, 2)
        layout.addWidget(reminders_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self._reject)
        buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._restore_defaults)
        layout.addWidget(buttons)

        self._loading = True
        self._load_from_config()
        self._loading = False

    # ------------------------------------------------------------------ helpers
    def _slider_row(
        self, low: int, high: int, value: int, suffix: str
    ) -> tuple[QSlider, QLabel, QWidget]:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        label = QLabel(f"{value}{suffix}")
        label.setMinimumWidth(52)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(label)
        slider.setProperty("suffix", suffix)
        return slider, label, row

    def _load_from_config(self) -> None:
        config = self.controller.config
        self.name_edit.setText(config.name)
        self.scale_slider.setValue(int(config.scale * 100))
        self.speed_slider.setValue(int(config.speed * 100))
        self.fps_slider.setValue(int(config.fps))
        self.sleep_slider.setValue(int(config.sleep_after))
        index = self.theme_combo.findData(config.theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        index = self.species_combo.findData(config.species)
        if index >= 0:
            self.species_combo.setCurrentIndex(index)
        self.check_top.setChecked(config.always_on_top)
        self.check_click.setChecked(config.click_through)
        self.check_battery.setChecked(config.reduce_on_battery)
        self.check_playful.setChecked(config.playful)
        self.check_sleep.setChecked(config.can_sleep)
        self.check_perch.setChecked(config.perch_on_windows)
        self.check_reminders.setChecked(config.reminders_enabled)
        self.check_chime.setChecked(config.reminder_sound)
        for key, (check, edit) in self.meal_widgets.items():
            check.setChecked(bool(getattr(config, f"{key}_enabled", True)))
            stored = getattr(config, f"{key}_time", "09:00")
            edit.setTime(QTime.fromString(stored, "HH:mm"))
        self.water_slider.setValue(int(config.water_interval_minutes))
        self.break_slider.setValue(int(config.break_interval_minutes))
        self.preview.refresh()

    # ------------------------------------------------------------------- events
    def _on_name(self, text: str) -> None:
        if not self._loading:
            self.controller.set_name(text)

    def _on_scale(self, value: int) -> None:
        self.scale_label.setText(f"{value}%")
        if not self._loading:
            self.controller.set_scale(value / 100.0)
            self.preview.refresh()

    def _on_speed(self, value: int) -> None:
        self.speed_label.setText(f"{value}%")
        if not self._loading:
            self.controller.set_speed(value / 100.0)

    def _on_fps(self, value: int) -> None:
        self.fps_label.setText(f"{value} fps")
        if not self._loading:
            self.controller.set_fps(value)

    def _on_sleep(self, value: int) -> None:
        self.sleep_label.setText(f"{value} s")
        if not self._loading:
            self.controller.set_sleep_after(float(value))

    def _on_theme(self, _index: int) -> None:
        if self._loading:
            return
        key = self.theme_combo.currentData()
        if key:
            self.controller.set_theme(str(key))
            self.preview.refresh()

    def _on_species(self, _index: int) -> None:
        if self._loading:
            return
        key = self.species_combo.currentData()
        if key:
            self.controller.set_species(str(key))
            self.preview.refresh()

    # ---------------------------------------------------------------- reminders
    def _on_reminders_enabled(self, value: bool) -> None:
        if not self._loading:
            self.controller.set_reminders_enabled(value)

    def _on_reminder_sound(self, value: bool) -> None:
        if not self._loading:
            self.controller.set_reminder_sound(value)

    def _on_meal_enabled(self, key: str, value: bool) -> None:
        if not self._loading:
            self.controller.set_meal_enabled(key, value)

    def _on_meal_time(self, key: str, value: QTime) -> None:
        if not self._loading:
            self.controller.set_meal_time(key, value.toString("HH:mm"))

    def _on_water_interval(self, value: int) -> None:
        self.water_label.setText(f"{value} min")
        if not self._loading:
            self.controller.set_water_interval(value)

    def _on_break_interval(self, value: int) -> None:
        self.break_label.setText(f"{value} min")
        if not self._loading:
            self.controller.set_break_interval(value)

    def _accept(self) -> None:
        self.controller.save_config()
        self.accept()

    def _reject(self) -> None:
        self.controller.apply_snapshot(self._snapshot)
        self.reject()

    def _restore_defaults(self) -> None:
        self.controller.reset_config()
        self._loading = True
        self._load_from_config()
        self._loading = False
        self.preview.refresh()
