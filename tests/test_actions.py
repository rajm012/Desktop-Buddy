"""Tests for quick-action validation and permission enforcement."""

from __future__ import annotations

import unittest

from desktop_buddy.actions import (
    ActionDefinition,
    ActionRegistry,
    ActionType,
    validate_target,
)


class ActionRegistryTests(unittest.TestCase):
    def test_builtin_action_runs_registered_callback(self) -> None:
        seen: list[str] = []
        registry = ActionRegistry(builtins={"dance": lambda: seen.append("dance")})
        result = registry.execute("dance")
        self.assertTrue(result.ok)
        self.assertEqual(seen, ["dance"])

    def test_url_action_accepts_only_safe_supported_schemes(self) -> None:
        opened: list[str] = []
        action = ActionDefinition(
            "docs", "Open docs", ActionType.URL, "https://example.com"
        )
        registry = ActionRegistry([action], open_url=lambda url: not opened.append(url))
        self.assertTrue(registry.execute("docs").ok)
        self.assertEqual(opened, ["https://example.com"])
        self.assertIsNotNone(validate_target(ActionType.URL, "javascript:alert(1)"))

    def test_application_uses_argument_vector_without_shell(self) -> None:
        launched: list[list[str]] = []
        action = ActionDefinition(
            "editor", "Open editor", ActionType.APPLICATION, "code --new-window"
        )
        registry = ActionRegistry(
            [action], launch_application=lambda parts: not launched.append(parts)
        )
        self.assertTrue(registry.execute("editor").ok)
        self.assertEqual(launched, [["code", "--new-window"]])

    def test_unapproved_command_never_reaches_executor(self) -> None:
        executed: list[list[str]] = []
        action = ActionDefinition(
            "script", "Run script", ActionType.COMMAND, "tool --flag", approved=False
        )
        registry = ActionRegistry(
            [action], run_command=lambda parts: not executed.append(parts)
        )
        result = registry.execute("script")
        self.assertFalse(result.ok)
        self.assertIn("not approved", result.message)
        self.assertEqual(executed, [])

    def test_approved_command_runs_exact_configured_argv(self) -> None:
        executed: list[list[str]] = []
        action = ActionDefinition(
            "script",
            "Run script",
            ActionType.COMMAND,
            "tool 'two words'",
            approved=True,
        )
        registry = ActionRegistry(
            [action], run_command=lambda parts: not executed.append(parts)
        )
        self.assertTrue(registry.execute("script").ok)
        self.assertEqual(executed, [["tool", "two words"]])

    def test_disabled_and_invalid_config_actions_are_not_registered(self) -> None:
        registry = ActionRegistry.from_config(
            [
                {
                    "id": "off",
                    "name": "Off",
                    "type": "url",
                    "target": "https://example.com",
                    "enabled": False,
                },
                {"id": "broken"},
            ]
        )
        self.assertEqual(registry.list_actions(), [])


if __name__ == "__main__":
    unittest.main()
