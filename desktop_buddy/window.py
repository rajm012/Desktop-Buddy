"""The transparent, always-on-top window that hosts the buddy."""

from __future__ import annotations

import logging
import math
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

from .behavior import Brain, Event, Perch, State, World
from .character import (
    CANVAS_H,
    CANVAS_W,
    FOOT_PAD_UNITS,
    Palette,
    make_character,
)
from .config import Config
from .effects import ParticleSystem
from .focus import FocusStatus, SessionKind, format_duration
from .platforms import get_backend
from .platforms.base import Capability, PlatformBackend

log = logging.getLogger(__name__)

# How long the buddy keeps its perch after you switch to an unrelated window.
PERCH_RELEASE_DELAY = 4.0


class BuddyWindow(QWidget):
    """Frameless ARGB window that draws, drives and choreographs one buddy."""

    context_menu_requested = pyqtSignal(QPoint)

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        backend: PlatformBackend | None = None,
    ) -> None:
        self.backend = backend or get_backend()
        flags = self._compute_flags(config, self.backend)
        super().__init__(parent, flags)
        self.config = config
        self._flags = flags
        self.config_changed_callback: Callable[[], None] | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._click_through_active(),
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
        self._on_battery = (
            self.backend.battery_status().on_battery
            if config.reduce_on_battery
            else False
        )
        self._battery_countdown = 10.0
        self._zzz_timer = 0.6
        self._note_timer = 0.2
        self._wisp_timer = 0.05
        self._perch_cooldown_until = 0.0
        self._press_count = 0
        self._perch_window_id: int | None = None
        self._perch_since = 0.0
        self._perch_loss_since: float | None = None
        self._focus_kind = SessionKind.FOCUS
        self._focus_status = FocusStatus.STOPPED
        self._focus_remaining = 0
        self._focus_completion_left = 0.0
        self._platform_fullscreen = False

        screen = QGuiApplication.primaryScreen()
        self._screen: QScreen | None = screen
        self._brain = self._make_brain(config, screen)
        self._palette = Palette.from_colors(config.theme_colors())
        self._character = make_character(config.species, self._palette)
        self._species = config.species
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

        self._probe = self.backend.create_active_window_probe()
        self._perch_timer = QTimer(self)
        self._perch_timer.setInterval(700)
        self._perch_timer.timeout.connect(self._poll_perch)
        self._perch_timer.start()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _compute_flags(config: Config, backend: PlatformBackend) -> Qt.WindowType:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if config.always_on_top and backend.supports(Capability.ALWAYS_ON_TOP):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if config.click_through and backend.supports(Capability.CLICK_THROUGH):
            flags |= Qt.WindowType.WindowTransparentForInput
        return flags

    def _click_through_active(self) -> bool:
        return self.config.click_through and self.backend.supports(
            Capability.CLICK_THROUGH
        )

    @staticmethod
    def _configure_brain_for_species(brain: Brain, species: str) -> None:
        ghost = species == "ghost"
        brain.can_dance = species in ("ghost", "robot")
        brain.gravity_scale = 0.32 if ghost else 1.0
        brain.max_fall_speed = 150.0 if ghost else 1500.0
        brain.jump_scale = 0.85 if ghost else 1.0
        brain.body_height = 132.0 if species == "robot" else 96.0

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
        brain.reduced_motion = config.reduced_motion
        self._configure_brain_for_species(brain, config.species)
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
        screen_world = self._brain.screen_world or self._brain.world
        point = QPoint(int(self._brain.x), int(screen_world.ground) - 8)
        screen = QGuiApplication.screenAt(point) or self._screen
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self._screen = screen
        screen_world = World(
            left=float(geometry.left()),
            right=float(geometry.right()),
            ground=float(geometry.bottom()),
        )
        brain = self._brain
        brain.screen_world = screen_world
        if brain.perch is None:
            brain.world = screen_world
            brain.x = screen_world.clamp_x(brain.x, brain.tuning.edge_margin)
            brain.y = min(brain.y, screen_world.ground)
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

    def say(self, text: str, seconds: float = 4.5) -> None:
        self._bubble_text = text
        self._bubble_left = float(seconds)
        self.update()

    def dance(self) -> None:
        if self.config.reduced_motion:
            self.say("Reduced motion is on.", 2.5)
            return
        for event in self._brain.dance():
            self._handle_event(event)
        self.update()

    def remind(self, kind: str, text: str) -> None:
        """Play a little attention animation for a wellness reminder."""
        self.say(text, seconds=9.0)
        if self.config.reduced_motion:
            self.update()
            return
        if kind == "water":
            self._particles.emit("drops", 0.0, -34.0, self._palette)
        elif kind == "meal":
            self._particles.emit("hearts", 0.0, -62.0, self._palette)
            self._particles.emit("sparkles", 0.0, -30.0, self._palette)
        elif kind == "winddown":
            self._particles.emit("zzz", 18.0, -76.0, self._palette)
            self._particles.emit("sparkles", 0.0, -40.0, self._palette)
        else:
            self._particles.emit("sparkles", 0.0, -36.0, self._palette)
            self._particles.emit("notes", 6.0, -80.0, self._palette)
        if not self._paused and self._brain.state not in (
            State.AIR,
            State.DRAG,
            State.CLIMB,
        ):
            for event in self._brain.dance():
                self._handle_event(event)
        self.update()

    def set_focus_state(
        self, kind: SessionKind, status: FocusStatus, remaining_seconds: int
    ) -> None:
        self._focus_kind = kind
        self._focus_status = status
        self._focus_remaining = max(0, int(remaining_seconds))
        self._brain.focus_kind = kind.value
        self._brain.focus_status = status.value
        self.update()

    def focus_started(self, kind: SessionKind, text: str) -> None:
        self.say(text, 4.0)
        if not self.config.reduced_motion:
            particle = "sparkles" if kind is SessionKind.FOCUS else "hearts"
            self._particles.emit(particle, 0.0, -54.0, self._palette)
        self.update()

    def focus_completed(
        self, kind: SessionKind, next_kind: SessionKind, text: str
    ) -> None:
        self.say(text, 8.0)
        self._focus_completion_left = 4.0
        if not self.config.reduced_motion:
            self._particles.emit("sparkles", 0.0, -46.0, self._palette)
            self._particles.emit("hearts", 0.0, -68.0, self._palette)
            if not self._paused and self._brain.state not in (
                State.AIR,
                State.DRAG,
                State.CLIMB,
            ):
                for event in self._brain.dance():
                    self._handle_event(event)
        self.update()

    def apply_config(self) -> None:
        self.config.normalize()
        config = self.config
        self._brain.speed_scale = config.speed
        self._brain.playful = config.playful
        self._brain.can_sleep = config.can_sleep
        self._brain.sleep_after = config.sleep_after
        self._brain.reduced_motion = config.reduced_motion
        self._configure_brain_for_species(self._brain, config.species)
        if self._species != config.species:
            self._character = make_character(config.species, self._palette)
            self._species = config.species
        if (
            config.species not in ("ghost", "robot")
            and self._brain.state is State.DANCE
        ):
            self._brain._to_idle()  # noqa: SLF001 - same package helper
        self._palette = Palette.from_colors(config.theme_colors())
        self._character.set_palette(self._palette)
        if config.reduced_motion:
            self._particles.clear()
            if self._brain.state in (State.RUN, State.AIR, State.DANCE):
                self._brain._to_idle()  # noqa: SLF001 - same package helper
                self._brain.y = self._brain.world.ground
                self._brain.vy = 0.0
        self.setWindowTitle(config.name)
        self._apply_size()
        self._apply_flags()
        self._update_timer()
        self._last_move = None
        self._move_window()
        if not config.perch_on_windows:
            self._drop_perch()
        self.update()

    # ------------------------------------------------------------- window mgmt
    def _apply_size(self) -> None:
        width = max(72, int(round(CANVAS_W * self.config.scale)))
        height = max(120, int(round(CANVAS_H * self.config.scale)))
        self.setFixedSize(width, height)
        unit = width / CANVAS_W
        self._feet_local_px = FOOT_PAD_UNITS * unit
        self._brain.body_height = 100.0 * unit
        self._brain.tuning.edge_margin = max(46.0, width / 2.0 + 2.0)

    def _apply_flags(self) -> None:
        flags = self._compute_flags(self.config, self.backend)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._click_through_active(),
        )
        if flags == self._flags:
            self._make_sticky()
            return
        visible = self.isVisible()
        self._flags = flags
        self.setWindowFlags(flags)
        if visible:
            self.show()
            self._make_sticky()

    def _make_sticky(self) -> None:
        """Apply native topmost, input and workspace behavior when supported."""
        try:
            self.backend.apply_window_behavior(
                int(self.winId()),
                always_on_top=self.config.always_on_top
                and not self._platform_fullscreen,
                click_through=self._click_through_active(),
            )
        except Exception:  # noqa: BLE001
            log.debug("Could not apply native window behavior", exc_info=True)

    def set_platform_fullscreen(self, active: bool) -> None:
        """Lower native topmost state while another app owns fullscreen."""
        active = bool(active)
        if active == self._platform_fullscreen:
            return
        self._platform_fullscreen = active
        self._make_sticky()

    def _move_window(self) -> None:
        """Keep the window on-screen and move the buddy inside it instead.

        Mutter refuses to place managed windows above the screen, so the
        window's local foot offset absorbs the difference. The buddy can
        therefore be dropped anywhere on the screen.
        """
        width, height = self.width(), self.height()
        unit = width / CANVAS_W
        screen = self._brain.screen_world or self._brain.world
        pad = FOOT_PAD_UNITS * unit
        desired_y = self._brain.y - height + pad
        min_y = float(screen.ceiling)
        max_y = max(min_y, float(screen.ground) + 1.0 - height)
        y = max(min_y, min(desired_y, max_y))
        self._feet_local_px = max(2.0, min(float(height) - 2.0, self._brain.y - y))
        x = int(round(self._brain.x - width / 2.0))
        y = int(round(y))
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
            State.CLIMB,
            State.DANCE,
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
        if self.config.reduce_on_battery and self._battery_countdown <= 0.0:
            self._battery_countdown = 15.0
            value = self.backend.battery_status().on_battery
            if value != self._on_battery:
                self._on_battery = value
                self._update_timer()
        elif not self.config.reduce_on_battery:
            self._battery_countdown = 0.0

        if self._bubble_left > 0.0:
            self._bubble_left = max(0.0, self._bubble_left - dt)
        if self._focus_completion_left > 0.0:
            self._focus_completion_left = max(0.0, self._focus_completion_left - dt)

        if self._paused:
            self.update()
            return

        self._update_timer()
        cursor = QCursor.pos()
        self._brain.set_cursor(float(cursor.x()), float(cursor.y()))
        for event in self._brain.step(dt):
            self._handle_event(event)
        if not self.config.reduced_motion:
            self._update_zzz(dt)
            self._update_species_effects(dt)
        self._particles.update(dt)
        self._move_window()
        self.update()

    def _handle_event(self, event: Event) -> None:
        if self.config.reduced_motion:
            return
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
        elif event is Event.DANCE:
            self._particles.emit("hearts", 0.0, -70.0, self._palette)
            self._particles.emit("notes", 6.0, -84.0, self._palette)
        elif event is Event.PERCH:
            self._particles.emit("sparkles", 0.0, -30.0, self._palette)

    def _update_zzz(self, dt: float) -> None:
        if self._brain.state is State.SLEEP:
            self._zzz_timer -= dt
            if self._zzz_timer <= 0.0:
                self._zzz_timer = 1.5
                self._particles.emit("zzz", 24.0, -78.0, self._palette)
        else:
            self._zzz_timer = 0.6

    def _update_species_effects(self, dt: float) -> None:
        state = self._brain.state
        if state is State.DANCE:
            self._note_timer -= dt
            if self._note_timer <= 0.0:
                self._note_timer = 0.4
                self._particles.emit("notes", 10.0, -84.0, self._palette)
        else:
            self._note_timer = 0.2
        if self.config.species == "ghost" and state in (State.RUN, State.AIR):
            self._wisp_timer -= dt
            if self._wisp_timer <= 0.0:
                self._wisp_timer = 0.16
                self._particles.emit("wisp", -18.0, -38.0, self._palette)
        else:
            self._wisp_timer = 0.05

    # ------------------------------------------------------------------ perching
    def _poll_perch(self) -> None:
        config = self.config
        if (
            not config.perch_on_windows
            or self._click_through_active()
            or not self.backend.supports(Capability.ACTIVE_WINDOW)
            or not self._probe.available
            or time.monotonic() < self._perch_cooldown_until
        ):
            self._drop_perch()
            return
        info = self._probe.active_window()
        self.set_platform_fullscreen(bool(info and info.fullscreen))
        if info is None or info.hidden or info.fullscreen:
            self._drop_perch()
            return
        try:
            own_id = int(self.winId())
        except Exception:  # noqa: BLE001
            own_id = 0
        if info.window_id == own_id:
            self._drop_perch()
            return
        kind = self.backend.classify_window(info.class_name)
        if kind is None:
            self._release_perch_after_delay()
            return
        self._perch_loss_since = None

        now = time.monotonic()
        if self._perch_window_id != info.window_id:
            self._perch_window_id = info.window_id
            self._perch_since = now
            return
        if now - self._perch_since < config.perch_delay:
            return

        screen = self._screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        dpr = max(0.1, screen.devicePixelRatio())
        geometry = screen.geometry()
        window_rect = QRectF(
            info.x / dpr, info.y / dpr, info.width / dpr, info.height / dpr
        )
        if window_rect.width() < 260.0 or window_rect.height() < 160.0:
            self._drop_perch()
            return
        if (
            window_rect.bottom() < geometry.top() + 40.0
            or window_rect.top() > geometry.bottom() - 40.0
        ):
            self._drop_perch()
            return

        margin = 26.0
        left = window_rect.left() + margin
        right = window_rect.right() - margin
        if right - left < 120.0:
            left, right = window_rect.left() + 8.0, window_rect.right() - 8.0
        if kind == "browser":
            # Just above the address/search bar, a third of the way across.
            x = window_rect.left() + min(
                max(window_rect.width() * 0.33, 120.0), window_rect.width() - 120.0
            )
        else:
            # Near the prompt: left-ish side of a terminal window.
            x = window_rect.left() + min(
                max(window_rect.width() * 0.22, 90.0), window_rect.width() - 90.0
            )
        # Stand on the top edge when the buddy fits above the window,
        # otherwise hover along the toolbar / first prompt line inside it.
        body_height = self._brain.body_height
        if window_rect.top() >= body_height + 24.0:
            perch_y = window_rect.top() - 1.0
        else:
            perch_y = window_rect.top() + (92.0 if kind == "browser" else 84.0)
        perch_y = max(perch_y, float(geometry.top()) + body_height + 4.0)
        perch = Perch(
            x=x,
            y=perch_y,
            left=left,
            right=right,
            kind=kind,
        )
        if self._brain.set_perch(perch):
            log.info(
                "Perching on %s (%s) at (%.0f, %.0f)",
                info.class_name or "window",
                kind,
                perch.x,
                perch.y,
            )

    def _release_perch_after_delay(self) -> None:
        """Stay put for a moment when focus moves to an unrelated window."""
        if self._brain.perch is None:
            return
        now = time.monotonic()
        if self._perch_loss_since is None:
            self._perch_loss_since = now
            return
        if now - self._perch_loss_since >= PERCH_RELEASE_DELAY:
            self._drop_perch()

    def _drop_perch(self) -> None:
        self._perch_window_id = None
        self._perch_loss_since = None
        for event in self._brain.clear_perch():
            self._handle_event(event)

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        self._press_count += 1
        if event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._click_through_active()
        ):
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
            self._move_window()
            self.update()
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
            # Don't immediately climb back onto a window after being put down.
            self._perch_cooldown_until = time.monotonic() + 20.0
            self.unsetCursor()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() != Qt.MouseButton.LeftButton or self._click_through_active():
            return
        if self._brain.state is State.DRAG:
            self._dragging = False
            self._brain.end_drag()
        for event_out in self._brain.poke():
            self._handle_event(event_out)
        self._perch_cooldown_until = time.monotonic() + 5.0
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
        if not self._click_through_active():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        if not self._dragging:
            self.unsetCursor()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._probe.close()
        super().closeEvent(event)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        unit = max(0.1, self.width() / CANVAS_W)
        feet_local = self._feet_local_px
        bottom_pad_units = (self.height() - feet_local) / unit
        self._character.paint(
            painter, self._brain, self.width(), self.height(), bottom_pad_units
        )
        painter.save()
        painter.translate(self.width() / 2.0, feet_local)
        painter.scale(unit, unit)
        self._particles.paint(painter)
        self._paint_focus_badge(painter)
        self._paint_bubble(painter, unit)
        painter.restore()
        painter.end()

    def _paint_focus_badge(self, painter: QPainter) -> None:
        active = self._focus_status in (FocusStatus.RUNNING, FocusStatus.PAUSED)
        if not active and self._focus_completion_left <= 0.0:
            return
        painter.save()
        x = 42.0
        y = -78.0
        pulse = 1.0 + 0.06 * abs(math.sin(self._brain.anim_time * 3.0))
        if self.config.reduced_motion:
            pulse = 1.0
        painter.translate(x, y)
        painter.scale(pulse, pulse)
        fill = QColor("#d9f3ff")
        outline = QColor("#287a9c")
        symbol = "F"
        if self._focus_kind is not SessionKind.FOCUS:
            fill = QColor("#e7f7df")
            outline = QColor("#4d8a45")
            symbol = "B"
        if self._focus_status is FocusStatus.PAUSED:
            fill = QColor("#f3f0f7")
            outline = QColor("#6d607e")
            symbol = "Ⅱ"
        if self._focus_completion_left > 0.0:
            fill = QColor("#fff0b8")
            outline = QColor("#b17800")
            symbol = "✓"
        painter.setBrush(fill)
        painter.setPen(QPen(outline, 2.0))
        painter.drawEllipse(QRectF(-17.0, -17.0, 34.0, 34.0))
        font = QFont("DejaVu Sans")
        font.setBold(True)
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(outline)
        painter.drawText(
            QRectF(-16.0, -14.0, 32.0, 18.0), Qt.AlignmentFlag.AlignCenter, symbol
        )
        font.setPixelSize(7)
        painter.setFont(font)
        painter.drawText(
            QRectF(-19.0, 1.0, 38.0, 12.0),
            Qt.AlignmentFlag.AlignCenter,
            format_duration(self._focus_remaining),
        )
        painter.restore()

    def _paint_bubble(self, painter: QPainter, unit: float) -> None:
        if not self._bubble_text or self._bubble_left <= 0.0:
            return
        font = QFont("DejaVu Sans")
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        lines = self._wrap_bubble_text(self._bubble_text, metrics, 118.0)
        text_width = max(metrics.horizontalAdvance(line) for line in lines)
        width = text_width + 22.0
        height = metrics.height() * len(lines) + 12.0
        center_y = -104.0
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
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "\n".join(lines))
        painter.setOpacity(1.0)

    @staticmethod
    def _wrap_bubble_text(text: str, metrics, max_width: float) -> list[str]:  # noqa: ANN001
        words = text.split()
        if not words:
            return [text]
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if not current or metrics.horizontalAdvance(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) > 3:
            merged = " ".join(lines[2:])
            lines = lines[:2]
            while merged and metrics.horizontalAdvance(merged + "…") > max_width:
                merged = merged[:-1]
            lines.append(merged + "…")
        return lines
