"""Permissioned plugin lifecycle, event bus, and external discovery.

This module intentionally has no Qt dependency. The application controller injects
the small set of host registration callbacks that plugins are allowed to use.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Callable, Protocol

PLUGIN_API_VERSION = 1


class PluginPermission(str, Enum):
    ACTIONS = "actions"
    REMINDERS = "reminders"
    TRAY = "tray"
    SETTINGS = "settings"
    EVENTS = "events"


class PluginStatus(str, Enum):
    DISABLED = "disabled"
    ACTIVE = "active"
    FAILED = "failed"
    BLOCKED = "blocked"
    INCOMPATIBLE = "incompatible"


class PluginError(RuntimeError):
    """Base error for invalid plugin operations."""


class PluginPermissionError(PluginError):
    """Raised when a plugin uses an API without a granted permission."""


def _safe_id(value: object) -> str:
    text = "".join(
        character if character.isalnum() or character in "_-" else "-"
        for character in str(value).strip().lower()
    )
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")[:64]


def _version_tuple(value: object) -> tuple[int, int, int]:
    parts = str(value).strip().split(".")
    numbers: list[int] = []
    for part in parts[:3]:
        digits = ""
        for character in part:
            if not character.isdigit():
                break
            digits += character
        numbers.append(int(digits or 0))
    return tuple((numbers + [0, 0, 0])[:3])  # type: ignore[return-value]


@dataclass(frozen=True)
class PluginMetadata:
    id: str
    name: str
    version: str
    description: str = ""
    api_version: int = PLUGIN_API_VERSION
    min_app_version: str = "0.0.0"
    max_app_version: str | None = None
    permissions: tuple[PluginPermission, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    builtin: bool = False
    entrypoint: str = "plugin.py:Plugin"

    @classmethod
    def from_dict(
        cls, data: object, *, builtin: bool = False
    ) -> "PluginMetadata | None":
        if not isinstance(data, dict):
            return None
        plugin_id = _safe_id(data.get("id"))
        name = str(data.get("name", "")).strip()[:80]
        version = str(data.get("version", "")).strip()[:32]
        if not plugin_id or not name or not version:
            return None
        try:
            api_version = int(data.get("api_version", PLUGIN_API_VERSION))
        except (TypeError, ValueError):
            return None
        raw_permissions = data.get("permissions", [])
        permissions: list[PluginPermission] = []
        if not isinstance(raw_permissions, (list, tuple)):
            return None
        for value in raw_permissions:
            try:
                permission = PluginPermission(str(value))
            except ValueError:
                return None
            if permission not in permissions:
                permissions.append(permission)
        raw_capabilities = data.get("required_capabilities", [])
        if not isinstance(raw_capabilities, (list, tuple)):
            return None
        capabilities = tuple(
            dict.fromkeys(str(value).strip() for value in raw_capabilities if value)
        )
        return cls(
            id=plugin_id,
            name=name,
            version=version,
            description=str(data.get("description", "")).strip()[:500],
            api_version=api_version,
            min_app_version=str(data.get("min_app_version", "0.0.0")).strip(),
            max_app_version=(
                str(data["max_app_version"]).strip()
                if data.get("max_app_version")
                else None
            ),
            permissions=tuple(permissions),
            required_capabilities=capabilities,
            builtin=builtin,
            entrypoint=str(data.get("entrypoint", "plugin.py:Plugin")).strip(),
        )

    def compatibility_error(self, app_version: str) -> str | None:
        if self.api_version != PLUGIN_API_VERSION:
            return (
                f"requires plugin API {self.api_version}; "
                f"this app provides {PLUGIN_API_VERSION}"
            )
        current = _version_tuple(app_version)
        if current < _version_tuple(self.min_app_version):
            return f"requires Desktop Buddy {self.min_app_version} or newer"
        if self.max_app_version and current > _version_tuple(self.max_app_version):
            return f"supports Desktop Buddy up to {self.max_app_version}"
        return None


@dataclass(frozen=True)
class PluginEvent:
    name: str
    payload: dict[str, object]


@dataclass(frozen=True)
class _Subscription:
    plugin_id: str
    callback: Callable[[PluginEvent], object]


class EventBus:
    """Synchronous event bus with per-subscriber failure isolation."""

    def __init__(
        self,
        error_handler: Callable[[str, str, Exception], None] | None = None,
    ) -> None:
        self._subscriptions: dict[str, list[_Subscription]] = defaultdict(list)
        self._error_handler = error_handler

    def subscribe(
        self,
        plugin_id: str,
        event_name: str,
        callback: Callable[[PluginEvent], object],
    ) -> Callable[[], None]:
        event_name = str(event_name).strip()
        if not event_name:
            raise PluginError("An event name is required.")
        subscription = _Subscription(plugin_id, callback)
        self._subscriptions[event_name].append(subscription)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self._subscriptions[event_name].remove(subscription)

        return unsubscribe

    def emit(self, event_name: str, payload: dict[str, object] | None = None) -> None:
        event = PluginEvent(str(event_name), dict(payload or {}))
        subscriptions = list(self._subscriptions.get(event.name, ()))
        subscriptions.extend(self._subscriptions.get("*", ()))
        for subscription in subscriptions:
            try:
                subscription.callback(event)
            except Exception as exc:  # noqa: BLE001 - plugin boundary
                if self._error_handler is not None:
                    self._error_handler(subscription.plugin_id, event.name, exc)

    def unsubscribe_plugin(self, plugin_id: str) -> None:
        for event_name, subscriptions in tuple(self._subscriptions.items()):
            self._subscriptions[event_name] = [
                item for item in subscriptions if item.plugin_id != plugin_id
            ]


class DesktopBuddyPlugin(Protocol):
    def activate(self, context: "PluginContext") -> object: ...

    def deactivate(self) -> object: ...


@dataclass
class PluginHost:
    register_action: Callable[[str, str, str, Callable[[], object]], Callable[[], None]]
    register_reminder: Callable[[str, dict[str, object]], Callable[[], None]]
    register_tray_item: Callable[
        [str, str, str, Callable[[], object]], Callable[[], None]
    ]
    register_settings_page: Callable[
        [str, str, str, Callable[..., object]], Callable[[], None]
    ]


@dataclass
class PluginRecord:
    metadata: PluginMetadata
    factory: Callable[[], DesktopBuddyPlugin]
    source: Path | None = None
    status: PluginStatus = PluginStatus.DISABLED
    error: str = ""
    instance: DesktopBuddyPlugin | None = None
    context: "PluginContext | None" = None


class PluginContext:
    """Capability-limited API presented to one activated plugin."""

    def __init__(
        self,
        manager: "PluginManager",
        record: PluginRecord,
        granted_permissions: set[PluginPermission],
    ) -> None:
        self._manager = manager
        self.metadata = record.metadata
        self.granted_permissions = frozenset(granted_permissions)
        self._cleanups: list[Callable[[], None]] = []

    def _require(self, permission: PluginPermission) -> None:
        if permission not in self.granted_permissions:
            raise PluginPermissionError(
                f"Plugin {self.metadata.id} lacks permission: {permission.value}"
            )

    def _contribution_id(self, local_id: str) -> str:
        local = _safe_id(local_id)
        if not local:
            raise PluginError("A contribution ID is required.")
        return f"{self.metadata.id}-{local}"

    def has_capability(self, capability: str) -> bool:
        return str(capability) in self._manager.available_capabilities

    def on(self, event_name: str, callback: Callable[[PluginEvent], object]) -> None:
        self._require(PluginPermission.EVENTS)
        guarded = self._manager.guard_callback(self.metadata.id, callback)
        self._cleanups.append(
            self._manager.events.subscribe(self.metadata.id, event_name, guarded)
        )

    def emit(self, event_name: str, **payload: object) -> None:
        self._require(PluginPermission.EVENTS)
        self._manager.events.emit(event_name, payload)

    def register_action(
        self, action_id: str, name: str, callback: Callable[[], object]
    ) -> str:
        self._require(PluginPermission.ACTIONS)
        contribution_id = self._contribution_id(action_id)
        guarded = self._manager.guard_callback(self.metadata.id, callback)
        self._cleanups.append(
            self._manager.host.register_action(
                self.metadata.id, contribution_id, str(name)[:80], guarded
            )
        )
        return contribution_id

    def register_reminder(self, definition: dict[str, object]) -> str:
        self._require(PluginPermission.REMINDERS)
        local_id = str(definition.get("id", "reminder"))
        contribution_id = self._contribution_id(local_id)
        data = dict(definition)
        data["id"] = contribution_id
        self._cleanups.append(
            self._manager.host.register_reminder(self.metadata.id, data)
        )
        return contribution_id

    def register_tray_item(
        self, item_id: str, label: str, callback: Callable[[], object]
    ) -> str:
        self._require(PluginPermission.TRAY)
        contribution_id = self._contribution_id(item_id)
        guarded = self._manager.guard_callback(self.metadata.id, callback)
        self._cleanups.append(
            self._manager.host.register_tray_item(
                self.metadata.id, contribution_id, str(label)[:80], guarded
            )
        )
        return contribution_id

    def register_settings_page(
        self, page_id: str, title: str, factory: Callable[..., object]
    ) -> str:
        self._require(PluginPermission.SETTINGS)
        contribution_id = self._contribution_id(page_id)
        guarded = self._manager.guard_callback(self.metadata.id, factory)
        self._cleanups.append(
            self._manager.host.register_settings_page(
                self.metadata.id, contribution_id, str(title)[:40], guarded
            )
        )
        return contribution_id

    def cleanup(self) -> None:
        for cleanup in reversed(self._cleanups):
            try:
                cleanup()
            except Exception:  # noqa: BLE001 - cleanup must be best effort
                self._manager.logger.exception(
                    "Plugin cleanup failed: %s", self.metadata.id
                )
        self._cleanups.clear()
        self._manager.events.unsubscribe_plugin(self.metadata.id)


class PluginManager:
    """Discovers, enables, disables, and isolates Desktop Buddy plugins."""

    def __init__(
        self,
        *,
        app_version: str,
        config_state: dict[str, dict[str, object]],
        available_capabilities: set[str],
        host: PluginHost,
        state_changed: Callable[[], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.app_version = app_version
        self.config_state = config_state
        self.available_capabilities = set(available_capabilities)
        self.host = host
        self.state_changed = state_changed or (lambda: None)
        self.logger = logger or logging.getLogger(__name__)
        self.records: dict[str, PluginRecord] = {}
        self.events = EventBus(self._event_failed)

    def register_builtin(
        self,
        metadata: PluginMetadata,
        factory: Callable[[], DesktopBuddyPlugin],
    ) -> bool:
        if metadata.id in self.records:
            return False
        if not metadata.builtin:
            metadata = PluginMetadata(**{**metadata.__dict__, "builtin": True})
        self.records[metadata.id] = PluginRecord(metadata, factory)
        return True

    def discover_external(self, roots: list[Path]) -> list[str]:
        discovered: list[str] = []
        for root in roots:
            if not root.is_dir():
                continue
            for manifest_path in sorted(root.glob("*/plugin.json")):
                try:
                    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                    metadata = PluginMetadata.from_dict(raw, builtin=False)
                except (OSError, ValueError):
                    self.logger.exception(
                        "Could not read plugin manifest: %s", manifest_path
                    )
                    continue
                if metadata is None or metadata.id in self.records:
                    self.logger.warning(
                        "Ignoring invalid/duplicate plugin: %s", manifest_path
                    )
                    continue
                plugin_dir = manifest_path.parent.resolve()
                factory = self._external_factory(metadata, plugin_dir)
                self.records[metadata.id] = PluginRecord(
                    metadata, factory, source=plugin_dir
                )
                discovered.append(metadata.id)
        return discovered

    def _external_factory(
        self, metadata: PluginMetadata, plugin_dir: Path
    ) -> Callable[[], DesktopBuddyPlugin]:
        def factory() -> DesktopBuddyPlugin:
            module_name, separator, class_name = metadata.entrypoint.partition(":")
            if not separator or not module_name or not class_name:
                raise PluginError("Entrypoint must use file.py:ClassName form.")
            module_path = (plugin_dir / module_name).resolve()
            if plugin_dir not in module_path.parents or module_path.suffix != ".py":
                raise PluginError(
                    "Entrypoint must be a Python file inside the plugin directory."
                )
            if not module_path.is_file():
                raise PluginError(f"Entrypoint does not exist: {module_name}")
            unique_name = f"desktop_buddy_external_{metadata.id.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(unique_name, module_path)
            if spec is None or spec.loader is None:
                raise PluginError(f"Could not load entrypoint: {module_name}")
            module = importlib.util.module_from_spec(spec)
            self._execute_module(spec.loader, module)
            plugin_class = getattr(module, class_name, None)
            if plugin_class is None:
                raise PluginError(f"Entrypoint class not found: {class_name}")
            return plugin_class()

        return factory

    @staticmethod
    def _execute_module(loader, module: ModuleType) -> None:  # noqa: ANN001
        loader.exec_module(module)

    def load_enabled(self) -> None:
        for plugin_id in tuple(self.records):
            if bool(self.config_state.get(plugin_id, {}).get("enabled", False)):
                self.enable(plugin_id)

    def granted_permissions(self, plugin_id: str) -> set[PluginPermission]:
        raw = self.config_state.get(plugin_id, {}).get("permissions", [])
        if not isinstance(raw, (list, tuple)):
            return set()
        result: set[PluginPermission] = set()
        for value in raw:
            try:
                result.add(PluginPermission(str(value)))
            except ValueError:
                continue
        return result

    def set_permissions(
        self, plugin_id: str, permissions: set[PluginPermission]
    ) -> bool:
        record = self.records.get(plugin_id)
        if record is None:
            return False
        declared = set(record.metadata.permissions)
        granted = set(permissions) & declared
        was_active = record.status is PluginStatus.ACTIVE
        if was_active:
            self.disable(plugin_id, persist_enabled=True)
        state = self.config_state.setdefault(plugin_id, {})
        state["permissions"] = sorted(item.value for item in granted)
        self.state_changed()
        if was_active:
            return self.enable(plugin_id)
        return True

    def enable(
        self,
        plugin_id: str,
        permissions: set[PluginPermission] | None = None,
    ) -> bool:
        record = self.records.get(plugin_id)
        if record is None:
            return False
        if record.status is PluginStatus.ACTIVE:
            return True
        if permissions is not None:
            state = self.config_state.setdefault(plugin_id, {})
            declared = set(record.metadata.permissions)
            state["permissions"] = sorted(
                item.value for item in permissions if item in declared
            )
            self.state_changed()
        compatibility_error = record.metadata.compatibility_error(self.app_version)
        if compatibility_error:
            record.status = PluginStatus.INCOMPATIBLE
            record.error = compatibility_error
            return False
        missing_capabilities = set(record.metadata.required_capabilities) - set(
            self.available_capabilities
        )
        if missing_capabilities:
            record.status = PluginStatus.BLOCKED
            record.error = "Missing capabilities: " + ", ".join(
                sorted(missing_capabilities)
            )
            return False
        granted = self.granted_permissions(plugin_id)
        missing_permissions = set(record.metadata.permissions) - granted
        if missing_permissions:
            record.status = PluginStatus.BLOCKED
            record.error = "Permissions not granted: " + ", ".join(
                sorted(item.value for item in missing_permissions)
            )
            return False
        try:
            record.instance = record.factory()
            record.context = PluginContext(self, record, granted)
            record.instance.activate(record.context)
        except Exception as exc:  # noqa: BLE001 - plugin boundary
            self._fail(record, exc, "activation")
            return False
        record.status = PluginStatus.ACTIVE
        record.error = ""
        state = self.config_state.setdefault(plugin_id, {})
        state["enabled"] = True
        self.state_changed()
        self.logger.info("Plugin enabled: %s", plugin_id)
        return True

    def disable(self, plugin_id: str, *, persist_enabled: bool = False) -> bool:
        record = self.records.get(plugin_id)
        if record is None:
            return False
        if record.instance is not None:
            try:
                record.instance.deactivate()
            except Exception:  # noqa: BLE001 - plugin boundary
                self.logger.exception("Plugin deactivation failed: %s", plugin_id)
        if record.context is not None:
            record.context.cleanup()
        record.instance = None
        record.context = None
        record.status = PluginStatus.DISABLED
        record.error = ""
        state = self.config_state.setdefault(plugin_id, {})
        state["enabled"] = bool(persist_enabled)
        self.state_changed()
        return True

    def guard_callback(self, plugin_id: str, callback: Callable) -> Callable:  # noqa: ANN001
        def guarded(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            try:
                return callback(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - plugin boundary
                record = self.records.get(plugin_id)
                if record is not None:
                    self._fail(record, exc, "callback")
                return False

        return guarded

    def _event_failed(self, plugin_id: str, event_name: str, exc: Exception) -> None:
        record = self.records.get(plugin_id)
        if record is not None:
            self._fail(record, exc, f"event {event_name}")

    def report_failure(self, plugin_id: str, exc: Exception, phase: str) -> None:
        record = self.records.get(plugin_id)
        if record is not None:
            self._fail(record, exc, phase)

    def _fail(self, record: PluginRecord, exc: Exception, phase: str) -> None:
        if record.instance is not None:
            try:
                record.instance.deactivate()
            except Exception:  # noqa: BLE001 - failure cleanup boundary
                self.logger.exception(
                    "Plugin deactivation after failure also failed: %s",
                    record.metadata.id,
                )
        if record.context is not None:
            record.context.cleanup()
        record.instance = None
        record.context = None
        record.status = PluginStatus.FAILED
        record.error = f"{phase} failed: {exc}"
        state = self.config_state.setdefault(record.metadata.id, {})
        state["enabled"] = False
        self.state_changed()
        self.logger.exception(
            "Plugin %s disabled after %s failure",
            record.metadata.id,
            phase,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def unload(self) -> None:
        for plugin_id in reversed(tuple(self.records)):
            if self.records[plugin_id].status is PluginStatus.ACTIVE:
                self.disable(plugin_id, persist_enabled=True)

    def shutdown(self) -> None:
        self.events.emit("app.stopping", {"version": self.app_version})
        self.unload()

    def summary(self) -> str:
        if not self.records:
            return "No plugins discovered."
        lines = []
        for record in self.records.values():
            origin = "built-in" if record.metadata.builtin else "external"
            line = (
                f"{record.metadata.id}  {record.status.value}  "
                f"{record.metadata.name} {record.metadata.version} ({origin})"
            )
            if record.error:
                line += f" — {record.error}"
            lines.append(line)
        return "Plugins:\n" + "\n".join(lines)
