# Context awareness and integrations

Phase 6 integrations are disabled by default. They run locally and can be
disabled independently in Preferences → Integrations.

## Context polling

When context awareness is enabled, the controller polls at most once every 15
seconds. If it is disabled, the Phase 6 context service performs no idle,
battery, network, or additional active-window probes. The pre-existing optional
window-perching feature has its own active-window access switch. The lightweight
timer remains available so enabled plugins can perform their own local refresh
work.

| Integration | Data read | Storage / transmission |
| --- | --- | --- |
| Active application | Window class and title | Memory only; never uploaded |
| Fullscreen detection | Active window fullscreen flag | Memory only |
| Idle detection | Milliseconds since local input | Memory only |
| Battery events | Charging state and percentage | Memory only |
| Network events | Interface name and online/offline state | Memory only; no traffic inspection |
| Media controls | MPRIS player bus name and playback state | Read on tray/CLI use; no history |
| Local Calendar plugin | Configured `.ics`/`.ical` files; event title/start/end | Local reminder state only; files are never changed |

Plugin metadata also contains a `data_access` list. Preferences displays it
before a plugin is enabled. The `events` permission can expose application and
system event payloads, so it should be granted only to trusted plugins.

## Linux implementation

- Idle time uses the XScreenSaver extension on X11.
- Fullscreen state uses EWMH active-window metadata on X11.
- Network state reads `/sys/class/net`; it does not inspect packets or contact a
  connectivity-check server.
- Media control uses the session D-Bus MPRIS API through `gdbus`.
- Secrets use the desktop Secret Service through `secret-tool`.

Wayland and the generic backend report unsupported native capabilities rather
than attempting unreliable fallbacks. Later Windows and macOS phases implement
the same backend methods with their native APIs.

## Application profiles

Profiles match the active window class and/or title using case-insensitive local
substring matching. A matching quiet profile suppresses non-urgent reminders;
urgent reminders remain allowed. Profiles may also pause character animation
without changing the user's manual pause preference.

## Calendar plugin

The built-in Local Calendar plugin is disabled by default. After granting its
`calendar`, `reminders`, `settings`, and `events` permissions, configure one or
more local iCalendar files in its settings tab. It registers one-time reminders
for events in the next seven days and publishes current-meeting state for quiet
mode. It ignores attendees, descriptions, and all write operations.

The first implementation deliberately accepts no server credentials or tokens.
If a later provider needs them, it must use `PlatformBackend.store_secret`,
`read_secret`, and `delete_secret`; secrets must never enter `config.json`.

## CLI

```bash
desktop-buddy media status
desktop-buddy media play-pause
desktop-buddy media previous
desktop-buddy media next
desktop-buddy media stop
desktop-buddy plugins info local-calendar
```

Media commands work only after the media integration is enabled. `status`
includes context, fullscreen, active profile, network, and meeting state for
local troubleshooting.
