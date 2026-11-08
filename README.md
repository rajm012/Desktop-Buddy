# Desktop Buddy 🤖👻🐾

Tiny creatures that live on your Ubuntu desktop.

**Bolt** is a soft-edged desktop robot with a large rounded screen face, two
luminous eyes, a compact white shell and oversized boots. It walks around,
dances on your browser's search bar, hangs out near your terminal prompt,
investigates your cursor, and **looks after you** with customizable local
reminders, safe quick actions, and a fully local focus timer.
**Boo-ombastic** the ghost and **Mochi** the original blob-cat remain available.

Linux/X11 is the verified release platform. Download the current Linux build
from [GitHub Releases](https://github.com/rajm012/Desktop-Buddy/releases/latest).
Windows releases are deferred; the native backend remains in the source for
future validation. See [Wayland](#wayland) for session limitations.

![Bolt's baseline animation poses](docs/screenshots/bolt-poses.png)

---

## Features

- Frameless, transparent, always-on-top window — no taskbar entry, no focus stealing
- Autonomous behaviour: idle breathing, blinking, looking around, walking, running,
  jumping (gravity + squash & stretch), landing dust, dancing, sleeping with `Zzz`
- **Dance mode**: Boo bobs, sways, sings `♪♫` and throws hearts (double-click,
  tray → Dance!, or `desktop-buddy dance`)
- **Window perching**: when you use a browser it climbs onto the window near the
  address/search bar; with a terminal it settles near the prompt; switch apps and
  it comes back down (tray → "Perch on browser/terminal" to disable)
- **Drop it anywhere**: drag the buddy anywhere on the screen — floor, middle of
  the screen, top edge, on top of another window
- **Three characters**: Bolt the articulated robot, Boo-ombastic the ghost and
  Mochi the cat — switch live from the tray or with `desktop-buddy character robot|ghost|mochi`
- **Custom reminders**: create one-time, daily, weekday, or interval schedules
  using local phrases such as `in 20 minutes`, `weekdays at 9`, and
  `every 2 hours`; existing wellness schedules migrate automatically
- Reminders arrive with a dancing Boo, a speech bubble, themed particles
  (water droplets, hearts, notes), a gentle chime and a card with
  **Done** / **Snooze 10m** buttons; done, missed, and snoozed outcomes are kept
  in local history, and non-urgent reminders respect active hours
- **Quick actions**: attach safe built-ins, application launches, URLs, or an
  explicitly approved command to a reminder; command execution never uses a shell
- **Permissioned plugins**: optional built-in and external plugins can add namespaced actions, reminders, tray items, settings pages, and event handlers; faulty plugins are disabled without taking down the buddy
- **Opt-in context awareness**: low-frequency local idle, fullscreen, active-app,
  battery, and network state with per-application quiet profiles
- **Native media controls**: optional Linux MPRIS play/pause, previous, next, and
  stop controls through the tray or CLI
- **Read-only local calendar**: an optional built-in plugin reads configured
  iCalendar files for upcoming reminders and meeting-aware quiet mode
- **Focus timer**: configurable focus, short-break and long-break sessions with start, pause, resume, skip and stop controls in Preferences, the tray and CLI
- Active or paused focus sessions survive restarts; completed focus sessions are
  recorded locally with a compact seven-day history and daily totals
- Bolt shows distinct focus/break eyes, a live timer badge and a completion
  celebration; completion alerts respect quiet hours, fullscreen and DND
- Eyes follow the cursor; the buddy chases it when playful
- Drag & throw with real physics; double-click for a happy hop; `Ctrl`+wheel to resize
- Right-click menu and a system-tray icon (GNOME AppIndicator)
- Six core Preferences tabs with theme/animation previews, platform capability status, import/export/reset controls, and optional plugin-provided tabs
- First-run onboarding for character, size, reminder hours and login startup
- Reduced motion, silent mode and do-not-disturb attention controls
- 7 colour themes, adjustable size / speed / frame rate / sleep timeout
- Adaptive frame rate and a battery saver (lower fps on battery)
- Remembers its position and settings between sessions
- Single instance: launching again just shows the existing buddy
- Platform-backed autostart entry so it comes back when you log in
- All artwork drawn procedurally with `QPainter` — crisp at any scale (including
  your 2.5× fractional HiDPI setup), no bitmap assets to ship

## Install

### Linux

Download `desktop-buddy-1.8.0-linux-x86_64.tar.gz` from
[the release](https://github.com/rajm012/Desktop-Buddy/releases/tag/v1.8.0).
The standalone archive includes Python and Qt and runs on Ubuntu 24.04 or newer
(Linux x86_64, glibc 2.39+). Extract it and launch `desktop-buddy`, or install it
for your user:

```bash
tar -xzf desktop-buddy-1.8.0-linux-x86_64.tar.gz
cd desktop-buddy
./install.sh                 # --no-autostart skips login startup
```

This copies the bundle to `~/.local/share/desktop-buddy/app`, adds a launcher and
application-menu entry, and enables login startup. No Python installation or
downloads are needed. Settings and history survive upgrades. See the archive's
README for system-library requirements, or [the Linux release guide](docs/RELEASING.md).

### Linux from source

Everything is user-level; **no sudo needed**.

```bash
git clone https://github.com/rajm012/Desktop-Buddy.git ~/desktop-buddy
cd ~/desktop-buddy
./install.sh                 # add --no-autostart to skip login startup
```

The installer:

1. creates a Python 3.10+ virtual environment in `.venv/` and installs PyQt6;
2. vendors `libxcb-cursor` into `vendor/syslibs/` if your system lacks it
   (Qt ≥ 6.5 needs it for the X11 platform plugin — this machine was missing it);
3. installs the launcher `~/.local/bin/desktop-buddy`;
4. installs the application-menu entry;
5. enables autostart (`~/.config/autostart/desktop-buddy.desktop`).

> If the `desktop-buddy` command is not found right away, your shell's `PATH`
> predates the new `~/.local/bin` directory. Use `~/.local/bin/desktop-buddy`
> or log out/in once (Ubuntu adds it automatically at login).

### Windows (deferred)

No Windows artifact is published in this release. Windows packaging scripts are
retained for future work; signing and the physical Windows 10/11 validation
matrix remain incomplete. See [docs/WINDOWS.md](docs/WINDOWS.md).

## Usage

```bash
desktop-buddy            # start it (or show it if already running)
```

Then:

| Action | How |
| --- | --- |
| Move it anywhere | Drag with the left mouse button, release to throw |
| Make it dance (Boo) | Double-click it, tray → Dance!, or `desktop-buddy dance` |
| Menu | Right-click it, or click the tray icon |
| Resize | `Ctrl` + mouse wheel |
| Change character | Tray → Character → Bolt / Boo-ombastic / Mochi |
| Reminders | Preferences → Reminders, tray → Reminders, or the reminder CLI |
| Quick actions | Preferences → Integrations or tray → Quick actions |
| Plugins | Preferences → Integrations → Plugins or `desktop-buddy plugins list` |
| Focus timer | Tray → Focus, Preferences → Focus, or `desktop-buddy focus start` |
| Context and media | Preferences → Integrations; tray → Media |
| Preferences | Tray menu → Preferences… (or `desktop-buddy settings`) |

### Command line

```bash
desktop-buddy quit | show | hide | toggle | pause | resume | dance | settings
desktop-buddy status                    # what is the buddy doing right now?
desktop-buddy character robot|ghost|mochi  # switch characters
desktop-buddy reminders status          # next reminders, in order
desktop-buddy reminders on|off          # pause/resume wellness reminders
desktop-buddy reminders list|history
desktop-buddy reminders add "Stand up" "weekdays at 9"
desktop-buddy reminders remove|done REMINDER_ID
desktop-buddy reminders snooze REMINDER_ID [MINUTES]
desktop-buddy remind REMINDER_ID         # fire any configured reminder now
desktop-buddy actions list
desktop-buddy actions run ACTION_ID
desktop-buddy plugins list|info PLUGIN_ID
desktop-buddy plugins grant PLUGIN_ID actions events
desktop-buddy plugins enable PLUGIN_ID [PERMISSIONS...]
desktop-buddy plugins disable PLUGIN_ID
desktop-buddy focus start [focus|short-break|long-break]
desktop-buddy focus pause|resume|skip|stop|status
desktop-buddy media status|play-pause|previous|next|stop
desktop-buddy click-through on|off     # let clicks pass through to apps below
desktop-buddy autostart on|off|status
desktop-buddy --diagnose               # environment/support report
desktop-buddy --reset-config           # wipe settings and start fresh
desktop-buddy --version
```

All control commands talk to the running instance over a local socket — a
second launch never spawns a duplicate buddy.

## Configuration

Settings live in `~/.config/desktop-buddy/config.json` (edited via the GUI,
but hand-editable too):

| Key | Default | Meaning |
| --- | --- | --- |
| `schema_version` | `6` | Persisted-format version used for automatic upgrades |
| `name` | `"Bolt"` | Displayed in the greeting/about |
| `species` | `"robot"` | `robot` (Bolt), `ghost` (Boo) or `mochi` (the cat) |
| `theme` | `"circuit"` | `circuit`, `mint`, `peach`, `lavender`, `sky`, `sakura`, `charcoal` |
| `scale` | `0.8` | 0.5 – 1.8 |
| `speed` | `1.0` | 0.4 – 2.5 |
| `fps` | `30` | 10 – 60 (adaptive; idles at ≤ 15) |
| `always_on_top` | `true` | Keep above other windows |
| `click_through` | `false` | Mouse input passes through to apps below |
| `reduce_on_battery` | `true` | 20 fps active / 12 fps idle on battery |
| `reduced_motion` | `false` | Disable runs, jumps, dances and particles |
| `silent_mode` | `false` | Disable all application sounds |
| `do_not_disturb` | `false` | Pause automatic reminder interruptions |
| `playful` | `true` | Chase the cursor sometimes |
| `can_sleep` | `true` | Nap after being idle |
| `sleep_after` | `180` | Seconds of no interaction before sleeping |
| `perch_on_windows` | `true` | Sit on the focused browser/terminal window |
| `perch_delay` | `1.2` | Seconds a window must stay focused before climbing |
| `reminders_enabled` | `true` | Master switch for all wellness reminders |
| `reminder_sound` | `true` | Play a gentle generated chime |
| `reminders` | built-in wellness set | General reminder definitions, schedules, urgency, snooze length, and attached action IDs |
| `actions` | `[]` | Built-in, application, URL, and approved-command quick actions |
| `plugins` | `{}` | Per-plugin enabled state and explicitly granted permissions |
| `active_start` / `active_end` | `"09:00"` / `"22:30"` | Window in which non-urgent reminders may interrupt |
| `reminder_grace_minutes` | `45` | How late a missed scheduled reminder may still fire |
| `snooze_minutes` | `10` | Default snooze length on the reminder card |
| `focus_minutes` | `25` | Length of a focus session (1–180 minutes) |
| `short_break_minutes` | `5` | Length of a short break (1–60 minutes) |
| `long_break_minutes` | `15` | Length of a long break (1–120 minutes) |
| `long_break_every` | `4` | Completed focus sessions between long breaks |
| `focus_respect_quiet_hours` | `true` | Suppress completion alerts outside active hours |
| `focus_suppress_fullscreen` | `true` | Suppress completion alerts over fullscreen apps when detection is available |
| `context_enabled` | `false` | Enable 15-second local context polling |
| `context_suppress_fullscreen` | `true` | Suppress non-urgent reminders in fullscreen apps |
| `context_network_events` | `false` | Publish online/offline interface changes |
| `context_low_battery_events` | `false` | Publish low-battery state changes |
| `low_battery_percent` | `20` | Low-battery event threshold |
| `application_profiles` | `[]` | Local active-app/title quiet rules |
| `media_controls_enabled` | `false` | Allow native media controls |
| `calendar_sources` | `[]` | Local `.ics`/`.ical` files read by the calendar plugin |
| `calendar_reminder_minutes` | `10` | Minutes before an event to remind |
| `calendar_meeting_quiet` | `true` | Silence non-urgent interruptions during meetings |
| `position_x` | auto | Last position on screen |

Live focus state and history are stored separately in
`~/.local/state/desktop-buddy/focus.json`. The file is versioned, local-only and
restores running or paused sessions after restart.

Reminder runtime state and up to 500 done/missed/snoozed history entries are
stored in `~/.local/state/desktop-buddy/reminders.json`. Reminder and focus times
use deterministic local wall-clock values and require no network service.

External plugins are discovered under `~/.config/desktop-buddy/plugins/<plugin-id>/`. Their manifests are read at startup, but Python code is imported only after explicit permission grants and enablement. Permissions constrain Desktop Buddy APIs, not the operating system; review external source before enabling it. See [the plugin API guide](docs/PLUGIN_API.md).

Phase 6 integration data, polling, privacy, and backend behavior are documented
in [the context and integrations guide](docs/CONTEXT_INTEGRATIONS.md).

## Performance

The Phase 0 baseline is recorded in [BENCHMARKS.md](BENCHMARKS.md). On the
reference i5-13500H Linux/X11 system, startup to first paint is about 174 ms,
idle use is about 4% of one core, and active movement is about 7% of one core.

Summary:

| State | CPU (one core) | Memory | Startup |
| --- | --- | --- | --- |
| First paint (offscreen check) | — | — | ~174 ms |
| Active (walking/dancing/perched) | ~7 % | ~85 MB | — |
| Idle / sleeping | ~4 % (adaptive fps) | ~85 MB | — |
| Paused or hidden | ~1 % | ~85 MB | — |

The window is only ~112 × 128 logical pixels, so even where it overlaps other
windows it blocks almost nothing.

The reminder scheduler wakes every 20 seconds. The focus controller checks its absolute deadline once per second; neither scheduler is tied to animation FPS. Context polling is disabled by default and, when enabled, runs once every 15 seconds using short native queries. Network polling reads local interface files and performs no connectivity request.

## Troubleshooting

### Wayland
GNOME Wayland does not let ordinary applications position themselves, force
themselves always-on-top, or set click-through. The buddy will still run, but
it will be stuck where the compositor puts it. **Log in with "Ubuntu on Xorg"**
for the full experience. `desktop-buddy --diagnose` prints your session type.

### Click-through is on and I can't click the buddy
Use the tray icon, or run:

```bash
desktop-buddy click-through off
```

Click-through uses X11 input shapes; a few compositors handle these oddly, so
treat it as best-effort. Everything else works with normal clicks.

### No tray icon
GNOME needs the AppIndicator extension (installed by default on Ubuntu). Even
without it, right-clicking the buddy opens the same menu.

### Qt complains about the `xcb` platform plugin
Re-vendor the missing library:

```bash
./scripts/fetch_qt_syslibs.sh
```

or install it system-wide with `sudo apt install libxcb-cursor0`.

### Logs and diagnostics

```bash
desktop-buddy --diagnose
tail -f ~/.local/state/desktop-buddy/desktop-buddy.log
```

### Reminders don't fire
- Check `desktop-buddy reminders status` for the next scheduled times.
- Non-urgent reminders only interrupt between `active_start` and `active_end`
  (default 09:00–22:30). Urgent reminders may fire outside that window.
- After sleep, a scheduled reminder can still appear within the grace window
  (45 min by default); otherwise it is recorded as missed.
- No chime? Check that the system has an available audio output. Reminder audio
  now uses Qt Multimedia and does not require an external player command.

### Focus completion did not pop up

- Run `desktop-buddy focus status` to confirm the session completed and view today's total.
- Completion alerts are intentionally suppressed during do-not-disturb, outside `active_start` / `active_end` when quiet-hours protection is enabled, and over fullscreen applications when the platform can detect them.
- The completion and daily total are still saved when an alert is suppressed.

## Uninstall

```bash
./uninstall.sh            # removes launcher, menu entry, autostart
./uninstall.sh --purge    # also deletes settings and logs
```

The project folder (including `.venv/`) is left alone; delete it manually if
you want it gone.

## Project layout

```
desktop_buddy/
  app.py            CLI, controller, single-instance IPC, diagnostics
  window.py         transparent always-on-top window, input, painting loop
  behavior.py       pure-python physics + state machine (unit-tested)
  character.py      procedural QPainter characters (Bolt + Boo + Mochi)
  effects.py        dust, sparkles, hearts, Zzz, music notes, wisps
  platforms/        capability interface and Linux/X11 implementation
    base.py          backend contract, portable paths/audio/IPC identity
    linux.py         X11 probing, workspace behavior, battery and autostart
    windows.py       Win32 windows, DPI, power, idle, keychain and autostart
  wellness.py       general reminder schedules, parsing and history (pure)
  focus.py          focus/break state machine, persistence and history (pure)
  actions.py        validated, permission-aware quick action registry (pure)
  context.py        pure context snapshots, app profiles and attention policy
  calendar_integration.py read-only local iCalendar parser and queries
  plugins.py        metadata, event bus, permissions, discovery and lifecycle
  builtin_plugins.py optional built-ins using the public plugin context
  toast.py          reminder card with Done/Snooze next to the buddy
  sound.py          generated chime waveforms (played through the backend)
  prefs.py          preferences dialog + live preview
  tray.py           tray icon and shared context menu
  config.py         JSON settings, themes, validation
  platform_utils.py compatibility wrappers for backend calls
install.sh / uninstall.sh / run.sh
scripts/fetch_qt_syslibs.sh
tests/              unittest suite (no display required)
tools/preview.py    renders a pose/theme sheet to PNG
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'         # one-time development setup
./scripts/check.sh                      # format check, tests, package build
.venv/bin/python tools/preview.py /tmp/buddy-preview.png
./run.sh --diagnose
```

The behaviour, wellness, focus, action, and plugin engines have no Qt dependency, so their state machines and policies can be tested headlessly.

The supported Phase 0 feature set and known constraints are maintained in
[docs/BASELINE.md](docs/BASELINE.md).

## Local Linux releases

```bash
./scripts/build_linux.sh                # check and build locally
./scripts/release_linux.sh --publish-only  # upload that exact build with gh
```

Or run `./scripts/release_linux.sh` to build and publish in one command. Commit
changes before building; the publisher verifies the source commit and checksums
and refuses stale or uncommitted builds. Output is in `dist/releases/v1.8.0/`.
No GitHub Actions workflow is run. Hosted checks are Linux-only and manual to
avoid spending Actions minutes on pushes or pull requests. See
[docs/RELEASING.md](docs/RELEASING.md) for future version bumps and prerequisites.

## Changelog

**1.8.0 — Linux release**
- Published a locally built Linux x86_64 standalone archive, wheel, source
  distribution, build provenance and SHA-256 checksums.
- Added local build/publish commands and manual Linux-only hosted checks.
- Fixed standalone Linux autostart to launch the packaged executable correctly,
  including paths containing spaces or desktop-entry special characters.
- Added the native Win32 backend for foreground-window geometry, fullscreen,
  topmost/click-through behavior, battery, idle time, network state and Windows
  Credential Manager.
- Added PerMonitorV2 process/installer manifests, Startup-folder autostart,
  exclusive-fullscreen lowering, and negative-origin multi-monitor coverage.
- Added PyInstaller/Inno Setup packaging, explicit preserve-or-purge uninstall,
  optional timestamped code signing; Windows builds and releases are deferred.
- Public Windows support remains gated on a production-signed installer and the
  documented Windows 10/11 physical/VM DPI validation matrix.

**1.7.0**
- Added opt-in, 15-second context polling with Linux/X11 idle and fullscreen
  detection, local network and low-battery events, and per-application quiet rules.
- Added optional native MPRIS media controls in the tray and CLI plus Secret
  Service keychain hooks for integrations that need credentials.
- Added a disabled-by-default, read-only Local Calendar plugin with upcoming
  event reminders, meeting-aware quiet mode, and explicit data-access disclosures.
- Context, media, and calendar data remain local; unsupported capabilities are
  reported and disabled instead of using unreliable fallbacks.

**1.6.0**
- Added plugin API 1 with versioned metadata, lifecycle, app compatibility, required platform capabilities, and per-plugin permissions.
- Added an isolated event bus and limited contribution APIs for actions, reminders, tray items, and Preferences pages.
- Added built-in-first registration and external discovery without importing external code until the plugin is explicitly enabled.
- Added Preferences and CLI/IPC plugin controls, a disabled-by-default example plugin, and a documented external-plugin example.
- Plugin activation and callback failures now disable and clean up only the faulty plugin while the core application continues running.

**1.5.0**
- Replaced fixed wellness controls with general one-time, daily, weekday, and
  interval reminders plus local schedule phrase parsing.
- Added done, missed, and snoozed reminder history, quiet-hours urgency rules,
  and lossless migration from the previous wellness fields.
- Added safe built-in/application/URL actions and command actions that require
  explicit warning confirmation and execute without a shell.
- Added reminder/action Preferences, tray, CLI, and single-instance IPC controls.

**1.4.0**
- Added a local focus timer with configurable focus, short-break and long-break durations, long-break cadence, and start/pause/resume/skip/stop actions.
- Added Focus controls to Preferences, the tray, CLI and single-instance IPC.
- Running and paused sessions restore after restart using versioned local state; completed focus sessions feed daily totals and a seven-day history.
- Bolt now has focus/break face states, a live timer badge and a completion celebration that honors reduced motion and silent mode.
- Completion notifications respect do-not-disturb, configured active hours and detectable fullscreen applications.

**1.3.0**
- New default character: **Bolt**, a soft-edged desktop companion with a large
  expressive screen, luminous eyes, molded shell, oversized boots and
  state-specific animation.
- New Circuit White theme and robot artwork for the app icon, tray, live
  preferences preview and pose-sheet tool. Boo and Mochi remain selectable.

**1.2.0**
- Wellness reminders: breakfast, lunch, snack, dinner, wind-down, water and
  stretch breaks, with active hours, grace window, snooze and daily state.
- Reminder cards with Done / Snooze buttons beside the buddy, plus themed
  animations (water droplets, hearts, music notes, Zzz) and generated chimes.
- Tray "Reminders" menu, preferences group with time pickers and interval
  sliders, and `remind` / `reminders` CLI commands.
- `status` now reports the reminder card state for troubleshooting.

**1.1.0**
- New character: **Boo-ombastic** the ghost (floaty physics, dance mode, music
  notes, wisps) — now the default; Mochi the cat is still selectable.
- Drag the buddy anywhere on screen, including the top edge (the window's local
  foot offset absorbs Mutter's on-screen placement clamp).
- Window perching: detects the focused browser (near the search bar) and
  terminal (near the prompt) and climbs onto it; follows the window when it
  moves and floats back down when you switch away.
- `dance` and `status` commands, tray "Dance!" and "Character" menus.
- Smaller canvas window → ~30 % less CPU while visible.

**1.0.0**
- Initial release: Mochi the cat, tray, preferences, autostart, installer.

## License

MIT — see [LICENSE](LICENSE).
