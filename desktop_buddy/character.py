"""Procedural rendering of the buddy characters.

Everything is drawn with QPainter (no bitmap assets), which keeps the buddies
crisp at any scale/DPI and makes the animation buttery smooth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from .behavior import Brain, State, World

# Canvas is expressed in abstract units; the window scales it to pixels.
CANVAS_W = 140.0
CANVAS_H = 160.0
FOOT_PAD_UNITS = 18.0


@dataclass(frozen=True)
class Palette:
    body: QColor
    body_dark: QColor
    belly: QColor
    accent: QColor
    outline: QColor
    blush: QColor
    eye: QColor

    @classmethod
    def from_colors(cls, colors: dict[str, str]) -> "Palette":
        def color(key: str, fallback: str) -> QColor:
            value = colors.get(key, fallback)
            parsed = QColor(value)
            return parsed if parsed.isValid() else QColor(fallback)

        return cls(
            body=color("body", "#7ed6b5"),
            body_dark=color("body_dark", "#5bbf9c"),
            belly=color("belly", "#eafbf3"),
            accent=color("accent", "#f9a8c9"),
            outline=color("outline", "#2f5d50"),
            blush=color("blush", "#f7a8b8"),
            eye=color("eye", "#20302c"),
        )


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _paint_ground_shadow(
    painter: QPainter,
    brain: Brain,
    unit: float,
    color: QColor,
    base_rx: float = 27.0,
    base_ry: float = 6.0,
    max_offset: float = 130.0,
) -> None:
    """Shadow on the floor, which may be well below the floating buddy."""
    offset = (brain.world.ground - brain.y) / unit
    if offset < -4.0 or offset > max_offset:
        return
    fade = max(0.12, 1.0 - max(0.0, offset) / max_offset)
    if brain.state is State.SLEEP:
        fade *= 0.7
    shadow = QColor(color)
    shadow.setAlpha(int(58 * fade))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(shadow)
    painter.drawEllipse(
        QPointF(0.0, offset - 2.0), base_rx * fade, base_ry * fade
    )


class Mochi:
    """The round mint blob-cat."""

    def __init__(self, palette: Palette) -> None:
        self.palette = palette

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette

    # ------------------------------------------------------------ entry points
    def paint(
        self,
        painter: QPainter,
        brain: Brain,
        width: int,
        height: int,
        foot_pad: float = FOOT_PAD_UNITS,
    ) -> None:
        unit = max(0.1, width / CANVAS_W)
        painter.save()
        painter.translate(width / 2.0, height - foot_pad * unit)
        painter.scale(unit, unit)
        self.paint_scene(painter, brain, unit)
        painter.restore()

    def paint_scene(self, painter: QPainter, brain: Brain, unit: float) -> None:
        """Paint in canvas units; origin = the buddy's feet."""
        _paint_ground_shadow(painter, brain, unit, self.palette.outline)
        painter.save()
        bob = self._walk_bob(brain)
        # The window follows the buddy, so the feet are already at the origin;
        # only cosmetic bobbing is applied here.
        painter.translate(0.0, bob)
        extent_x, extent_y = self._squash(brain)
        painter.scale(float(brain.facing), 1.0)
        painter.scale(extent_x, extent_y)
        self._paint_tail(painter, brain)
        self._paint_ears(painter, brain)
        self._paint_feet(painter, brain)
        self._paint_body(painter, brain)
        self._paint_belly(painter, brain)
        self._paint_arms(painter, brain)
        self._paint_face(painter, brain)
        painter.restore()

    def paint_icon(self, painter: QPainter, brain: Brain) -> None:
        self._paint_ears(painter, brain)
        self._paint_body(painter, brain)
        self._paint_belly(painter, brain)
        self._paint_face(painter, brain)

    # --------------------------------------------------------------- animation
    def _walk_cycle(self, brain: Brain) -> float:
        if brain.state is State.SLEEP:
            return 0.0
        speed = 0.0
        if brain.state is State.WALK:
            speed = 9.0
        elif brain.state is State.RUN:
            speed = 14.0
        elif brain.state is State.DRAG:
            speed = 6.0
        return brain.anim_time * speed * max(0.6, brain.speed_scale)

    def _walk_bob(self, brain: Brain) -> float:
        if brain.state not in (State.WALK, State.RUN):
            return 0.0
        return -abs(math.sin(self._walk_cycle(brain))) * 1.8

    def _squash(self, brain: Brain) -> tuple[float, float]:
        if brain.state is State.LAND:
            duration = max(0.001, brain.tuning.land_duration)
            progress = min(1.0, brain.state_time / duration)
            amount = math.sin(math.pi * progress) * 0.26
            return 1.0 + amount, 1.0 - amount
        if brain.state is State.AIR:
            stretch = min(0.2, abs(brain.vy) / 1400.0)
            return 1.0 - stretch * 0.55, 1.0 + stretch
        if brain.state is State.SLEEP:
            breath = math.sin(brain.anim_time * 1.6) * 0.02
            return 1.0 + breath, 1.0 - breath
        breath = math.sin(brain.anim_time * 2.3) * 0.012
        return 1.0 + breath, 1.0 - breath

    # ----------------------------------------------------------------- drawing
    def _paint_tail(self, painter: QPainter, brain: Brain) -> None:
        phase = self._walk_cycle(brain)
        wag = math.sin(brain.anim_time * 4.6 + phase) * 7.0
        if brain.state is State.SLEEP:
            wag = math.sin(brain.anim_time * 1.6) * 2.0
        path = QPainterPath()
        path.moveTo(22.0, -14.0)
        path.quadTo(52.0, -10.0 + wag, 47.0, -40.0 + wag * 0.7)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_pen(self.palette.outline, 9.5))
        painter.drawPath(path)
        painter.setPen(_pen(self.palette.body_dark, 6.0))
        painter.drawPath(path)
        tip = QPointF(47.0, -40.0 + wag * 0.7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette.accent)
        painter.drawEllipse(tip, 5.2, 5.2)

    def _paint_ears(self, painter: QPainter, brain: Brain) -> None:
        droop = 8.0 if brain.state is State.SLEEP else 0.0
        for side in (-1, 1):
            sx = float(side)
            outer = QPainterPath()
            outer.moveTo(sx * 33.0, -60.0)
            outer.quadTo(sx * 37.0, -84.0 + droop, sx * 24.0, -95.0 + droop)
            outer.quadTo(sx * 10.0, -87.0 + droop * 0.5, sx * 7.0, -70.0)
            outer.closeSubpath()
            painter.setBrush(self.palette.body)
            painter.setPen(_pen(self.palette.outline, 2.6))
            painter.drawPath(outer)

            inner = QPainterPath()
            inner.moveTo(sx * 29.0, -66.0)
            inner.quadTo(sx * 31.0, -81.0 + droop, sx * 23.0, -88.0 + droop)
            inner.quadTo(sx * 14.0, -82.0 + droop * 0.5, sx * 12.0, -71.0)
            inner.closeSubpath()
            inner_color = QColor(self.palette.accent)
            inner_color.setAlpha(190)
            painter.setBrush(inner_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(inner)

    def _paint_feet(self, painter: QPainter, brain: Brain) -> None:
        phase = self._walk_cycle(brain)
        airborne = brain.state is State.AIR
        dangling = brain.state in (State.DRAG, State.CLIMB)
        for side in (-1, 1):
            swing = math.sin(phase + (0.0 if side < 0 else math.pi))
            lift = max(0.0, swing) * 4.0
            forward = swing * 3.0
            if airborne:
                lift, forward = 3.0, -side * 1.5
            elif dangling:
                lift, forward = 5.0, 0.0
            rect = QRectF(side * 15.0 - 9.0 + forward, -11.0 - lift, 18.0, 13.0)
            painter.setBrush(self.palette.body_dark)
            painter.setPen(_pen(self.palette.outline, 2.2))
            painter.drawRoundedRect(rect, 6.5, 6.5)

    def _paint_body(self, painter: QPainter, brain: Brain) -> None:
        path = QPainterPath()
        path.moveTo(-30.0, -4.0)
        path.cubicTo(-43.0, -24.0, -38.0, -63.0, -16.0, -76.0)
        path.cubicTo(-4.0, -84.0, 4.0, -84.0, 16.0, -76.0)
        path.cubicTo(38.0, -63.0, 43.0, -24.0, 30.0, -4.0)
        path.cubicTo(20.0, 3.0, -20.0, 3.0, -30.0, -4.0)
        path.closeSubpath()
        gradient = QLinearGradient(0.0, -80.0, 0.0, 0.0)
        gradient.setColorAt(0.0, self.palette.body)
        gradient.setColorAt(1.0, self.palette.body_dark)
        painter.setBrush(QBrush(gradient))
        painter.setPen(_pen(self.palette.outline, 2.8))
        painter.drawPath(path)

    def _paint_belly(self, painter: QPainter, brain: Brain) -> None:
        painter.setBrush(self.palette.belly)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(0.0, -26.0), 20.0, 16.0)

    def _paint_arms(self, painter: QPainter, brain: Brain) -> None:
        phase = self._walk_cycle(brain)
        airborne = brain.state is State.AIR
        for side in (-1, 1):
            swing = math.sin(phase + (0.0 if side < 0 else math.pi)) * 22.0
            angle = swing
            if airborne:
                angle = side * 150.0
            elif brain.state is State.SLEEP:
                angle = side * 8.0
            painter.save()
            painter.translate(side * 30.0, -28.0)
            painter.rotate(angle * side)
            painter.setBrush(self.palette.body)
            painter.setPen(_pen(self.palette.outline, 2.2))
            painter.drawRoundedRect(QRectF(-4.5, -3.0, 9.0, 20.0), 4.5, 4.5)
            painter.restore()

    def _paint_face(self, painter: QPainter, brain: Brain) -> None:
        look_x = brain.look[0] * brain.facing
        look_y = brain.look[1]
        sleeping = brain.state is State.SLEEP
        surprised = brain.state in (State.AIR, State.DRAG, State.CLIMB) and not sleeping

        blush = QColor(self.palette.blush)
        blush.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blush)
        painter.drawEllipse(QPointF(-25.0, -41.0), 6.5, 4.5)
        painter.drawEllipse(QPointF(25.0, -41.0), 6.5, 4.5)

        eye_r = 8.8 if surprised else 8.2
        pupil_r = 4.2 if surprised else 3.7
        for side in (-1, 1):
            cx = side * 13.0 + look_x * 2.4
            cy = -52.0 + look_y * 1.8
            if sleeping:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(_pen(self.palette.outline, 2.4))
                painter.drawArc(QRectF(cx - 6.5, cy - 3.5, 13.0, 9.0), 200 * 16, 140 * 16)
                continue

            painter.setBrush(QColor("#ffffff"))
            painter.setPen(_pen(self.palette.outline, 1.8))
            painter.drawEllipse(QPointF(cx, cy), eye_r, eye_r)

            pupil = QPointF(cx + look_x * 3.0, cy + look_y * 2.6)
            painter.setBrush(self.palette.eye)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pupil, pupil_r, pupil_r)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(
                QPointF(pupil.x() - pupil_r * 0.35, pupil.y() - pupil_r * 0.4),
                pupil_r * 0.32,
                pupil_r * 0.32,
            )

            if brain.blink > 0.01:
                painter.save()
                clip = QPainterPath()
                clip.addEllipse(QPointF(cx, cy), eye_r + 0.6, eye_r + 0.6)
                painter.setClipPath(clip)
                cover = QRectF(
                    cx - eye_r - 1.0,
                    cy - eye_r - 1.0,
                    2 * eye_r + 2.0,
                    (2 * eye_r + 2.0) * min(1.0, brain.blink),
                )
                painter.setBrush(self.palette.body)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(cover)
                painter.restore()
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(_pen(self.palette.outline, 1.8))
                painter.drawEllipse(QPointF(cx, cy), eye_r, eye_r)

        nose = QPainterPath()
        nose.moveTo(-3.4, -45.0)
        nose.lineTo(3.4, -45.0)
        nose.quadTo(0.0, -39.6, -3.4, -45.0)
        nose.closeSubpath()
        painter.setBrush(self.palette.accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(nose)

        if surprised:
            painter.setBrush(QColor("#6d3345"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(0.0, -38.5), 3.6, 4.6)
        else:
            mouth = QPainterPath()
            mouth.moveTo(-6.6, -41.5)
            mouth.quadTo(-3.3, -37.2, 0.0, -41.5)
            mouth.quadTo(3.3, -37.2, 6.6, -41.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(_pen(self.palette.outline, 1.8))
            painter.drawPath(mouth)

        whisker = QColor(self.palette.outline)
        whisker.setAlpha(120)
        painter.setPen(_pen(whisker, 1.3))
        for side in (-1, 1):
            for offset in (-3.0, 2.0):
                painter.drawLine(
                    QPointF(side * 26.0, -42.0 + offset),
                    QPointF(side * 40.0, -45.0 + offset * 1.6),
                )


class Ghost:
    """Boo-ombastic: a small, floaty, dance-loving ghost."""

    def __init__(self, palette: Palette) -> None:
        self.palette = palette

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette

    def paint(
        self,
        painter: QPainter,
        brain: Brain,
        width: int,
        height: int,
        foot_pad: float = FOOT_PAD_UNITS,
    ) -> None:
        unit = max(0.1, width / CANVAS_W)
        painter.save()
        painter.translate(width / 2.0, height - foot_pad * unit)
        painter.scale(unit, unit)
        self.paint_scene(painter, brain, unit)
        painter.restore()

    def paint_scene(self, painter: QPainter, brain: Brain, unit: float) -> None:
        _paint_ground_shadow(
            painter, brain, unit, self.palette.outline, base_rx=25.0, base_ry=5.0
        )
        painter.save()

        dancing = brain.state is State.DANCE
        sleeping = brain.state is State.SLEEP
        float_bob = math.sin(brain.anim_time * 2.4) * 2.6
        if sleeping:
            float_bob = math.sin(brain.anim_time * 1.2) * 1.2 + 2.0
        painter.translate(0.0, float_bob)
        if dancing:
            swing = math.sin(brain.anim_time * 7.5)
            painter.translate(0.0, -abs(swing) * 7.0)
            painter.rotate(swing * 11.0)

        sx, sy = self._squash(brain)
        painter.scale(float(brain.facing), 1.0)
        painter.scale(sx, sy)
        if sleeping:
            painter.setOpacity(0.82)

        self._paint_arms(painter, brain)
        self._paint_body(painter, brain)
        self._paint_face(painter, brain)
        painter.restore()

    def paint_icon(self, painter: QPainter, brain: Brain) -> None:
        self._paint_body(painter, brain)
        self._paint_face(painter, brain)

    def _squash(self, brain: Brain) -> tuple[float, float]:
        if brain.state is State.LAND:
            duration = max(0.001, brain.tuning.land_duration)
            progress = min(1.0, brain.state_time / duration)
            amount = math.sin(math.pi * progress) * 0.22
            return 1.0 + amount, 1.0 - amount
        if brain.state is State.AIR:
            stretch = min(0.16, abs(brain.vy) / 1600.0)
            return 1.0 - stretch * 0.5, 1.0 + stretch
        if brain.state is State.CLIMB:
            return 1.0, 1.04
        breath = math.sin(brain.anim_time * 2.0) * 0.018
        return 1.0 + breath, 1.0 - breath

    # ----------------------------------------------------------------- drawing
    def _body_path(self, brain: Brain) -> QPainterPath:
        half = 32.0
        top = -92.0
        bottom = -12.0
        path = QPainterPath()
        path.moveTo(-half, bottom)
        path.lineTo(-half, -54.0)
        path.cubicTo(-half, -78.0, -16.0, top, 0.0, top)
        path.cubicTo(16.0, top, half, -78.0, half, -54.0)
        path.lineTo(half, bottom)
        segments = 3
        step = (2.0 * half) / segments
        for index in range(segments):
            x_start = half - index * step
            x_end = x_start - step
            center = (x_start + x_end) / 2.0
            wobble = math.sin(brain.anim_time * 4.2 + index * 1.9) * 3.6
            path.quadTo(center, bottom + 8.5 + wobble, x_end, bottom)
        path.closeSubpath()
        return path

    def _paint_body(self, painter: QPainter, brain: Brain) -> None:
        path = self._body_path(brain)
        gradient = QLinearGradient(0.0, -92.0, 0.0, -8.0)
        body = QColor(self.palette.body)
        top_color = QColor(body)
        top_color.setAlpha(242)
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, self.palette.body_dark)
        painter.setBrush(QBrush(gradient))
        painter.setPen(_pen(self.palette.outline, 2.6))
        painter.drawPath(path)

        glow = QColor(self.palette.belly)
        glow.setAlpha(70)
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(-9.0, -58.0), 13.0, 17.0)

    def _paint_arms(self, painter: QPainter, brain: Brain) -> None:
        dancing = brain.state is State.DANCE
        airborne = brain.state is State.AIR
        wave = math.sin(brain.anim_time * 8.5)
        for side in (-1, 1):
            angle = side * 12.0
            if dancing:
                angle = side * (150.0 + wave * 25.0 * side)
            elif airborne:
                angle = side * 155.0
            elif brain.state is State.SLEEP:
                angle = side * 6.0
            painter.save()
            painter.translate(side * 29.0, -42.0)
            painter.rotate(angle * side)
            painter.setBrush(self.palette.body)
            painter.setPen(_pen(self.palette.outline, 2.2))
            painter.drawRoundedRect(QRectF(-4.2, -3.0, 8.4, 19.0), 4.2, 4.2)
            painter.restore()

    def _paint_face(self, painter: QPainter, brain: Brain) -> None:
        look_x = brain.look[0] * brain.facing
        look_y = brain.look[1]
        sleeping = brain.state is State.SLEEP
        dancing = brain.state is State.DANCE
        surprised = brain.state in (State.AIR, State.DRAG, State.CLIMB)
        happy_closed = dancing and int(brain.anim_time * 4.0) % 2 == 0

        blush = QColor(self.palette.blush)
        blush.setAlpha(115)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blush)
        painter.drawEllipse(QPointF(-22.0, -47.0), 6.0, 4.0)
        painter.drawEllipse(QPointF(22.0, -47.0), 6.0, 4.0)

        for side in (-1, 1):
            cx = side * 11.5 + look_x * 2.2
            cy = -59.0 + look_y * 2.0
            if sleeping or happy_closed:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(_pen(self.palette.outline, 2.4))
                painter.drawArc(QRectF(cx - 6.0, cy - 3.0, 12.0, 8.5), 200 * 16, 140 * 16)
                continue
            rx = 5.6 if surprised else 5.0
            ry = 8.6 if surprised else 7.2
            if brain.blink > 0.05:
                ry *= max(0.08, 1.0 - brain.blink)
            painter.setBrush(self.palette.eye)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), rx, ry)
            highlight = QColor("#ffffff")
            highlight.setAlpha(230)
            painter.setBrush(highlight)
            painter.drawEllipse(
                QPointF(cx - rx * 0.35, cy - ry * 0.42), rx * 0.30, ry * 0.26
            )

        # mouth: singing while dancing, small smile otherwise
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_pen(self.palette.outline, 1.8))
        if dancing:
            painter.setBrush(QColor("#6d3345"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(0.0, -45.0), 3.4, 4.4)
        else:
            mouth = QPainterPath()
            mouth.moveTo(-5.4, -46.5)
            mouth.quadTo(-2.7, -42.8, 0.0, -46.5)
            mouth.quadTo(2.7, -42.8, 5.4, -46.5)
            painter.drawPath(mouth)


def make_character(species: str, palette: Palette):
    """Factory: returns the renderer for a species key."""
    if species == "ghost":
        return Ghost(palette)
    return Mochi(palette)


# Backwards-compatible alias (the first character was simply called Character).
Character = Mochi


def icon_pixmap(species: str, palette: Palette, size: int = 128, dpr: float = 1.0) -> QPixmap:
    """Render a buddy's portrait as an application/tray icon."""
    device_size = max(16, int(size * dpr))
    pixmap = QPixmap(device_size, device_size)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    world = World(left=-500.0, right=500.0, ground=0.0)
    brain = Brain(world=world, x=0.0, y=0.0, state=State.IDLE)
    character = make_character(species, palette)
    unit = device_size / 118.0
    painter.translate(device_size / 2.0, device_size * 1.02)
    painter.scale(unit, unit)
    character.paint_icon(painter, brain)
    painter.end()
    return pixmap
