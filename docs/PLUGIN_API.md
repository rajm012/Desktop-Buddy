# Desktop Buddy plugin API 1

Desktop Buddy 1.6 introduces a small, synchronous plugin API for optional local
integrations. Plugins are disabled by default, declare every Desktop Buddy API
they use, and may declare required platform capabilities.

External plugins execute Python code as the current user. Permissions restrict
access to Desktop Buddy contribution APIs; they are not an operating-system
sandbox. Review plugin source before enabling it.

## Installation and discovery

Create one directory per plugin under the backend config directory. On a normal
Linux installation this is:

```text
~/.config/desktop-buddy/plugins/hello/
  plugin.json
  plugin.py
```

Desktop Buddy reads `plugin.json` at startup but does not import `plugin.py`
until the user grants all declared permissions and enables the plugin. Built-in
plugins are registered before external directories are scanned. Duplicate IDs
are ignored, so an external plugin cannot replace a built-in.

## Minimal manifest

```json
{
  "id": "hello",
  "name": "Hello plugin",
  "version": "1.0.0",
  "description": "Adds a small action and observes startup.",
  "api_version": 1,
  "min_app_version": "1.6.0",
  "data_access": ["Describe every category of user data read"],
  "permissions": ["actions", "events"],
  "required_capabilities": [],
  "entrypoint": "plugin.py:Plugin"
}
```

Required metadata fields are `id`, `name`, and `version`. Compatibility fields:

- `api_version`: must equal the app's plugin API version, currently `1`.
- `min_app_version`: minimum compatible Desktop Buddy version.
- `max_app_version`: optional maximum compatible version.
- `entrypoint`: a Python file inside the plugin directory and a class name,
  written as `file.py:ClassName`.
- `required_capabilities`: platform capability names such as `audio`,
  `active_window`, or `battery`. Activation is blocked when one is unavailable.
- `data_access`: exact, user-facing descriptions of data the integration reads.
  Preferences displays these declarations before enablement.

## Minimal plugin

```python
class Plugin:
    def activate(self, context):
        self.context = context
        self.action_id = context.register_action(
            "hello", "Say hello", self.say_hello
        )
        context.on("app.started", self.on_started)

    def deactivate(self):
        self.context = None

    def say_hello(self):
        self.context.emit("hello.clicked", source="action")

    def on_started(self, event):
        print("Desktop Buddy started", event.payload["version"])
```

`activate(context)` is called once after compatibility, capability, and
permission checks pass. `deactivate()` is called when disabled, reloaded, or the
application exits. Contributions and event subscriptions are removed
automatically even if `deactivate()` fails.

## Permissions and APIs

Every used API must be declared in the manifest and granted by the user:

| Permission | Context API | Effect |
| --- | --- | --- |
| `actions` | `register_action(id, name, callback)` | Adds a namespaced safe action. |
| `reminders` | `register_reminder(definition)` | Adds a namespaced reminder while enabled. |
| `tray` | `register_tray_item(id, label, callback)` | Adds an item under tray → Plugins. |
| `settings` | `register_settings_page(id, title, factory)` | Adds a Preferences tab. |
| `events` | `on(name, callback)`, `emit(name, **payload)` | Receives or publishes synchronous events. |
| `calendar` | Marker permission for built-in/provider calendar readers | Grants declared read-only calendar access. |
| `media` | Marker permission for built-in/provider media integrations | Grants declared native media access. |

Contribution IDs are automatically prefixed with the plugin ID. Plugins cannot
replace core or other-plugin contributions. Reminder definitions use the same
fields documented for `config.reminders`; plugin reminders exist only while the
plugin is active.

A settings factory is called as `factory(parent)` and must return a `QWidget`.
Settings pages are presentation only: plugin domain work should stay outside Qt
callbacks. The full application controller is not part of the plugin API.

## Core events

The stable API 1 event set is:

- `app.started`, `app.stopping`
- `system.context`, `system.fullscreen`, `system.active_application`
- `system.low_battery`, `system.network`
- `calendar.upcoming`, `calendar.meeting`
- `system.capabilities`
- `action.executed`
- `reminder.triggered`, `reminder.done`, `reminder.snoozed`, `reminder.missed`
- `focus.changed`, `focus.completed`

Event delivery is synchronous. Keep handlers short and move slow work off the UI
thread. An exception from activation, an event handler, a contributed callback,
or a settings factory disables only that plugin, removes its contributions, and
is written to the Desktop Buddy log.

## Managing plugins

Use Preferences → Integrations → Plugins for normal permission and enable/disable
controls. CLI and IPC equivalents are:

```bash
desktop-buddy plugins list
desktop-buddy plugins info hello
desktop-buddy plugins grant hello actions events
desktop-buddy plugins enable hello
desktop-buddy plugins disable hello
```

Permissions may also be supplied during enable:

```bash
desktop-buddy plugins enable hello actions events
```

Changes are stored in config schema 5 under `plugins`. External plugin code and
plugin-owned data are not copied into Desktop Buddy's config or state files.
