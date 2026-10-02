#!/usr/bin/env python3
"""Render a pose/theme sheet to PNG for visual inspection (offscreen)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen  # noqa: E402

from desktop_buddy.behavior import Brain, State, World  # noqa: E402
from desktop_buddy.character import CANVAS_H, CANVAS_W, Character, Palette  # noqa: E402
from desktop_buddy.config import THEMES  # noqa: E402
from desktop_buddy.effects import ParticleSystem  # noqa: E402

CELL_W, CELL_H = 200, 300


def make_brain(state: State, **kwargs: object) -> Brain:
    world = World(left=-400.0, right=400.0, ground=0.0)
    brain = Brain(world=world, x=0.0, y=0.0, state=state)
    for key, value in kwargs.items():
        setattr(brain, key, value)
    return brain


def main() -> int:
    app = QGuiApplication([])  # noqa: F841
    poses: list[tuple[str, Brain]] = [
        ("idle", make_brain(State.IDLE, anim_time=0.4, look=(0.2, 0.1))),
        ("walk", make_brain(State.WALK, anim_time=0.42, look=(0.6, 0.0))),
        ("jump", make_brain(State.AIR, y=-90.0, vy=-260.0, look=(0.0, -0.4))),
        ("land", make_brain(State.LAND, state_time=0.07, last_impact=650.0)),
        ("sleep", make_brain(State.SLEEP, anim_time=1.1)),
        ("drag", make_brain(State.DRAG, y=-120.0, look=(0.0, -0.8))),
    ]
    themes = list(THEMES.items())[:5]
    cols = max(len(poses), len(themes))
    rows = 2
    image = QImage(
        CELL_W * cols, CELL_H * rows, QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(QColor("#eef1f5"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    label_font = QFont("DejaVu Sans", 11)
    label_font.setBold(True)

    for index, (name, brain) in enumerate(poses):
        x0 = index * CELL_W
        painter.save()
        painter.translate(x0, 0)
        painter.setPen(QPen(QColor("#c9ced8"), 1.0))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(6, 6, CELL_W - 12, CELL_H - 12), 10, 10)
        painter.setPen(QColor("#222833"))
        painter.setFont(label_font)
        painter.drawText(QRectF(12, 10, CELL_W - 24, 24), Qt.AlignmentFlag.AlignLeft, name)
        character = Character(Palette.from_colors(THEMES["mint"]))
        scale = 1.15
        width = int(CANVAS_W * scale)
        height = int(CANVAS_H * scale)
        painter.save()
        painter.translate((CELL_W - width) / 2.0, CELL_H - 34 - height)
        character.paint(painter, brain, width, height)
        painter.restore()
        particles = ParticleSystem()
        if name == "jump":
            particles.emit("sparkles", 0.0, -20.0, character.palette)
        elif name == "land":
            particles.emit("dust", 0.0, -2.0, character.palette)
        elif name == "sleep":
            particles.emit("zzz", 24.0, -78.0, character.palette)
        particles.update(0.25)
        painter.save()
        painter.translate((CELL_W - width) / 2.0, CELL_H - 34)
        painter.scale(scale, scale)
        particles.paint(painter)
        painter.restore()
        painter.restore()

    for index, (key, colors) in enumerate(themes):
        x0 = index * CELL_W
        painter.save()
        painter.translate(x0, CELL_H)
        painter.setPen(QPen(QColor("#c9ced8"), 1.0))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(6, 6, CELL_W - 12, CELL_H - 12), 10, 10)
        painter.setPen(QColor("#222833"))
        painter.setFont(label_font)
        painter.drawText(QRectF(12, 10, CELL_W - 24, 24), Qt.AlignmentFlag.AlignLeft, colors["label"])
        character = Character(Palette.from_colors(colors))
        brain = make_brain(State.IDLE, anim_time=0.3, look=(-0.2, 0.1))
        scale = 1.15
        width = int(CANVAS_W * scale)
        height = int(CANVAS_H * scale)
        painter.translate((CELL_W - width) / 2.0, CELL_H - 34 - height)
        character.paint(painter, brain, width, height)
        painter.restore()

    painter.end()
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/buddy-preview.png")
    image.save(str(output))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
