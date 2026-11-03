"""Built-in plugins shipped with Desktop Buddy.

Built-ins use exactly the same public context as external plugins. The example is
disabled by default and doubles as an integration fixture and API reference.
"""

from __future__ import annotations

from .plugins import PluginContext, PluginMetadata, PluginPermission

EXAMPLE_PLUGIN_METADATA = PluginMetadata(
    id="example-routine",
    name="Example Routine",
    version="1.0.0",
    description="Demonstrates actions, reminders, tray items, settings, and events.",
    api_version=1,
    min_app_version="1.6.0",
    permissions=(
        PluginPermission.ACTIONS,
        PluginPermission.REMINDERS,
        PluginPermission.TRAY,
        PluginPermission.SETTINGS,
        PluginPermission.EVENTS,
    ),
    builtin=True,
)


class ExampleRoutinePlugin:
    """Small optional built-in that demonstrates every limited contribution API."""

    def __init__(self) -> None:
        self.context: PluginContext | None = None
        self.cheers = 0
        self.started_events = 0

    def activate(self, context: PluginContext) -> None:
        self.context = context
        action_id = context.register_action("cheer", "Example cheer", self.cheer)
        context.register_reminder(
            {
                "id": "posture",
                "title": "Example posture check",
                "kind": "custom",
                "icon": "🧍",
                "message": "Relax your shoulders and sit comfortably.",
                "recurrence": "interval",
                "interval_minutes": 240,
                "enabled": True,
                "urgent": False,
                "snooze_minutes": 10,
                "action_id": action_id,
            }
        )
        context.register_tray_item("cheer", "Example cheer", self.cheer)
        context.register_settings_page(
            "about", "Example Routine", self.create_settings_page
        )
        context.on("app.started", self.on_started)

    def deactivate(self) -> None:
        self.context = None

    def cheer(self) -> None:
        self.cheers += 1
        if self.context is not None:
            self.context.emit("example.cheered", count=self.cheers)

    def on_started(self, _event) -> None:  # noqa: ANN001
        self.started_events += 1

    def create_settings_page(self, parent=None):  # noqa: ANN001, ANN201
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

        page = QWidget(parent)
        layout = QVBoxLayout(page)
        title = QLabel("Example Routine plugin")
        title.setStyleSheet("font-size:16px;font-weight:600;")
        body = QLabel(
            "This optional built-in demonstrates the stable plugin API. It adds a "
            "four-hour posture reminder, a safe action, a tray item, this settings "
            "page, and event subscriptions."
        )
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch()
        return page


BUILTIN_PLUGINS = ((EXAMPLE_PLUGIN_METADATA, ExampleRoutinePlugin),)
