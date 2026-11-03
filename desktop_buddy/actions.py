"""Permission-aware registry for reminder quick actions.

The registry contains no Qt or subprocess policy. Callers inject the actual URL,
application, and command executors, which keeps validation and permission rules
unit-testable.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from urllib.parse import urlparse


class ActionType(str, Enum):
    BUILTIN = "builtin"
    APPLICATION = "application"
    URL = "url"
    COMMAND = "command"


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    name: str
    type: ActionType
    target: str
    enabled: bool = True
    approved: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "target": self.target,
            "enabled": self.enabled,
            "approved": self.approved,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ActionDefinition | None":
        if not isinstance(data, dict):
            return None
        action_id = _safe_id(data.get("id"))
        name = str(data.get("name", "")).strip()[:80]
        target = str(data.get("target", "")).strip()[:2000]
        try:
            action_type = ActionType(str(data.get("type", "builtin")))
        except ValueError:
            return None
        if not action_id or not name or not target:
            return None
        return cls(
            action_id,
            name,
            action_type,
            target,
            bool(data.get("enabled", True)),
            bool(data.get("approved", False)),
        )


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str


def _safe_id(value: object) -> str:
    text = "".join(
        character if character.isalnum() or character in "_-" else "-"
        for character in str(value).strip().lower()
    )
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")[:64]


def validate_target(action_type: ActionType, target: str) -> str | None:
    target = str(target).strip()
    if not target:
        return "A target is required."
    if action_type is ActionType.URL:
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https", "mailto"}:
            return "URLs must use http, https or mailto."
    elif action_type in (ActionType.APPLICATION, ActionType.COMMAND):
        try:
            parts = shlex.split(target)
        except ValueError as exc:
            return f"Invalid command line: {exc}"
        if not parts:
            return "A program or command is required."
    return None


class ActionRegistry:
    """Resolves built-ins and configured actions through explicit executors."""

    def __init__(
        self,
        definitions: list[ActionDefinition] | None = None,
        *,
        builtins: dict[str, Callable[[], object]] | None = None,
        open_url: Callable[[str], bool] | None = None,
        launch_application: Callable[[list[str]], bool] | None = None,
        run_command: Callable[[list[str]], bool] | None = None,
    ) -> None:
        self.definitions = {
            action.id: action for action in (definitions or []) if action.enabled
        }
        self.builtins = dict(builtins or {})
        self.open_url = open_url or (lambda _target: False)
        self.launch_application = launch_application or (lambda _parts: False)
        self.run_command = run_command or (lambda _parts: False)

    @classmethod
    def from_config(cls, raw: object, **kwargs) -> "ActionRegistry":  # noqa: ANN003
        definitions: list[ActionDefinition] = []
        if isinstance(raw, list):
            for item in raw:
                action = ActionDefinition.from_dict(item)
                if action is not None:
                    definitions.append(action)
        return cls(definitions, **kwargs)

    def list_actions(self) -> list[ActionDefinition]:
        return sorted(self.definitions.values(), key=lambda action: action.name.lower())

    def execute(self, action_id: str) -> ActionResult:
        action_id = _safe_id(action_id)
        builtin = self.builtins.get(action_id)
        if builtin is not None:
            try:
                builtin()
            except Exception as exc:  # noqa: BLE001 - boundary reports failure
                return ActionResult(False, f"Built-in action failed: {exc}")
            return ActionResult(True, f"Ran built-in action: {action_id}")

        action = self.definitions.get(action_id)
        if action is None:
            return ActionResult(False, f"Unknown or disabled action: {action_id}")
        error = validate_target(action.type, action.target)
        if error:
            return ActionResult(False, error)
        if action.type is ActionType.COMMAND and not action.approved:
            return ActionResult(
                False,
                "Command action is not approved. Approve it explicitly in Preferences.",
            )
        try:
            if action.type is ActionType.BUILTIN:
                callback = self.builtins.get(_safe_id(action.target))
                if callback is None:
                    return ActionResult(False, f"Unknown built-in: {action.target}")
                callback()
                ok = True
            elif action.type is ActionType.URL:
                ok = bool(self.open_url(action.target))
            elif action.type is ActionType.APPLICATION:
                ok = bool(self.launch_application(shlex.split(action.target)))
            else:
                ok = bool(self.run_command(shlex.split(action.target)))
        except Exception as exc:  # noqa: BLE001 - executor boundary
            return ActionResult(False, f"Action failed: {exc}")
        return ActionResult(
            ok, f"Ran {action.name}" if ok else f"Could not run {action.name}"
        )
