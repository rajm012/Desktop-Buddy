"""Offscreen tests for window placement (drag anywhere + perching)."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.behavior import Perch  # noqa: E402
from desktop_buddy.character import CANVAS_W, FOOT_PAD_UNITS  # noqa: E402
from desktop_buddy.config import Config  # noqa: E402
from desktop_buddy.platforms.base import GenericPlatformBackend  # noqa: E402
from desktop_buddy.window import BuddyWindow  # noqa: E402


class WindowMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        config = Config()
        config.species = "ghost"
        config.perch_on_windows = False
        self.window = BuddyWindow(config, backend=GenericPlatformBackend())

    def tearDown(self) -> None:
        self.window.close()

    def _pad_px(self) -> float:
        return FOOT_PAD_UNITS * (self.window.width() / CANVAS_W)

    def _assert_buddy_at_brain_position(self) -> None:
        """The buddy's feet must land where the brain says, on screen."""
        drawn_feet = self.window.y() + self.window._feet_local_px
        self.assertAlmostEqual(drawn_feet, self.window._brain.y, delta=2.0)

    def test_buddy_reaches_screen_top_while_window_stays_on_screen(self) -> None:
        self.window._brain.x = 400.0
        self.window._brain.y = 60.0
        self.window._move_window()
        expected_x = round(400.0 - self.window.width() / 2.0)
        # Mutter clamps windows at the screen top, so the window stays at 0
        # and the buddy's foot offset inside the window absorbs the difference.
        self.assertEqual((self.window.x(), self.window.y()), (expected_x, 0))
        self.assertAlmostEqual(self.window._feet_local_px, 60.0, delta=1.0)
        self._assert_buddy_at_brain_position()

    def test_window_follows_buddy_to_bottom(self) -> None:
        self.window._brain.x = 200.0
        self.window._brain.y = float(self.window._brain.world.ground)
        self.window._move_window()
        screen = self.window._brain.screen_world
        self.assertLessEqual(
            self.window.y(), int(screen.ground) + 1 - self.window.height()
        )
        self._assert_buddy_at_brain_position()

    def test_perched_window_sits_on_window_edge(self) -> None:
        perch = Perch(x=450.0, y=300.0, left=200.0, right=900.0, kind="browser")
        self.assertTrue(self.window._brain.set_perch(perch))
        for _ in range(20 * 60):
            self.window._brain.step(1.0 / 60.0)
            if self.window._brain.perched:
                break
        self.assertTrue(self.window._brain.perched)
        self.window._move_window()
        expected_y = round(300.0 - self.window.height() + self._pad_px())
        self.assertEqual(self.window.y(), expected_y)
        self._assert_buddy_at_brain_position()


if __name__ == "__main__":
    unittest.main()
