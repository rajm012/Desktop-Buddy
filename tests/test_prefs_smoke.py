"""Offscreen smoke test: the preferences dialog builds and renders."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.config import Config  # noqa: E402
from desktop_buddy.prefs import PreferencesDialog  # noqa: E402


class _StubController:
    """Accepts every controller call the dialog makes."""

    def __init__(self) -> None:
        self.config = Config()

    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None


class PreferencesSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_builds_with_reminder_controls(self) -> None:
        dialog = PreferencesDialog(_StubController())
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.check_reminders is not None)
        self.assertIn("lunch", dialog.meal_widgets)
        self.assertEqual(dialog.water_slider.minimum(), 10)
        dialog.close()

    def test_dialog_survives_theme_and_species_change(self) -> None:
        controller = _StubController()
        dialog = PreferencesDialog(controller)
        dialog.show()
        controller.config.theme = "peach"
        controller.config.species = "mochi"
        dialog.preview.refresh()
        self.app.processEvents()
        dialog.close()


if __name__ == "__main__":
    unittest.main()
