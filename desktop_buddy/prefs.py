"""Preferences dialog with a live character preview."""

from __future__ import annotations

import time

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .behavior import Brain, State, World
from .character import Character, Palette
from .config import THEMES


class CharacterPreview(QWidget):
    """Small animated preview that mirrors the effect of the current settings."""

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.setMinimumHeight(170)
        self._brain = Brain(world=World(left=-400.0, right=400.0, ground=0.0))
        self._brain.playful = False
        self._brain.can_sleep = False
        self._character = Character(
            Palette.from_colors(controller.config.theme_colors())
        )
        self._palette = Palette.from_colors(controller.config.theme_colors())
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def refresh(self) -> None:
        self._palette = Palette.from_colors(self.controller.config.theme_colors())
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
        layout.addLayout(form)

        self.check_top = QCheckBox("Always on top")
        self.check_click = QCheckBox("Click-through (use tray/CLI to undo)")
        self.check_battery = QCheckBox("Reduce motion when on battery")
        self.check_playful = QCheckBox("Playful with the cursor")
        self.check_sleep = QCheckBox("Sleep when idle")
        for box in (
            self.check_top,
            self.check_click,
            self.check_battery,
            self.check_playful,
            self.check_sleep,
        ):
            layout.addWidget(box)
        self.check_top.toggled.connect(controller.set_always_on_top)
        self.check_click.toggled.connect(controller.set_click_through)
        self.check_battery.toggled.connect(controller.set_reduce_on_battery)
        self.check_playful.toggled.connect(controller.set_playful)
        self.check_sleep.toggled.connect(controller.set_can_sleep)

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
        self.check_top.setChecked(config.always_on_top)
        self.check_click.setChecked(config.click_through)
        self.check_battery.setChecked(config.reduce_on_battery)
        self.check_playful.setChecked(config.playful)
        self.check_sleep.setChecked(config.can_sleep)
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
