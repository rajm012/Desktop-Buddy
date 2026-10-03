"""A small reminder card that pops up next to the buddy."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .character import Palette
from .wellness import Reminder

log = logging.getLogger(__name__)

AUTO_DISMISS_SECONDS = 45.0


class ReminderToast(QWidget):
    """Frameless card with Done / Snooze, parked next to the buddy."""

    closed = pyqtSignal()

    def __init__(
        self,
        reminder: Reminder,
        message: str,
        palette: Palette,
        anchor_fn,  # noqa: ANN001 - callable returning (x, y, w, h)
        on_done,  # noqa: ANN001
        on_snooze,  # noqa: ANN001
        on_dismiss,  # noqa: ANN001
        snooze_minutes: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.reminder = reminder
        self.palette_colors = palette
        self._anchor_fn = anchor_fn
        self._on_done = on_done
        self._on_snooze = on_snooze
        self._on_dismiss = on_dismiss
        self._finished = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle(f"{reminder.title} — Desktop Buddy")
        self.setFixedWidth(340)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        icon = QLabel(reminder.icon)
        icon.setStyleSheet("font-size: 30px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        icon.setFixedWidth(44)
        outer.addWidget(icon)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        title = QLabel(reminder.title)
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {palette.outline.name()};"
        )
        body = QLabel(message)
        body.setWordWrap(True)
        body.setStyleSheet("font-size: 12px; color: #2b2f36;")
        body.setMinimumWidth(190)
        text_column.addWidget(title)
        text_column.addWidget(body)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        done = QPushButton("Done")
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        done.setStyleSheet(
            "QPushButton {"
            f"background: {palette.body.name()}; color: {palette.eye.name()};"
            "border: none; border-radius: 12px; padding: 6px 14px;"
            "font-weight: 600; }"
            "QPushButton:hover { background: "
            f"{palette.body_dark.name()}; }}"
        )
        done.clicked.connect(self._done)
        snooze = QPushButton(f"Snooze {snooze_minutes}m")
        snooze.setCursor(Qt.CursorShape.PointingHandCursor)
        snooze.setStyleSheet(
            "QPushButton { background: rgba(0,0,0,0.10); color: #2b2f36;"
            "border: 1px solid rgba(0,0,0,0.14); border-radius: 12px;"
            "padding: 6px 12px; }"
            "QPushButton:hover { background: rgba(0,0,0,0.18); }"
        )
        snooze.clicked.connect(self._snooze)
        buttons.addWidget(done)
        buttons.addWidget(snooze)
        buttons.addStretch(1)
        text_column.addLayout(buttons)
        outer.addLayout(text_column, 1)

        self.adjustSize()
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(450)
        self._follow_timer.timeout.connect(self._reposition)
        self._follow_timer.start()

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._dismiss)
        self._auto_timer.start(int(AUTO_DISMISS_SECONDS * 1000))
        self._reposition()

    # ------------------------------------------------------------------ layout
    def show_near_buddy(self) -> None:
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self) -> None:
        try:
            ax, ay, aw, ah = self._anchor_fn()
        except Exception:  # noqa: BLE001
            return
        screen = QGuiApplication.screenAt(QPoint(int(ax), int(ay)))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width, height = self.width(), self.height()
        x = ax + aw / 2.0 - width / 2.0
        x = max(area.left() + 8, min(x, area.right() - width - 8))
        above = ay - height - 14
        if above >= area.top() + 8:
            y = above
        else:
            y = min(ay + ah + 14, area.bottom() - height - 8)
        y = max(area.top() + 8, y)
        if (int(x), int(y)) != (self.x(), self.y()):
            self.move(int(x), int(y))

    # ----------------------------------------------------------------- actions
    def _finish(self, reason: str) -> None:
        if self._finished:
            return
        log.info("Toast %s closed (%s)", self.reminder.id, reason)
        self._finished = True
        self._follow_timer.stop()
        self._auto_timer.stop()
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def _done(self) -> None:
        self._on_done(self.reminder)
        self._finish("done")

    def _snooze(self) -> None:
        self._on_snooze(self.reminder)
        self._finish("snoozed")

    def _dismiss(self) -> None:
        self._on_dismiss(self.reminder)
        self._finish("dismissed")

    # ------------------------------------------------------------------- paint
    def showEvent(self, event) -> None:  # noqa: ANN001
        log.info("Toast %s shown at (%d,%d)", self.reminder.id, self.x(), self.y())
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: ANN001
        log.info("Toast %s hidden", self.reminder.id)
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor(self.palette_colors.outline), 2.0))
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.drawRoundedRect(rect, 16.0, 16.0)
        painter.end()
