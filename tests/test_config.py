"""Unit tests for configuration and platform helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from desktop_buddy.config import THEMES, Config
from desktop_buddy.platform_utils import autostart_enabled, set_autostart


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        config = Config()
        config.normalize()
        self.assertIn(config.theme, THEMES)
        self.assertGreater(config.scale, 0.0)
        self.assertGreater(config.fps, 0)

    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            original = Config()
            original.scale = 1.2
            original.theme = "peach"
            original.name = "Biscuit"
            original.save(path)
            loaded = Config.load(path)
            self.assertEqual(loaded.scale, 1.2)
            self.assertEqual(loaded.theme, "peach")
            self.assertEqual(loaded.name, "Biscuit")

    def test_invalid_values_are_normalized(self) -> None:
        config = Config.from_dict(
            {"scale": 99, "speed": -5, "fps": "abc", "theme": "neon", "name": ""}
        )
        self.assertEqual(config.scale, 1.8)
        self.assertEqual(config.speed, 0.4)
        self.assertEqual(config.fps, 30)
        self.assertEqual(config.theme, "mint")
        self.assertEqual(config.name, "Mochi")

    def test_reset_restores_defaults(self) -> None:
        config = Config()
        config.scale = 1.5
        config.theme = "charcoal"
        config.reset()
        self.assertEqual(config.scale, Config().scale)
        self.assertEqual(config.theme, Config().theme)

    def test_theme_colors_complete(self) -> None:
        for key in THEMES:
            config = Config()
            config.theme = key
            colors = config.theme_colors()
            for color_key in ("body", "belly", "accent", "outline", "eye"):
                self.assertIn(color_key, colors)


class AutostartTests(unittest.TestCase):
    def test_autostart_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertFalse(autostart_enabled(base))
            path = set_autostart(True, base)
            self.assertTrue(path.is_file())
            self.assertTrue(autostart_enabled(base))
            text = path.read_text(encoding="utf-8")
            self.assertIn("[Desktop Entry]", text)
            self.assertIn("Exec=", text)
            set_autostart(False, base)
            self.assertFalse(autostart_enabled(base))


if __name__ == "__main__":
    unittest.main()
