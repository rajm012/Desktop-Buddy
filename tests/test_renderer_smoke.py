"""Offscreen smoke tests for every character and colour theme."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.behavior import Brain, State, World  # noqa: E402
from desktop_buddy.character import Palette, make_character  # noqa: E402
from desktop_buddy.config import SPECIES, THEMES  # noqa: E402


class RendererSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_every_character_and_theme_renders_pixels(self) -> None:
        for species in SPECIES:
            for theme, colors in THEMES.items():
                with self.subTest(species=species, theme=theme):
                    image = QImage(168, 192, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    brain = Brain(
                        world=World(left=-400.0, right=400.0, ground=0.0),
                        state=State.IDLE,
                    )
                    character = make_character(species, Palette.from_colors(colors))
                    character.paint(painter, brain, 168, 192)
                    painter.end()

                    opaque_pixels = sum(
                        image.pixelColor(x, y).alpha() > 0
                        for y in range(image.height())
                        for x in range(image.width())
                    )
                    self.assertGreater(opaque_pixels, 500)


if __name__ == "__main__":
    unittest.main()
