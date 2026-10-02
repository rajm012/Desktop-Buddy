"""The transparent, always-on-top window that hosts the buddy."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QScreen,
)
from PyQt6.QtWidgets import QWidget

from .behavior import Brain, Event, State, World
from .character import CANVAS_H, CANVAS_W, Character, Palette
from .config import Config
from .effects import ParticleSystem
from .platform_utils import on_battery, set_window_sticky

log = logging.getLogger(__name__)


class BuddyWindow(QWidget):
    """Frameless ARGB window that draws and drives one buddy."""

    context_menu_requested = pyqtSignal(QPoint)

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        flags = self._compute_flags(config)
        super().__init__(parent, flags)
        self.config = config
        self._flags = flags
        self.config_changed_callback: Callable[[], None] | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, config.click_through
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle(config.name)

        self._paused = config.paused
        self._bubble_text = ""
        self._bubble_left = 0.0
        self._dragging = False
        self._grab_dx = 0.0
        self._grab_dy = 0.0
        self._last_move: tuple[int, int] | None = None
        self._on_battery = on_battery()
        self._battery_countdown = 10.0
        self._zzz_timer = 0.6

        screen = QGuiApplication.primaryScreen()
        self._screen: QScreen | None = screen
        self._brain = self._make_brain(config, screen)
        self._palette = Palette.from_colors(config.theme_colors())
        self._character = Character(self._palette)
        self._particles = ParticleSystem(random.Random())

        self._apply_size()
        self._move_window()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._update_timer()
        self._timer.start()
        self._last_tick = time.monotonic()
        self._connect_screen_signals()
        self._make_sticky()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _compute_flags(config: Config) -> Qt.WindowType:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if config.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if config.click_through:
            flags |= Qt.WindowType.WindowTransparentForInput
        return flags

    def _make_brain(self, config: Config, screen: QScreen | None) -> Brain:
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            world = World(
                left=float(geometry.left()),
                right=float(geometry.right()),
                ground=float(geometry.bottom()),
            )
            self._screen = screen
        else:
            world = World(left=0.0, right=1366.0, ground=768.0)
        brain = Brain(world=world, rng=random.Random())
        brain.speed_scale = config.speed
        brain.playful = config.playful
        brain.can_sleep = config.can_sleep
        brain.sleep_after = config.sleep_after
        if config.position_x is not None:
            brain.x = world.clamp_x(config.position_x, brain.tuning.edge_margin)
        return brain

    def _connect_screen_signals(self) -> None:
        app = QGuiApplication.instance()
        if app is None:
            return
        app.screenAdded.connect(self._on_screens_changed)
        app.screenRemoved.connect(self._on_screens_changed)
        for screen in app.screens():
            screen.availableGeometryChanged.connect(self._on_screens_changed)

    def _on_screens_changed(self, *_args: object) -> None:
        self._refresh_screen()

    def _refresh_screen(self) -> None:
        point = QPoint(int(self._brain.x), int(self._brain.world.ground) - 8)
        screen = QGuiApplication.screenAt(point) or self._screen
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self._screen = screen
        self._brain.world = World(
            left=float(geometry.left()),
            right=float(geometry.right()),
            ground=float(geometry.bottom()),
        )
        brain = self._brain
        brain.x = brain.world.clamp_x(brain.x, brain.tuning.edge_margin)
        brain.y = min(brain.y, brain.world.ground)
        self._last_move = None
        self._move_window()

    # ------------------------------------------------------------------ public
    @property
    def current_x(self) -> float:
        return self._brain.x

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._update_timer()
        self.update()

    def set_visible(self, visible: bool) -> None:
        if visible:
            self._last_move = None
            self._move_window()
            self.show()
            self._make_sticky()
            self.raise_()
        else:
            self.hide()

    def _make_sticky(self) -> None:
        """Keep the buddy visible on every workspace (X11 best effort)."""
        try:
            set_window_sticky(int(self.winId()))
        except Exception:  # noqa: BLE001
            log.debug("Could not set sticky window state", exc_info=True)

    def say(self, text: str, seconds: float = 4.5) -> None:
        self._bubble_text = text
        self._bubble_left = float(seconds)
        self.update()

    def apply_config(self) -> None:
        self.config.normalize()
        config = self.config
        self._brain.speed_scale = config.speed
        self._brain.playful = config.playful
        self._brain.can_sleep = config.can_sleep
        self._brain.sleep_after = config.sleep_after
        self._palette = Palette.from_colors(config.theme_colors())
        self._character.set_palette(self._palette)
        self.setWindowTitle(config.name)
        self._apply_size()
        self._apply_flags()
        self._update_timer()
        self._last_move = None
        self._move_window()
        self.update()

    # ------------------------------------------------------------- window mgmt
    def _apply_size(self) -> None:
        width = max(72, int(round(CANVAS_W * self.config.scale)))
        height = max(120, int(round(CANVAS_H * self.config.scale)))
        self.setFixedSize(width, height)

    def _apply_flags(self) -> None:
        flags = self._compute_flags(self.config)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, self.config.click_through
        )
        if flags == self._flags:
            return
        visible = self.isVisible()
        self._flags = flags
        self.setWindowFlags(flags)
        if visible:
            self.show()
            self._make_sticky()

    def _move_window(self) -> None:
        width, height = self.width(), self.height()
        x = int(round(self._brain.x - width / 2.0))
        y = int(round(self._brain.world.ground)) + 1 - height
        if (x, y) != self._last_move:
            self.move(x, y)
            self._last_move = (x, y)

    def _update_timer(self) -> None:
        interval = max(16, int(round(1000.0 / self._desired_fps())))
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _desired_fps(self) -> float:
        """Adaptive frame rate: full speed while moving, gentle while idling."""
        if self._paused:
            return 4.0
        active = self._brain.state in (
            State.WALK,
            State.RUN,
            State.AIR,
            State.LAND,
            State.DRAG,
        )
        fps = float(self.config.fps) if active else min(15.0, float(self.config.fps))
        if self.config.reduce_on_battery and self._on_battery:
            fps = min(fps, 20.0 if active else 12.0)
        return max(8.0, min(60.0, fps))

    # -------------------------------------------------------------------- loop
    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now

        self._battery_countdown -= dt
        if self._battery_countdown <= 0.0:
            self._battery_countdown = 15.0
            value = on_battery()
            if value != self._on_battery:
                self._on_battery = value
                self._update_timer()

        if self._bubble_left > 0.0:
            self._bubble_left = max(0.0, self._bubble_left - dt)

        if self._paused:
            self.update()
            return

        self._update_timer()
        cursor = QCursor.pos()
        self._brain.set_cursor(float(cursor.x()), float(cursor.y()))
        for event in self._brain.step(dt):
            self._handle_event(event)
        self._update_zzz(dt)
        self._particles.update(dt)
        self._move_window()
        self.update()

    def _handle_event(self, event: Event) -> None:
        if event is Event.JUMP:
            self._particles.emit("sparkles", 0.0, -18.0, self._palette)
        elif event is Event.LAND:
            strength = min(1.6, max(0.6, abs(self._brain.last_impact) / 600.0))
            for _ in range(int(strength * 2)):
                self._particles.emit("dust", 0.0, 0.0, self._palette)
        elif event is Event.POKE:
            self._particles.emit("hearts", 0.0, -64.0, self._palette)
        elif event is Event.WAKE:
            self._particles.emit("sparkles", 0.0, -46.0, self._palette)

    def _update_zzz(self, dt: float) -> None:
        if self._brain.state is State.SLEEP:
            self._zzz_timer -= dt
            if self._zzz_timer <= 0.0:
                self._zzz_timer = 1.5
                self._particles.emit("zzz", 24.0, -78.0, self._palette)
        else:
            self._zzz_timer = 0.6

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        if event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.config.click_through:
            self._dragging = True
            self._brain.start_drag()
            position = event.globalPosition()
            self._grab_dx = self._brain.x - position.x()
            self._grab_dy = self._brain.y - position.y()
            self._brain.drag_to(
                position.x() + self._grab_dx,
                position.y() + self._grab_dy,
                time.monotonic(),
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if not self._dragging:
            return
        position = event.globalPosition()
        self._brain.drag_to(
            position.x() + self._grab_dx,
            position.y() + self._grab_dy,
            time.monotonic(),
        )
        self._move_window()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            vx, vy = self._brain.drag_velocity()
            self._brain.end_drag(vx, vy)
            self.unsetCursor()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() != Qt.MouseButton.LeftButton or self.config.click_through:
            return
        if self._brain.state is State.DRAG:
            self._dragging = False
            self._brain.end_drag()
        for event_out in self._brain.poke():
            self._handle_event(event_out)
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: ANN001
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            event.ignore()
            return
        steps = event.angleDelta().y() / 120.0
        self.config.scale = max(0.5, min(1.8, self.config.scale + steps * 0.06))
        self.apply_config()
        if self.config_changed_callback:
            self.config_changed_callback()
        event.accept()

    def enterEvent(self, event) -> None:  # noqa: ANN001
        if not self.config.click_through:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        if not self._dragging:
            self.unsetCursor()
        super().leaveEvent(event)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._character.paint(painter, self._brain, self.width(), self.height())
        unit = max(0.1, self.width() / CANVAS_W)
        painter.save()
        painter.translate(self.width() / 2.0, self.height())
        painter.scale(unit, unit)
        self._particles.paint(painter)
        self._paint_bubble(painter, unit)
        painter.restore()
        painter.end()

    def _paint_bubble(self, painter: QPainter, unit: float) -> None:
        if not self._bubble_text or self._bubble_left <= 0.0:
            return
        font = QFont("DejaVu Sans")
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(self._bubble_text)
        width = text_width + 22.0
        height = metrics.height() + 12.0
        air_units = self._brain.height / unit
        center_y = -104.0 - air_units
        rect = QRectF(-width / 2.0, center_y - height, width, height)

        painter.setOpacity(min(1.0, self._bubble_left / 0.5))
        painter.setBrush(QColor(255, 255, 255, 238))
        painter.setPen(QPen(self._palette.outline, 2.0))
        painter.drawRoundedRect(rect, 10.0, 10.0)
        tail = QPainterPath()
        tail.moveTo(-7.0, rect.bottom() - 0.5)
        tail.lineTo(0.0, rect.bottom() + 9.0)
        tail.lineTo(7.0, rect.bottom() - 0.5)
        tail.closeSubpath()
        painter.setBrush(QColor(255, 255, 255, 238))
        painter.drawPath(tail)
        painter.setPen(QPen(self._palette.eye))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._bubble_text)
        painter.setOpacity(1.0)
