
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen  # noqa: E402

from desktop_buddy.behavior import Brain, State, World  # noqa: E402
from desktop_buddy.character import (  # noqa: E402
    CANVAS_H,
    CANVAS_W,
    Palette,
    make_character,
)
from desktop_buddy.config import THEMES  # noqa: E402
from desktop_buddy.effects import ParticleSystem  # noqa: E402

CELL_W, CELL_H = 210, 310


def make_brain(state: State, **kwargs: object) -> Brain:
    world = World(left=-400.0, right=400.0, ground=0.0)
    brain = Brain(world=world, x=0.0, y=0.0, state=state)
    for key, value in kwargs.items():
        setattr(brain, key, value)
    return brain


def poses() -> list[tuple[str, Brain, list[tuple[str, float, float]]]]:
    return [
        ("idle", make_brain(State.IDLE, anim_time=0.4, look=(0.2, 0.1)), []),
        ("walk", make_brain(State.WALK, anim_time=0.42, look=(0.6, 0.0)), []),
        ("run", make_brain(State.RUN, anim_time=0.31, look=(0.8, -0.1)), []),
        ("jump", make_brain(State.AIR, vy=-260.0), [("sparkles", 0.0, -20.0)]),
        ("fall", make_brain(State.AIR, anim_time=0.35, vy=320.0), []),
        ("land", make_brain(State.LAND, state_time=0.07, last_impact=650.0), [("dust", 0.0, -2.0)]),
        ("dance", make_brain(State.DANCE, anim_time=0.62, can_dance=True), [("notes", 8.0, -80.0), ("hearts", 0.0, -64.0)]),
        ("sleep", make_brain(State.SLEEP, anim_time=1.1), [("zzz", 24.0, -78.0)]),
        ("drag", make_brain(State.DRAG, look=(0.0, -0.8)), [("wisp", -18.0, -38.0)]),
    ]


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/buddy-preview.png")
    species = sys.argv[2] if len(sys.argv) > 2 else "robot"
    palette_colors = THEMES["mint"]
    if species == "ghost":
        palette_colors = THEMES["lavender"]
    elif species == "robot":
        palette_colors = THEMES["circuit"]

    app = QGuiApplication([])  # noqa: F841
    sheet = poses()
    image = QImage(CELL_W * len(sheet), CELL_H, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#eef1f5"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    label_font = QFont("DejaVu Sans", 11)
    label_font.setBold(True)
    palette = Palette.from_colors(palette_colors)
    character = make_character(species, palette)
    scale = 1.1

    for index, (name, brain, effects) in enumerate(sheet):
        painter.save()
        painter.translate(index * CELL_W, 0)
        painter.setPen(QPen(QColor("#c9ced8"), 1.0))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(6, 6, CELL_W - 12, CELL_H - 12), 10, 10)
        painter.setPen(QColor("#222833"))
        painter.setFont(label_font)
        painter.drawText(QRectF(12, 10, CELL_W - 24, 24), Qt.AlignmentFlag.AlignLeft, name)

        width = int(CANVAS_W * scale)
        height = int(CANVAS_H * scale)
        offset_x = (CELL_W - width) / 2.0
        offset_y = CELL_H - 34 - height
        painter.save()
        painter.translate(offset_x, offset_y)
        character.paint(painter, brain, width, height)
        painter.restore()

        particles = ParticleSystem()
        for kind, px, py in effects:
            particles.emit(kind, px, py, palette)
        particles.update(0.25)
        painter.save()
        painter.translate(
            offset_x + width / 2.0, offset_y + height - 18.0 * scale
        )
        painter.scale(scale, scale)
        particles.paint(painter)
        painter.restore()
        painter.restore()

    painter.end()
    image.save(str(output))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
