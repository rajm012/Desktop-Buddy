"""Plugin metadata, permissions, discovery, lifecycle, and isolation tests."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from desktop_buddy.builtin_plugins import (
    EXAMPLE_PLUGIN_METADATA,
    ExampleRoutinePlugin,
)
from desktop_buddy.plugins import (
    PLUGIN_API_VERSION,
    PluginHost,
    PluginManager,
    PluginMetadata,
    PluginPermission,
    PluginStatus,
)


class HostRecorder:
    def __init__(self) -> None:
        self.actions: dict[str, tuple[str, object]] = {}
        self.reminders: dict[str, dict] = {}
        self.tray_items: dict[str, tuple[str, object]] = {}
        self.settings_pages: dict[str, tuple[str, object]] = {}

    @staticmethod
    def _cleanup(mapping: dict, key: str):  # noqa: ANN202
        return lambda: mapping.pop(key, None)

    def register_action(self, _plugin, action_id, name, callback):  # noqa: ANN001, ANN201
        self.actions[action_id] = (name, callback)
        return self._cleanup(self.actions, action_id)

    def register_reminder(self, _plugin, definition):  # noqa: ANN001, ANN201
        reminder_id = definition["id"]
        self.reminders[reminder_id] = definition
        return self._cleanup(self.reminders, reminder_id)

    def register_tray(self, _plugin, item_id, label, callback):  # noqa: ANN001, ANN201
        self.tray_items[item_id] = (label, callback)
        return self._cleanup(self.tray_items, item_id)

    def register_settings(self, _plugin, page_id, title, factory):  # noqa: ANN001, ANN201
        self.settings_pages[page_id] = (title, factory)
        return self._cleanup(self.settings_pages, page_id)

    def host(self) -> PluginHost:
        return PluginHost(
            self.register_action,
            self.register_reminder,
            self.register_tray,
            self.register_settings,
        )


def manager_for(
    recorder: HostRecorder,
    state: dict[str, dict] | None = None,
    capabilities: set[str] | None = None,
) -> PluginManager:
    logger = logging.getLogger(f"plugin-test-{id(recorder)}")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return PluginManager(
        app_version="1.6.0",
        config_state=state if state is not None else {},
        available_capabilities=capabilities or set(),
        host=recorder.host(),
        logger=logger,
    )


class PluginMetadataTests(unittest.TestCase):
    def test_metadata_parses_permissions_and_compatibility(self) -> None:
        metadata = PluginMetadata.from_dict(
            {
                "id": "My Plugin",
                "name": "My Plugin",
                "version": "2.1.0",
                "api_version": PLUGIN_API_VERSION,
                "min_app_version": "1.5.0",
                "max_app_version": "2.0.0",
                "permissions": ["actions", "events"],
                "required_capabilities": ["audio"],
            }
        )
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.id, "my-plugin")
        self.assertEqual(
            metadata.permissions,
            (PluginPermission.ACTIONS, PluginPermission.EVENTS),
        )
        self.assertIsNone(metadata.compatibility_error("1.6.0"))
        self.assertIn("newer", metadata.compatibility_error("1.4.0"))

    def test_unknown_permission_or_api_is_rejected_or_incompatible(self) -> None:
        self.assertIsNone(
            PluginMetadata.from_dict(
                {
                    "id": "bad",
                    "name": "Bad",
                    "version": "1",
                    "permissions": ["filesystem"],
                }
            )
        )
        metadata = PluginMetadata("future", "Future", "1", api_version=999)
        self.assertIn("plugin API", metadata.compatibility_error("1.6.0"))


class PluginManagerTests(unittest.TestCase):
    def test_faulty_activation_is_disabled_without_escaping(self) -> None:
        class Faulty:
            def activate(self, _context) -> None:  # noqa: ANN001
                raise RuntimeError("boom")

            def deactivate(self) -> None:
                return None

        recorder = HostRecorder()
        state = {"faulty": {"enabled": True, "permissions": []}}
        manager = manager_for(recorder, state)
        manager.register_builtin(
            PluginMetadata("faulty", "Faulty", "1", builtin=True), Faulty
        )
        manager.load_enabled()
        record = manager.records["faulty"]
        self.assertEqual(record.status, PluginStatus.FAILED)
        self.assertFalse(state["faulty"]["enabled"])
        self.assertIn("boom", record.error)

    def test_permissions_and_platform_capabilities_block_activation(self) -> None:
        class Fine:
            def activate(self, _context) -> None:  # noqa: ANN001
                return None

            def deactivate(self) -> None:
                return None

        metadata = PluginMetadata(
            "needs-audio",
            "Needs Audio",
            "1",
            permissions=(PluginPermission.EVENTS,),
            required_capabilities=("audio",),
            builtin=True,
        )
        recorder = HostRecorder()
        manager = manager_for(recorder)
        manager.register_builtin(metadata, Fine)
        self.assertFalse(manager.enable("needs-audio"))
        self.assertEqual(manager.records["needs-audio"].status, PluginStatus.BLOCKED)
        manager.available_capabilities.add("audio")
        self.assertFalse(manager.enable("needs-audio"))
        self.assertIn("Permissions", manager.records["needs-audio"].error)
        self.assertTrue(manager.enable("needs-audio", {PluginPermission.EVENTS}))

    def test_faulty_event_disables_only_its_plugin(self) -> None:
        seen: list[str] = []

        class FaultyEvent:
            def activate(self, context) -> None:  # noqa: ANN001
                context.on("tick", self.tick)

            def tick(self, _event) -> None:  # noqa: ANN001
                raise RuntimeError("event boom")

            def deactivate(self) -> None:
                return None

        class HealthyEvent:
            def activate(self, context) -> None:  # noqa: ANN001
                context.on("tick", lambda _event: seen.append("healthy"))

            def deactivate(self) -> None:
                return None

        recorder = HostRecorder()
        manager = manager_for(recorder)
        permission = (PluginPermission.EVENTS,)
        manager.register_builtin(
            PluginMetadata("faulty", "Faulty", "1", permissions=permission),
            FaultyEvent,
        )
        manager.register_builtin(
            PluginMetadata("healthy", "Healthy", "1", permissions=permission),
            HealthyEvent,
        )
        manager.enable("faulty", set(permission))
        manager.enable("healthy", set(permission))
        manager.events.emit("tick")
        self.assertEqual(manager.records["faulty"].status, PluginStatus.FAILED)
        self.assertEqual(manager.records["healthy"].status, PluginStatus.ACTIVE)
        self.assertEqual(seen, ["healthy"])

    def test_faulty_contributed_callback_is_removed(self) -> None:
        class FaultyAction:
            def activate(self, context) -> None:  # noqa: ANN001
                context.register_action("fail", "Fail", self.fail)

            def fail(self) -> None:
                raise RuntimeError("callback boom")

            def deactivate(self) -> None:
                return None

        recorder = HostRecorder()
        manager = manager_for(recorder)
        manager.register_builtin(
            PluginMetadata(
                "faulty-action",
                "Faulty Action",
                "1",
                permissions=(PluginPermission.ACTIONS,),
            ),
            FaultyAction,
        )
        manager.enable("faulty-action", {PluginPermission.ACTIONS})
        callback = recorder.actions["faulty-action-fail"][1]
        self.assertFalse(callback())
        self.assertEqual(manager.records["faulty-action"].status, PluginStatus.FAILED)
        self.assertEqual(recorder.actions, {})

    def test_all_optional_plugins_can_remain_disabled(self) -> None:
        recorder = HostRecorder()
        manager = manager_for(recorder)
        manager.register_builtin(EXAMPLE_PLUGIN_METADATA, ExampleRoutinePlugin)
        manager.load_enabled()
        self.assertEqual(
            manager.records[EXAMPLE_PLUGIN_METADATA.id].status,
            PluginStatus.DISABLED,
        )
        self.assertEqual(recorder.actions, {})
        self.assertEqual(recorder.reminders, {})
        self.assertEqual(recorder.tray_items, {})
        self.assertEqual(recorder.settings_pages, {})

    def test_builtin_example_integration_and_cleanup(self) -> None:
        recorder = HostRecorder()
        manager = manager_for(recorder)
        manager.register_builtin(EXAMPLE_PLUGIN_METADATA, ExampleRoutinePlugin)
        permissions = set(EXAMPLE_PLUGIN_METADATA.permissions)
        self.assertTrue(manager.enable(EXAMPLE_PLUGIN_METADATA.id, permissions))
        record = manager.records[EXAMPLE_PLUGIN_METADATA.id]
        self.assertEqual(record.status, PluginStatus.ACTIVE)
        self.assertIn("example-routine-cheer", recorder.actions)
        self.assertIn("example-routine-posture", recorder.reminders)
        self.assertIn("example-routine-cheer", recorder.tray_items)
        self.assertIn("example-routine-about", recorder.settings_pages)
        manager.events.emit("app.started")
        assert isinstance(record.instance, ExampleRoutinePlugin)
        self.assertEqual(record.instance.started_events, 1)
        action = recorder.actions["example-routine-cheer"][1]
        action()
        self.assertEqual(record.instance.cheers, 1)
        manager.disable(EXAMPLE_PLUGIN_METADATA.id)
        self.assertEqual(recorder.actions, {})
        self.assertEqual(recorder.reminders, {})
        self.assertEqual(recorder.tray_items, {})
        self.assertEqual(recorder.settings_pages, {})

    def test_external_discovery_does_not_import_until_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "external"
            plugin_dir.mkdir()
            marker = plugin_dir / "imported.txt"
            manifest = {
                "id": "external",
                "name": "External",
                "version": "1.0.0",
                "api_version": 1,
                "permissions": [],
                "entrypoint": "plugin.py:Plugin",
            }
            (plugin_dir / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (plugin_dir / "plugin.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('yes')\n"
                "class Plugin:\n"
                "    def activate(self, context): self.context = context\n"
                "    def deactivate(self): pass\n",
                encoding="utf-8",
            )
            recorder = HostRecorder()
            manager = manager_for(recorder)
            self.assertEqual(manager.discover_external([root]), ["external"])
            self.assertFalse(marker.exists())
            self.assertTrue(manager.enable("external"))
            self.assertTrue(marker.is_file())
            self.assertEqual(manager.records["external"].status, PluginStatus.ACTIVE)

    def test_external_plugin_cannot_replace_builtin_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "duplicate"
            plugin_dir.mkdir()
            (plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "example-routine",
                        "name": "Replacement",
                        "version": "99.0.0",
                    }
                ),
                encoding="utf-8",
            )
            recorder = HostRecorder()
            manager = manager_for(recorder)
            manager.register_builtin(EXAMPLE_PLUGIN_METADATA, ExampleRoutinePlugin)
            self.assertEqual(manager.discover_external([root]), [])
            self.assertTrue(manager.records["example-routine"].metadata.builtin)
            self.assertEqual(
                manager.records["example-routine"].metadata.name,
                "Example Routine",
            )


if __name__ == "__main__":
    unittest.main()
