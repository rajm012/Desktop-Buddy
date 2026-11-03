"""Offscreen smoke test: the preferences dialog builds and renders."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from desktop_buddy.config import Config  # noqa: E402
from desktop_buddy.focus import FocusEngine, FocusSettings  # noqa: E402
from desktop_buddy.platforms.base import GenericPlatformBackend  # noqa: E402
from desktop_buddy.platforms.linux import LinuxBackend  # noqa: E402
from desktop_buddy.prefs import (  # noqa: E402
    ActionEditDialog,
    OnboardingDialog,
    PreferencesDialog,
    ReminderEditDialog,
)


class _StubController:
    """Accepts every controller call the dialog makes."""

    def __init__(self, backend=None) -> None:  # noqa: ANN001
        self.config = Config()
        self.backend = backend or GenericPlatformBackend()
        self._focus = FocusEngine(FocusSettings.from_config(self.config))

    def autostart_active(self) -> bool:
        return False

    def apply_snapshot(self, snapshot: dict) -> None:
        restored = Config.from_dict(snapshot)
        self.config.__dict__.update(restored.__dict__)

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
        self.assertGreaterEqual(dialog.reminder_list.count(), 7)
        self.assertTrue(dialog.reminder_add_button.isEnabled())
        self.assertTrue(dialog.action_add_button.isEnabled())
        self.assertEqual(dialog.focus_minutes.value(), 25)
        self.assertTrue(dialog.focus_start_button.isEnabled())
        self.assertFalse(dialog.check_click.isEnabled())
        self.assertIn("unavailable", dialog.capability_notice.text().lower())
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            list(PreferencesDialog.TAB_NAMES),
        )
        self.assertLessEqual(dialog.height(), 700)
        dialog.close()

    def test_reminder_editor_parses_local_schedule(self) -> None:
        dialog = ReminderEditDialog(_StubController())
        dialog.title_edit.setText("Stand up")
        dialog.schedule_edit.setText("weekdays at 9")
        definition = dialog.definition()
        self.assertEqual(definition["recurrence"], "weekdays")
        self.assertEqual(definition["time"], "09:00")
        self.assertEqual(definition["weekdays"], [0, 1, 2, 3, 4])
        dialog.close()

    def test_editing_command_target_clears_prior_approval(self) -> None:
        dialog = ActionEditDialog(
            {
                "id": "trusted",
                "name": "Trusted",
                "type": "command",
                "target": "printf ok",
                "enabled": True,
                "approved": True,
            }
        )
        self.assertTrue(dialog.approve_check.isChecked())
        dialog.target_edit.setText("printf changed")
        dialog._target_changed(dialog.target_edit.text())  # noqa: SLF001
        self.assertFalse(dialog.approve_check.isChecked())
        dialog.close()

    def test_dialog_survives_theme_and_species_change(self) -> None:
        controller = _StubController()
        dialog = PreferencesDialog(controller)
        dialog.show()
        controller.config.theme = "peach"
        controller.config.species = "robot"
        dialog.preview.refresh()
        self.app.processEvents()
        dialog.close()

    def test_wayland_limitations_are_explained(self) -> None:
        backend = LinuxBackend(
            env={"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
        )
        dialog = PreferencesDialog(_StubController(backend))
        self.assertFalse(dialog.check_top.isEnabled())
        self.assertFalse(dialog.check_perch.isEnabled())
        self.assertIn("Wayland", dialog.capability_notice.text())
        dialog.close()

    def test_cancel_restores_the_opening_snapshot(self) -> None:
        controller = _StubController()
        dialog = PreferencesDialog(controller)
        controller.config.scale = 1.6
        controller.config.reduced_motion = True
        dialog.reject()
        self.assertEqual(controller.config.scale, Config().scale)
        self.assertFalse(controller.config.reduced_motion)

    def test_onboarding_contains_phase_two_choices(self) -> None:
        dialog = OnboardingDialog(_StubController())
        self.assertGreater(dialog.species_combo.count(), 1)
        self.assertEqual(dialog.scale_slider.minimum(), 50)
        self.assertEqual(dialog.active_start.displayFormat(), "HH:mm")
        self.assertFalse(dialog.autostart.isEnabled())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
