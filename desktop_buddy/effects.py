"""Small particle system: dust, sparkles, hearts, sleep bubbles, notes, wisps."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from .character import Palette


@dataclass
class Particle:
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color: QColor
    wobble: float = 0.0
    rotation: float = 0.0
    spin: float = 0.0

    @property
    def progress(self) -> float:
        return 1.0 - max(0.0, min(1.0, self.life / self.max_life))


class ParticleSystem:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.items: list[Particle] = []

    def clear(self) -> None:
        self.items.clear()

    # ------------------------------------------------------------------ emitters
    def emit(self, kind: str, x: float, y: float, palette: Palette) -> None:
        if kind == "dust":
            self._emit_dust(x, y, palette)
        elif kind == "hearts":
            self._emit_hearts(x, y, palette)
        elif kind == "sparkles":
            self._emit_sparkles(x, y, palette)
        elif kind == "zzz":
            self._emit_zzz(x, y, palette)
        elif kind == "notes":
            self._emit_note(x, y, palette)
        elif kind == "wisp":
            self._emit_wisp(x, y, palette)
        elif kind == "drops":
            self._emit_drops(x, y, palette)

    def _emit_dust(self, x: float, y: float, palette: Palette) -> None:
        for _ in range(self.rng.randint(6, 9)):
            side = self.rng.choice((-1, 1))
            color = QColor(palette.belly if self.rng.random() < 0.5 else palette.body_dark)
            self.items.append(
                Particle(
                    kind="dust",
                    x=x + self.rng.uniform(-16.0, 16.0),
                    y=y + self.rng.uniform(-4.0, 2.0),
                    vx=side * self.rng.uniform(28.0, 78.0),
                    vy=-self.rng.uniform(10.0, 58.0),
                    life=0.0,
                    max_life=self.rng.uniform(0.35, 0.6),
                    size=self.rng.uniform(3.0, 6.5),
                    color=color,
                )
            )
        for particle in self.items[-9:]:
            particle.life = particle.max_life

    def _emit_hearts(self, x: float, y: float, palette: Palette) -> None:
        for _ in range(self.rng.randint(4, 6)):
            color = QColor(palette.accent if self.rng.random() < 0.6 else palette.blush)
            self.items.append(
                Particle(
                    kind="heart",
                    x=x + self.rng.uniform(-16.0, 16.0),
                    y=y + self.rng.uniform(-8.0, 8.0),
                    vx=self.rng.uniform(-16.0, 16.0),
                    vy=-self.rng.uniform(45.0, 80.0),
                    life=self.rng.uniform(0.9, 1.4),
                    max_life=1.4,
                    size=self.rng.uniform(4.5, 7.5),
                    color=color,
                    wobble=self.rng.uniform(0.0, math.tau),
                )
            )

    def _emit_sparkles(self, x: float, y: float, palette: Palette) -> None:
        for _ in range(self.rng.randint(7, 10)):
            angle = self.rng.uniform(0.0, math.tau)
            speed = self.rng.uniform(45.0, 130.0)
            self.items.append(
                Particle(
                    kind="sparkle",
                    x=x + math.cos(angle) * 10.0,
                    y=y + math.sin(angle) * 10.0,
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed - 40.0,
                    life=self.rng.uniform(0.45, 0.85),
                    max_life=0.85,
                    size=self.rng.uniform(2.0, 4.2),
                    color=QColor(palette.accent),
                    spin=self.rng.uniform(-4.0, 4.0),
                    rotation=self.rng.uniform(0.0, math.pi),
                )
            )

    def _emit_zzz(self, x: float, y: float, palette: Palette) -> None:
        color = QColor(palette.outline)
        self.items.append(
            Particle(
                kind="zzz",
                x=x,
                y=y,
                vx=self.rng.uniform(10.0, 18.0),
                vy=-self.rng.uniform(14.0, 22.0),
                life=1.7,
                max_life=1.7,
                size=self.rng.uniform(8.0, 11.0),
                color=color,
                wobble=self.rng.uniform(0.0, math.tau),
            )
        )

    def _emit_note(self, x: float, y: float, palette: Palette) -> None:
        color = QColor(palette.accent)
        if self.rng.random() < 0.4:
            color = QColor(palette.body_dark)
        self.items.append(
            Particle(
                kind="note",
                x=x + self.rng.uniform(-8.0, 8.0),
                y=y,
                vx=self.rng.uniform(-14.0, 22.0),
                vy=-self.rng.uniform(34.0, 52.0),
                life=self.rng.uniform(1.0, 1.5),
                max_life=1.5,
                size=self.rng.uniform(9.0, 13.0),
                color=color,
                wobble=self.rng.uniform(0.0, math.tau),
            )
        )

    def _emit_wisp(self, x: float, y: float, palette: Palette) -> None:
        color = QColor(palette.belly)
        color.setAlpha(150)
        self.items.append(
            Particle(
                kind="wisp",
                x=x + self.rng.uniform(-6.0, 6.0),
                y=y + self.rng.uniform(-6.0, 6.0),
                vx=self.rng.uniform(-46.0, -12.0),
                vy=self.rng.uniform(-8.0, 10.0),
                life=self.rng.uniform(0.5, 0.9),
                max_life=0.9,
                size=self.rng.uniform(4.0, 7.5),
                color=color,
                wobble=self.rng.uniform(0.0, math.tau),
            )
        )

    def _emit_drops(self, x: float, y: float, palette: Palette) -> None:
        blue = QColor("#54c7ec")
        for _ in range(self.rng.randint(9, 13)):
            color = QColor(blue)
            color.setAlpha(self.rng.randint(150, 230))
            self.items.append(
                Particle(
                    kind="drop",
                    x=x + self.rng.uniform(-34.0, 34.0),
                    y=y + self.rng.uniform(-18.0, 6.0),
                    vx=self.rng.uniform(-24.0, 24.0),
                    vy=-self.rng.uniform(90.0, 200.0),
                    life=self.rng.uniform(0.7, 1.2),
                    max_life=1.2,
                    size=self.rng.uniform(3.0, 5.5),
                    color=color,
                )
            )

    # ------------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        alive: list[Particle] = []
        for particle in self.items:
            particle.life -= dt
            if particle.life <= 0.0:
                continue
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            if particle.kind == "dust":
                particle.vy += 90.0 * dt
                particle.vx *= max(0.0, 1.0 - dt * 2.6)
            elif particle.kind == "heart":
                particle.vy += 12.0 * dt
                particle.x += math.sin(
                    particle.progress * 9.0 + particle.wobble
                ) * 14.0 * dt
            elif particle.kind == "sparkle":
                particle.vy += 150.0 * dt
                particle.rotation += particle.spin * dt
            elif particle.kind == "zzz":
                particle.x += math.sin(particle.progress * 6.0) * 6.0 * dt
            elif particle.kind == "note":
                particle.x += math.sin(
                    particle.progress * 7.0 + particle.wobble
                ) * 12.0 * dt
                particle.vy -= 6.0 * dt
            elif particle.kind == "wisp":
                particle.vy += 8.0 * dt
                particle.vx *= max(0.0, 1.0 - dt * 1.8)
            elif particle.kind == "drop":
                particle.vy += 420.0 * dt
            if particle.y > 26.0:
                continue
            alive.append(particle)
        self.items = alive

    # -------------------------------------------------------------------- paint
    def paint(self, painter: QPainter) -> None:
        for particle in self.items:
            alpha = int(255 * (1.0 - particle.progress) ** 0.8)
            if alpha <= 2:
                continue
            painter.save()
            painter.translate(particle.x, particle.y)
            if particle.kind == "dust":
                self._paint_dust(painter, particle, alpha)
            elif particle.kind == "heart":
                self._paint_heart(painter, particle, alpha)
            elif particle.kind == "sparkle":
                painter.rotate(math.degrees(particle.rotation))
                self._paint_sparkle(painter, particle, alpha)
            elif particle.kind == "zzz":
                self._paint_zzz(painter, particle, alpha)
            elif particle.kind == "note":
                self._paint_note(painter, particle, alpha)
            elif particle.kind == "wisp":
                self._paint_wisp(painter, particle, alpha)
            elif particle.kind == "drop":
                self._paint_drop(painter, particle, alpha)
            painter.restore()

    def _paint_dust(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        grow = 1.0 + particle.progress * 0.8
        painter.drawEllipse(QPointF(0.0, 0.0), particle.size * grow, particle.size * grow)

    def _paint_heart(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(alpha)
        size = particle.size
        path = QPainterPath()
        path.moveTo(0.0, size * 0.9)
        path.cubicTo(-size * 1.5, -size * 0.2, -size * 0.7, -size * 1.5, 0.0, -size * 0.55)
        path.cubicTo(size * 0.7, -size * 1.5, size * 1.5, -size * 0.2, 0.0, size * 0.9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    def _paint_sparkle(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(alpha)
        size = particle.size
        path = QPainterPath()
        path.moveTo(0.0, -size)
        path.quadTo(size * 0.2, -size * 0.2, size, 0.0)
        path.quadTo(size * 0.2, size * 0.2, 0.0, size)
        path.quadTo(-size * 0.2, size * 0.2, -size, 0.0)
        path.quadTo(-size * 0.2, -size * 0.2, 0.0, -size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    def _paint_zzz(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(alpha)
        painter.setPen(QPen(color))
        font = QFont("DejaVu Sans", int(particle.size))
        font.setBold(True)
        painter.setFont(font)
        letter = "Z" if int(particle.progress * 4) % 2 == 0 else "z"
        painter.drawText(
            QRectF(-12.0, -12.0, 24.0, 24.0),
            Qt.AlignmentFlag.AlignCenter,
            letter,
        )

    def _paint_note(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(alpha)
        painter.setPen(QPen(color))
        font = QFont("DejaVu Sans", int(particle.size))
        font.setBold(True)
        painter.setFont(font)
        glyph = "♪" if int(particle.progress * 5) % 2 == 0 else "♫"
        painter.drawText(
            QRectF(-12.0, -12.0, 24.0, 24.0),
            Qt.AlignmentFlag.AlignCenter,
            glyph,
        )

    def _paint_wisp(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(min(alpha, 120))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        grow = 1.0 + particle.progress * 1.4
        painter.drawEllipse(
            QPointF(0.0, 0.0), particle.size * grow, particle.size * grow * 0.8
        )

    def _paint_drop(self, painter: QPainter, particle: Particle, alpha: int) -> None:
        color = QColor(particle.color)
        color.setAlpha(alpha)
        size = particle.size
        path = QPainterPath()
        path.moveTo(0.0, -size * 1.6)
        path.cubicTo(size * 0.95, -size * 0.25, size * 0.85, size, 0.0, size)
        path.cubicTo(-size * 0.85, size, -size * 0.95, -size * 0.25, 0.0, -size * 1.6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        highlight = QColor(255, 255, 255, min(200, alpha))
        painter.setBrush(highlight)
        painter.drawEllipse(
            QPointF(-size * 0.25, size * 0.15), size * 0.22, size * 0.3
        )
