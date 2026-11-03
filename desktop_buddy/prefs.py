"""Tabbed preferences and first-run onboarding."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, QTime, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .actions import ActionDefinition, ActionType, validate_target
from .behavior import Brain, State, World
from .character import Palette, make_character
from .config import SPECIES, THEMES, Config
from .focus import FocusStatus, SessionKind, format_duration, kind_label
from .platforms.base import Capability
from .wellness import Reminder, parse_reminder_phrase


class CharacterPreview(QWidget):
    """Animated theme and pose preview using the real character renderer."""

    STATES = (
        ("Idle", State.IDLE),
        ("Walk", State.WALK),
        ("Run", State.RUN),
        ("Jump / fall", State.AIR),
        ("Land", State.LAND),
        ("Dance", State.DANCE),
        ("Sleep", State.SLEEP),
    )

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.setMinimumHeight(190)
        self._brain = Brain(world=World(left=-400.0, right=400.0, ground=0.0))
        self._brain.playful = False
        self._brain.can_sleep = False
        self._preview_state = State.IDLE
        self._palette = Palette.from_colors(controller.config.theme_colors())
        self._species = controller.config.species
        self._character = make_character(self._species, self._palette)
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_state(self, state: State) -> None:
        self._preview_state = state
        self._brain.state_time = 0.0
        self.update()

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
        self._brain.anim_time += dt
        self._brain.state_time += dt
        self._brain.state = self._preview_state
        self._brain.y = -38.0 if self._preview_state is State.AIR else 0.0
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


class ReminderEditDialog(QDialog):
    """Editor for a general reminder and its locally parsed schedule."""

    def __init__(
        self, controller, raw: dict | None = None, parent: QWidget | None = None
    ) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.raw = dict(raw or {})
        reminder = Reminder.from_dict(self.raw) if raw else None
        self.setWindowTitle("Edit reminder" if raw else "Add reminder")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title_edit = QLineEdit(reminder.title if reminder else "")
        self.message_edit = QLineEdit(reminder.message if reminder else "")
        self.icon_edit = QLineEdit(reminder.icon if reminder else "⏰")
        self.icon_edit.setMaxLength(8)
        self.schedule_edit = QLineEdit(
            reminder.schedule().describe() if reminder else "in 20 minutes"
        )
        self.schedule_edit.setPlaceholderText(
            "in 20 minutes, daily at 9, weekdays at 09:00, every 2 hours"
        )
        self.snooze_spin = QSpinBox()
        self.snooze_spin.setRange(1, 1440)
        self.snooze_spin.setSuffix(" min")
        self.snooze_spin.setValue(reminder.snooze_minutes if reminder else 10)
        self.action_combo = QComboBox()
        self.action_combo.addItem("No action", None)
        for action_id, name in (
            ("dance", "Dance"),
            ("show-buddy", "Show buddy"),
            ("open-settings", "Open settings"),
            ("start-focus", "Start focus"),
            ("stop-focus", "Stop focus"),
        ):
            self.action_combo.addItem(f"{name} (built-in)", action_id)
        for item in controller.config.actions:
            action = ActionDefinition.from_dict(item)
            if action is not None:
                self.action_combo.addItem(action.name, action.id)
        if reminder and reminder.action_id:
            index = self.action_combo.findData(reminder.action_id)
            if index >= 0:
                self.action_combo.setCurrentIndex(index)
        form.addRow("Title", self.title_edit)
        form.addRow("Message", self.message_edit)
        form.addRow("Icon", self.icon_edit)
        form.addRow("Schedule", self.schedule_edit)
        form.addRow("Default snooze", self.snooze_spin)
        form.addRow("Action after Done", self.action_combo)
        layout.addLayout(form)
        hint = QLabel(
            "Schedules are interpreted locally. Supported examples: “in 20 minutes”, "
            "“tomorrow at 8 pm”, “daily at 9”, “weekdays at 09:00”, and “every 2 hours”."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(reminder.enabled if reminder else True)
        self.urgent_check = QCheckBox("Urgent (may interrupt outside active hours)")
        self.urgent_check.setChecked(reminder.urgent if reminder else False)
        layout.addWidget(self.enabled_check)
        layout.addWidget(self.urgent_check)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def definition(self) -> dict[str, object]:
        schedule = parse_reminder_phrase(self.schedule_edit.text())
        title = self.title_edit.text().strip()
        data: dict[str, object] = {
            "id": self.raw.get("id", "temporary"),
            "kind": self.raw.get("kind", "custom"),
            "title": title,
            "icon": self.icon_edit.text().strip() or "⏰",
            "message": self.message_edit.text().strip() or f"{title}!",
            "recurrence": schedule.recurrence.value,
            "enabled": self.enabled_check.isChecked(),
            "urgent": self.urgent_check.isChecked(),
            "snooze_minutes": self.snooze_spin.value(),
        }
        if schedule.time_of_day is not None:
            data["time"] = schedule.time_of_day.strftime("%H:%M")
        if schedule.one_time_at is not None:
            data["one_time_at"] = schedule.one_time_at.isoformat()
        if schedule.interval_minutes is not None:
            data["interval_minutes"] = schedule.interval_minutes
        if schedule.weekdays:
            data["weekdays"] = list(schedule.weekdays)
        if self.action_combo.currentData():
            data["action_id"] = str(self.action_combo.currentData())
        return data

    def _validate_and_accept(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "Missing title", "Enter a reminder title.")
            return
        try:
            self.definition()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid schedule", str(exc))
            return
        self.accept()


class ActionEditDialog(QDialog):
    """Editor that requires explicit confirmation before approving commands."""

    def __init__(self, raw: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.raw = dict(raw or {})
        action = ActionDefinition.from_dict(self.raw) if raw else None
        self.setWindowTitle("Edit quick action" if raw else "Add quick action")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(action.name if action else "")
        self.type_combo = QComboBox()
        for action_type, label in (
            (ActionType.BUILTIN, "Built-in action"),
            (ActionType.APPLICATION, "Launch application"),
            (ActionType.URL, "Open URL"),
            (ActionType.COMMAND, "Approved command"),
        ):
            self.type_combo.addItem(label, action_type)
        if action:
            self.type_combo.setCurrentIndex(self.type_combo.findData(action.type))
        self.target_edit = QLineEdit(action.target if action else "")
        self.target_edit.setPlaceholderText(
            "dance / firefox --private-window / https://example.com"
        )
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(action.enabled if action else True)
        form.addRow("Name", self.name_edit)
        form.addRow("Type", self.type_combo)
        form.addRow("Target", self.target_edit)
        layout.addLayout(form)
        layout.addWidget(self.enabled_check)
        warning = QLabel(
            "Command actions run the exact argument list shown above, without a shell. "
            "They can still modify files or launch programs. Approve only commands you "
            "understand and trust."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background:#fff4d6;color:#5f4b16;border:1px solid #e4cb7a;"
            "border-radius:6px;padding:7px;"
        )
        layout.addWidget(warning)
        self.approve_check = QCheckBox("I explicitly approve this command")
        unchanged_approval = bool(action and action.approved)
        self.approve_check.setChecked(unchanged_approval)
        layout.addWidget(self.approve_check)
        self.type_combo.currentIndexChanged.connect(self._sync_command_warning)
        self.target_edit.textEdited.connect(self._target_changed)
        self._initial_target = action.target if action else ""
        self._sync_command_warning()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_command_warning(self) -> None:
        command = self.type_combo.currentData() is ActionType.COMMAND
        self.approve_check.setVisible(command)

    def _target_changed(self, text: str) -> None:
        if text != self._initial_target:
            self.approve_check.setChecked(False)

    def definition(self) -> dict[str, object]:
        action_type = self.type_combo.currentData()
        return {
            "id": self.raw.get("id", "temporary"),
            "name": self.name_edit.text().strip(),
            "type": action_type.value,
            "target": self.target_edit.text().strip(),
            "enabled": self.enabled_check.isChecked(),
            "approved": bool(
                action_type is ActionType.COMMAND and self.approve_check.isChecked()
            ),
        }

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Enter an action name.")
            return
        action_type = self.type_combo.currentData()
        error = validate_target(action_type, self.target_edit.text())
        if error:
            QMessageBox.warning(self, "Invalid target", error)
            return
        if action_type is ActionType.COMMAND and self.approve_check.isChecked():
            answer = QMessageBox.warning(
                self,
                "Approve command action?",
                "This command can affect your computer. Run it only if you understand "
                "the exact target shown.\n\nApprove this command?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        self.accept()


class PreferencesDialog(QDialog):
    """Compact tabbed settings editor with live preview and safe cancellation."""

    TAB_NAMES = (
        "Character",
        "Behaviour",
        "Reminders",
        "Focus",
        "Integrations",
        "System",
    )

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self._snapshot = controller.config.to_dict()
        self._loading = True
        self.setWindowTitle("Desktop Buddy Preferences")
        self.resize(720, 610)
        self.setMinimumSize(620, 520)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_character_tab()
        self._build_behaviour_tab()
        self._build_reminders_tab()
        self._build_focus_tab()
        self._build_integrations_tab()
        self._build_system_tab()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self._reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        layout.addWidget(buttons)

        self._apply_capabilities()
        self._load_from_config()
        self._loading = False
        self._focus_refresh_timer = QTimer(self)
        self._focus_refresh_timer.setInterval(1000)
        self._focus_refresh_timer.timeout.connect(self.refresh_focus_status)
        self._focus_refresh_timer.start()
        self.refresh_focus_status()

    def _page(self, name: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.tabs.addTab(page, name)
        return page, layout

    def _build_character_tab(self) -> None:
        _, layout = self._page("Character")
        self.preview = CharacterPreview(self.controller, self)
        layout.addWidget(self.preview, 1)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(24)
        self.name_edit.textEdited.connect(self._on_name)
        form.addRow("Name", self.name_edit)
        self.species_combo = QComboBox()
        for key, info in SPECIES.items():
            self.species_combo.addItem(info["label"], key)
        self.species_combo.currentIndexChanged.connect(self._on_species)
        form.addRow("Character", self.species_combo)
        self.theme_combo = QComboBox()
        for key, colors in THEMES.items():
            self.theme_combo.addItem(colors["label"], key)
        self.theme_combo.currentIndexChanged.connect(self._on_theme)
        form.addRow("Theme", self.theme_combo)
        self.scale_slider, self.scale_label, scale_row = self._slider_row(50, 180, "%")
        self.scale_slider.valueChanged.connect(self._on_scale)
        form.addRow("Size", scale_row)
        self.state_combo = QComboBox()
        for label, state in CharacterPreview.STATES:
            self.state_combo.addItem(label, state)
        self.state_combo.currentIndexChanged.connect(
            lambda _index: self.preview.set_state(self.state_combo.currentData())
        )
        form.addRow("Preview animation", self.state_combo)
        layout.addLayout(form)

    def _build_behaviour_tab(self) -> None:
        _, layout = self._page("Behaviour")
        form = QFormLayout()
        self.speed_slider, self.speed_label, speed_row = self._slider_row(40, 250, "%")
        self.speed_slider.valueChanged.connect(self._on_speed)
        form.addRow("Movement speed", speed_row)
        self.fps_slider, self.fps_label, fps_row = self._slider_row(10, 60, " fps")
        self.fps_slider.valueChanged.connect(self._on_fps)
        form.addRow("Frame rate", fps_row)
        self.sleep_slider, self.sleep_label, sleep_row = self._slider_row(30, 600, " s")
        self.sleep_slider.valueChanged.connect(self._on_sleep)
        form.addRow("Sleep after idle", sleep_row)
        layout.addLayout(form)
        self.check_playful = QCheckBox("Play with and follow the cursor")
        self.check_sleep = QCheckBox("Sleep when idle")
        self.check_reduced_motion = QCheckBox(
            "Reduced motion (no runs, jumps, dances or particles)"
        )
        self.check_battery = QCheckBox("Reduce frame rate while on battery")
        self.check_playful.toggled.connect(
            lambda value: self._set_setting(self.controller.set_playful, value)
        )
        self.check_sleep.toggled.connect(
            lambda value: self._set_setting(self.controller.set_can_sleep, value)
        )
        self.check_reduced_motion.toggled.connect(
            lambda value: self._set_setting(self.controller.set_reduced_motion, value)
        )
        self.check_battery.toggled.connect(
            lambda value: self._set_setting(
                self.controller.set_reduce_on_battery, value
            )
        )
        for widget in (
            self.check_playful,
            self.check_sleep,
            self.check_reduced_motion,
            self.check_battery,
        ):
            layout.addWidget(widget)
        layout.addStretch()

    def _build_reminders_tab(self) -> None:
        _, layout = self._page("Reminders")
        self.check_reminders = QCheckBox("Enable reminders")
        self.check_chime = QCheckBox("Play a gentle chime")
        self.check_reminders.toggled.connect(self._on_reminders_enabled)
        self.check_chime.toggled.connect(self._on_reminder_sound)
        layout.addWidget(self.check_reminders)
        layout.addWidget(self.check_chime)
        reminder_group = QGroupBox("Your reminders")
        reminder_layout = QVBoxLayout(reminder_group)
        self.reminder_list = QListWidget()
        self.reminder_list.itemDoubleClicked.connect(
            lambda _item: self._edit_reminder()
        )
        reminder_layout.addWidget(self.reminder_list)
        buttons = QHBoxLayout()
        self.reminder_add_button = QPushButton("Add…")
        self.reminder_edit_button = QPushButton("Edit…")
        self.reminder_remove_button = QPushButton("Remove")
        self.reminder_fire_button = QPushButton("Show now")
        self.reminder_add_button.clicked.connect(self._add_reminder)
        self.reminder_edit_button.clicked.connect(self._edit_reminder)
        self.reminder_remove_button.clicked.connect(self._remove_reminder)
        self.reminder_fire_button.clicked.connect(self._fire_selected_reminder)
        for button in (
            self.reminder_add_button,
            self.reminder_edit_button,
            self.reminder_remove_button,
            self.reminder_fire_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch()
        reminder_layout.addLayout(buttons)
        layout.addWidget(reminder_group, 1)
        history_group = QGroupBox("Recent history")
        history_layout = QVBoxLayout(history_group)
        self.reminder_history_list = QListWidget()
        self.reminder_history_list.setMaximumHeight(130)
        history_layout.addWidget(self.reminder_history_list)
        layout.addWidget(history_group)

    def _build_focus_tab(self) -> None:
        _, layout = self._page("Focus")
        title = QLabel("Focus timer")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        status_group = QGroupBox("Current session")
        status_layout = QVBoxLayout(status_group)
        self.focus_status_label = QLabel()
        self.focus_status_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.focus_today_label = QLabel()
        status_layout.addWidget(self.focus_status_label)
        status_layout.addWidget(self.focus_today_label)
        controls = QHBoxLayout()
        self.focus_kind_combo = QComboBox()
        self._shown_focus_kind: SessionKind | None = None
        for kind in SessionKind:
            self.focus_kind_combo.addItem(kind_label(kind), kind)
        self.focus_start_button = QPushButton("Start")
        self.focus_pause_button = QPushButton("Pause")
        self.focus_resume_button = QPushButton("Resume")
        self.focus_skip_button = QPushButton("Skip")
        self.focus_stop_button = QPushButton("Stop")
        self.focus_start_button.clicked.connect(
            lambda: self.controller.focus_start(self.focus_kind_combo.currentData())
        )
        self.focus_pause_button.clicked.connect(self.controller.focus_pause)
        self.focus_resume_button.clicked.connect(self.controller.focus_resume)
        self.focus_skip_button.clicked.connect(self.controller.focus_skip)
        self.focus_stop_button.clicked.connect(self.controller.focus_stop)
        controls.addWidget(self.focus_kind_combo)
        for button in (
            self.focus_start_button,
            self.focus_pause_button,
            self.focus_resume_button,
            self.focus_skip_button,
            self.focus_stop_button,
        ):
            controls.addWidget(button)
        status_layout.addLayout(controls)
        layout.addWidget(status_group)

        settings_group = QGroupBox("Durations and cadence")
        settings_form = QFormLayout(settings_group)
        self.focus_minutes = self._minute_spin(1, 180)
        self.short_break_minutes = self._minute_spin(1, 60)
        self.long_break_minutes = self._minute_spin(1, 120)
        self.long_break_every = QSpinBox()
        self.long_break_every.setRange(1, 12)
        self.long_break_every.setSuffix(" focus sessions")
        settings_form.addRow("Focus", self.focus_minutes)
        settings_form.addRow("Short break", self.short_break_minutes)
        settings_form.addRow("Long break", self.long_break_minutes)
        settings_form.addRow("Long break after", self.long_break_every)
        self.focus_minutes.valueChanged.connect(
            lambda value: self._on_focus_setting("focus_minutes", value)
        )
        self.short_break_minutes.valueChanged.connect(
            lambda value: self._on_focus_setting("short_break_minutes", value)
        )
        self.long_break_minutes.valueChanged.connect(
            lambda value: self._on_focus_setting("long_break_minutes", value)
        )
        self.long_break_every.valueChanged.connect(
            lambda value: self._on_focus_setting("long_break_every", value)
        )
        layout.addWidget(settings_group)

        self.check_dnd = QCheckBox(
            "Do not disturb (pause automatic reminders and interruptions)"
        )
        self.check_dnd.toggled.connect(
            lambda value: self._set_setting(self.controller.set_do_not_disturb, value)
        )
        layout.addWidget(self.check_dnd)
        self.check_focus_quiet = QCheckBox(
            "Keep completion notifications within reminder active hours"
        )
        self.check_focus_fullscreen = QCheckBox(
            "Suppress completion notifications while an app is fullscreen"
        )
        self.check_focus_quiet.toggled.connect(
            lambda value: self._on_focus_setting("focus_respect_quiet_hours", value)
        )
        self.check_focus_fullscreen.toggled.connect(
            lambda value: self._on_focus_setting("focus_suppress_fullscreen", value)
        )
        layout.addWidget(self.check_focus_quiet)
        layout.addWidget(self.check_focus_fullscreen)
        history_group = QGroupBox("Last 7 days")
        history_layout = QVBoxLayout(history_group)
        self.focus_history_label = QLabel()
        self.focus_history_label.setWordWrap(True)
        history_layout.addWidget(self.focus_history_label)
        layout.addWidget(history_group)
        layout.addStretch()

    @staticmethod
    def _minute_spin(low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSuffix(" min")
        return spin

    def _build_integrations_tab(self) -> None:
        _, layout = self._page("Integrations")
        intro = QLabel(
            "Background integrations are opt-in controls and can be disabled here."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.check_perch = QCheckBox("Read the active window to perch on it")
        self.check_perch.toggled.connect(
            lambda value: self._set_setting(self.controller.set_perch_on_windows, value)
        )
        self.check_autostart = QCheckBox("Start Desktop Buddy when I log in")
        self.check_autostart.toggled.connect(
            lambda value: self._set_setting(self.controller.set_autostart, value)
        )
        layout.addWidget(self.check_perch)
        layout.addWidget(self.check_autostart)
        actions_group = QGroupBox("Quick actions")
        actions_layout = QVBoxLayout(actions_group)
        actions_help = QLabel(
            "Create shortcuts for built-ins, applications, URLs, or explicitly "
            "approved commands. Reminder actions run only after you press Done."
        )
        actions_help.setWordWrap(True)
        actions_layout.addWidget(actions_help)
        self.action_list = QListWidget()
        self.action_list.itemDoubleClicked.connect(lambda _item: self._edit_action())
        actions_layout.addWidget(self.action_list)
        action_buttons = QHBoxLayout()
        self.action_add_button = QPushButton("Add…")
        self.action_edit_button = QPushButton("Edit…")
        self.action_remove_button = QPushButton("Remove")
        self.action_run_button = QPushButton("Run")
        self.action_add_button.clicked.connect(self._add_action)
        self.action_edit_button.clicked.connect(self._edit_action)
        self.action_remove_button.clicked.connect(self._remove_action)
        self.action_run_button.clicked.connect(self._run_action)
        for button in (
            self.action_add_button,
            self.action_edit_button,
            self.action_remove_button,
            self.action_run_button,
        ):
            action_buttons.addWidget(button)
        action_buttons.addStretch()
        actions_layout.addLayout(action_buttons)
        layout.addWidget(actions_group, 1)

    def _build_system_tab(self) -> None:
        _, layout = self._page("System")
        self.check_top = QCheckBox("Keep the buddy always on top")
        self.check_click = QCheckBox("Click-through (use tray or CLI to undo)")
        self.check_silent = QCheckBox("Silent mode (disable all sounds)")
        self.check_top.toggled.connect(
            lambda value: self._set_setting(self.controller.set_always_on_top, value)
        )
        self.check_click.toggled.connect(
            lambda value: self._set_setting(self.controller.set_click_through, value)
        )
        self.check_silent.toggled.connect(
            lambda value: self._set_setting(self.controller.set_silent_mode, value)
        )
        layout.addWidget(self.check_top)
        layout.addWidget(self.check_click)
        layout.addWidget(self.check_silent)

        status_group = QGroupBox("Platform capabilities and permissions")
        self.capability_grid = QGridLayout(status_group)
        self.capability_labels: dict[Capability, QLabel] = {}
        names = {
            Capability.ALWAYS_ON_TOP: "Always on top",
            Capability.CLICK_THROUGH: "Click-through",
            Capability.ACTIVE_WINDOW: "Active-window access",
            Capability.AUTOSTART: "Login autostart",
            Capability.BATTERY: "Battery status",
            Capability.AUDIO: "Audio playback",
            Capability.WORKSPACE_BEHAVIOR: "All-workspace visibility",
        }
        for row, (capability, name) in enumerate(names.items()):
            self.capability_grid.addWidget(QLabel(name), row, 0)
            label = QLabel()
            label.setWordWrap(True)
            self.capability_grid.addWidget(label, row, 1)
            self.capability_labels[capability] = label
        layout.addWidget(status_group)

        self.capability_notice = QLabel()
        self.capability_notice.setWordWrap(True)
        self.capability_notice.setStyleSheet(
            "background: #fff4d6; color: #5f4b16; border: 1px solid #e4cb7a; "
            "border-radius: 6px; padding: 7px;"
        )
        layout.addWidget(self.capability_notice)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import…")
        self.export_button = QPushButton("Export…")
        self.reset_button = QPushButton("Reset all settings")
        self.import_button.clicked.connect(self._import_config)
        self.export_button.clicked.connect(self._export_config)
        self.reset_button.clicked.connect(self._restore_defaults)
        row.addWidget(self.import_button)
        row.addWidget(self.export_button)
        row.addStretch()
        row.addWidget(self.reset_button)
        layout.addLayout(row)

    def _slider_row(
        self, low: int, high: int, suffix: str
    ) -> tuple[QSlider, QLabel, QWidget]:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        label = QLabel()
        label.setMinimumWidth(58)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(label)
        slider.setProperty("suffix", suffix)
        return slider, label, row

    def _set_setting(self, setter, value: bool) -> None:  # noqa: ANN001
        if not self._loading:
            setter(value)

    def _load_from_config(self) -> None:
        config = self.controller.config
        self.name_edit.setText(config.name)
        for combo, value in (
            (self.theme_combo, config.theme),
            (self.species_combo, config.species),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.scale_slider.setValue(round(config.scale * 100))
        self.speed_slider.setValue(round(config.speed * 100))
        self.fps_slider.setValue(config.fps)
        self.sleep_slider.setValue(round(config.sleep_after))
        self.check_top.setChecked(config.always_on_top)
        self.check_click.setChecked(config.click_through)
        self.check_battery.setChecked(config.reduce_on_battery)
        self.check_playful.setChecked(config.playful)
        self.check_sleep.setChecked(config.can_sleep)
        self.check_reduced_motion.setChecked(config.reduced_motion)
        self.check_silent.setChecked(config.silent_mode)
        self.check_dnd.setChecked(config.do_not_disturb)
        self.focus_minutes.setValue(config.focus_minutes)
        self.short_break_minutes.setValue(config.short_break_minutes)
        self.long_break_minutes.setValue(config.long_break_minutes)
        self.long_break_every.setValue(config.long_break_every)
        self.check_focus_quiet.setChecked(config.focus_respect_quiet_hours)
        self.check_focus_fullscreen.setChecked(config.focus_suppress_fullscreen)
        self.check_perch.setChecked(config.perch_on_windows)
        self.check_autostart.setChecked(self.controller.autostart_active())
        self.check_reminders.setChecked(config.reminders_enabled)
        self.check_chime.setChecked(config.reminder_sound)
        self.refresh_reminders()
        self.refresh_actions()
        self.preview.refresh()

    def _apply_capabilities(self) -> None:
        controls = (
            (self.check_top, Capability.ALWAYS_ON_TOP),
            (self.check_click, Capability.CLICK_THROUGH),
            (self.check_battery, Capability.BATTERY),
            (self.check_perch, Capability.ACTIVE_WINDOW),
            (self.check_chime, Capability.AUDIO),
            (self.check_autostart, Capability.AUTOSTART),
            (self.check_focus_fullscreen, Capability.ACTIVE_WINDOW),
        )
        for widget, capability in controls:
            info = self.controller.backend.capability(capability)
            widget.setEnabled(info.available)
            widget.setToolTip(info.reason)
        unavailable: list[str] = []
        for capability, label in self.capability_labels.items():
            info = self.controller.backend.capability(capability)
            if info.available:
                label.setText("Available")
                label.setStyleSheet("color: #18713c;")
            else:
                reason = info.reason or "Unavailable on this platform."
                label.setText(f"Unavailable — {reason}")
                label.setStyleSheet("color: #8a3b12;")
                unavailable.append(reason)
        if unavailable:
            self.capability_notice.setText(
                "Unavailable features are disabled:\n"
                + "\n".join(dict.fromkeys(unavailable))
            )
        else:
            self.capability_notice.setText("All platform features are available.")

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
        if not self._loading and self.theme_combo.currentData():
            self.controller.set_theme(str(self.theme_combo.currentData()))
            self.preview.refresh()

    def _on_species(self, _index: int) -> None:
        if not self._loading and self.species_combo.currentData():
            self.controller.set_species(str(self.species_combo.currentData()))
            self.name_edit.setText(self.controller.config.name)
            self.preview.refresh()

    def _on_reminders_enabled(self, value: bool) -> None:
        if not self._loading:
            self.controller.set_reminders_enabled(value)

    def _on_reminder_sound(self, value: bool) -> None:
        if not self._loading:
            self.controller.set_reminder_sound(value)

    def refresh_reminders(self) -> None:
        selected = self._selected_id(self.reminder_list)
        self.reminder_list.clear()
        for raw in self.controller.config.reminders:
            reminder = Reminder.from_dict(raw)
            if reminder is None:
                continue
            state = "on" if reminder.enabled else "off"
            urgency = " · urgent" if reminder.urgent else ""
            item = QListWidgetItem(
                f"{reminder.icon} {reminder.title} — {reminder.schedule().describe()} "
                f"· {state}{urgency}"
            )
            item.setData(Qt.ItemDataRole.UserRole, reminder.id)
            self.reminder_list.addItem(item)
            if reminder.id == selected:
                self.reminder_list.setCurrentItem(item)
        self.reminder_history_list.clear()
        wellness = getattr(self.controller, "_wellness", None)
        if wellness is not None and callable(getattr(wellness, "recent_history", None)):
            for entry in wellness.recent_history(12):
                self.reminder_history_list.addItem(
                    f"{entry.handled_at.strftime('%b %d %H:%M')} · "
                    f"{entry.status.value} · {entry.title}"
                )

    def refresh_actions(self) -> None:
        selected = self._selected_id(self.action_list)
        self.action_list.clear()
        for raw in self.controller.config.actions:
            action = ActionDefinition.from_dict(raw)
            if action is None:
                continue
            flags = []
            if not action.enabled:
                flags.append("off")
            if action.type is ActionType.COMMAND and not action.approved:
                flags.append("not approved")
            suffix = f" · {', '.join(flags)}" if flags else ""
            item = QListWidgetItem(
                f"{action.name} — {action.type.value}: {action.target}{suffix}"
            )
            item.setData(Qt.ItemDataRole.UserRole, action.id)
            self.action_list.addItem(item)
            if action.id == selected:
                self.action_list.setCurrentItem(item)

    @staticmethod
    def _selected_id(widget: QListWidget) -> str | None:
        item = widget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _reminder_raw(self, reminder_id: str | None) -> dict | None:
        return next(
            (
                item
                for item in self.controller.config.reminders
                if isinstance(item, dict) and item.get("id") == reminder_id
            ),
            None,
        )

    def _action_raw(self, action_id: str | None) -> dict | None:
        return next(
            (
                item
                for item in self.controller.config.actions
                if isinstance(item, dict) and item.get("id") == action_id
            ),
            None,
        )

    def _add_reminder(self) -> None:
        dialog = ReminderEditDialog(self.controller, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.controller.save_reminder_definition(dialog.definition())
            except ValueError as exc:
                QMessageBox.warning(self, "Could not save reminder", str(exc))
            self.refresh_reminders()

    def _edit_reminder(self) -> None:
        reminder_id = self._selected_id(self.reminder_list)
        raw = self._reminder_raw(reminder_id)
        if raw is None:
            return
        dialog = ReminderEditDialog(self.controller, raw, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.controller.save_reminder_definition(
                    dialog.definition(), reminder_id
                )
            except ValueError as exc:
                QMessageBox.warning(self, "Could not save reminder", str(exc))
            self.refresh_reminders()

    def _remove_reminder(self) -> None:
        reminder_id = self._selected_id(self.reminder_list)
        if reminder_id and self.controller.remove_reminder(reminder_id):
            self.refresh_reminders()

    def _fire_selected_reminder(self) -> None:
        reminder_id = self._selected_id(self.reminder_list)
        if reminder_id:
            self.controller.remind_now(reminder_id)

    def _add_action(self) -> None:
        dialog = ActionEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.controller.save_action_definition(dialog.definition())
            except ValueError as exc:
                QMessageBox.warning(self, "Could not save action", str(exc))
            self.refresh_actions()

    def _edit_action(self) -> None:
        action_id = self._selected_id(self.action_list)
        raw = self._action_raw(action_id)
        if raw is None:
            return
        dialog = ActionEditDialog(raw, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.controller.save_action_definition(dialog.definition(), action_id)
            except ValueError as exc:
                QMessageBox.warning(self, "Could not save action", str(exc))
            self.refresh_actions()

    def _remove_action(self) -> None:
        action_id = self._selected_id(self.action_list)
        if action_id and self.controller.remove_action(action_id):
            self.refresh_actions()
            self.refresh_reminders()

    def _run_action(self) -> None:
        action_id = self._selected_id(self.action_list)
        if not action_id:
            return
        result = self.controller.run_action(action_id, announce=False)
        if not result.ok:
            QMessageBox.warning(self, "Action not run", result.message)

    def _on_focus_setting(self, key: str, value: int | bool) -> None:
        if not self._loading:
            self.controller.set_focus_setting(key, value)

    def refresh_focus_status(self) -> None:
        focus = getattr(self.controller, "_focus", None)
        if focus is None:
            self.focus_status_label.setText("Focus timer unavailable")
            self.focus_today_label.clear()
            self.focus_history_label.clear()
            return
        state = focus.state
        if self._shown_focus_kind is not state.kind:
            index = self.focus_kind_combo.findData(state.kind)
            if index >= 0:
                self.focus_kind_combo.setCurrentIndex(index)
            self._shown_focus_kind = state.kind
        remaining = format_duration(focus.remaining_seconds())
        self.focus_status_label.setText(
            f"{kind_label(state.kind)} · {remaining} · {state.status.value}"
        )
        today_minutes = focus.today_seconds() // 60
        self.focus_today_label.setText(
            f"Today: {today_minutes} focused minutes · "
            f"{state.completed_focus_sessions} completed sessions"
        )
        history = focus.recent_history(7)
        self.focus_history_label.setText(
            "   ".join(
                f"{day.strftime('%a')}: {seconds // 60}m" for day, seconds in history
            )
        )
        stopped = state.status is FocusStatus.STOPPED
        running = state.status is FocusStatus.RUNNING
        paused = state.status is FocusStatus.PAUSED
        self.focus_kind_combo.setEnabled(stopped)
        self.focus_start_button.setEnabled(stopped)
        self.focus_pause_button.setEnabled(running)
        self.focus_resume_button.setEnabled(paused)
        self.focus_skip_button.setEnabled(running or paused)
        self.focus_stop_button.setEnabled(running or paused)

    def _accept(self) -> None:
        self.controller.save_config()
        self.accept()

    def _reject(self) -> None:
        self.reject()

    def reject(self) -> None:
        self.controller.apply_snapshot(self._snapshot)
        super().reject()

    def _restore_defaults(self) -> None:
        self.controller.reset_config()
        self._loading = True
        self._load_from_config()
        self._loading = False

    def _import_config(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Desktop Buddy settings", "", "JSON files (*.json)"
        )
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("The JSON root must be an object.")
            imported = Config.from_dict(data)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.controller.apply_snapshot(imported.to_dict())
        self._loading = True
        self._load_from_config()
        self._loading = False

    def _export_config(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Desktop Buddy settings",
            "desktop-buddy-settings.json",
            "JSON files (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            self.controller.config.save(path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))


class OnboardingDialog(QDialog):
    """Small first-run setup for the choices that matter immediately."""

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Welcome to Desktop Buddy")
        self.setModal(True)
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        title = QLabel("Meet your new desktop buddy")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        text = QLabel(
            "Choose a character and a few comfortable defaults. You can change "
            "everything later in Preferences."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        form = QFormLayout()
        self.species_combo = QComboBox()
        for key, info in SPECIES.items():
            self.species_combo.addItem(info["label"], key)
        self.species_combo.setCurrentIndex(
            max(0, self.species_combo.findData(controller.config.species))
        )
        form.addRow("Character", self.species_combo)
        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(50, 180)
        self.scale_slider.setValue(round(controller.config.scale * 100))
        self.scale_label = QLabel(f"{self.scale_slider.value()}%")
        self.scale_slider.valueChanged.connect(
            lambda value: self.scale_label.setText(f"{value}%")
        )
        size_layout.addWidget(self.scale_slider, 1)
        size_layout.addWidget(self.scale_label)
        form.addRow("Size", size_row)
        self.active_start = QTimeEdit(
            QTime.fromString(controller.config.active_start, "HH:mm")
        )
        self.active_end = QTimeEdit(
            QTime.fromString(controller.config.active_end, "HH:mm")
        )
        self.active_start.setDisplayFormat("HH:mm")
        self.active_end.setDisplayFormat("HH:mm")
        form.addRow("Reminders start", self.active_start)
        form.addRow("Reminders end", self.active_end)
        self.autostart = QCheckBox("Start Desktop Buddy when I log in")
        info = controller.backend.capability(Capability.AUTOSTART)
        self.autostart.setEnabled(info.available)
        self.autostart.setToolTip(info.reason)
        self.autostart.setChecked(controller.autostart_active())
        form.addRow("", self.autostart)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        start = buttons.addButton("Get started", QDialogButtonBox.ButtonRole.AcceptRole)
        start.setDefault(True)
        buttons.accepted.connect(self._finish)
        layout.addWidget(buttons)

    def _finish(self) -> None:
        self.controller.set_species(str(self.species_combo.currentData()))
        self.controller.set_scale(self.scale_slider.value() / 100.0)
        self.controller.config.active_start = self.active_start.time().toString("HH:mm")
        self.controller.config.active_end = self.active_end.time().toString("HH:mm")
        self.controller.config.normalize()
        self.controller._rebuild_wellness()  # noqa: SLF001 - same UI/controller layer
        if self.autostart.isEnabled():
            self.controller.set_autostart(self.autostart.isChecked())
        self.controller.save_config()
        self.accept()

    def reject(self) -> None:
        self.controller.save_config()
        super().reject()
