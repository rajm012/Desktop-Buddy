# Desktop Buddy Agent Guide

This file is the operational handbook for coding agents working in this repository. Read it before changing code. Use `ROADMAP.md` for product direction and this file for repository navigation, engineering constraints, verification, and the current handoff point.

## 1. Project at a glance

Desktop Buddy is a Python 3.10+ / PyQt6 desktop companion. It renders animated characters in a small transparent, always-on-top window and provides local wellness reminders, tray controls, preferences, onboarding, CLI commands, and single-instance IPC.

Current package version: `1.4.0`.

Primary supported environment: Linux/X11. Linux/Wayland runs in a reduced mode because compositors restrict positioning, active-window inspection, always-on-top behavior, and click-through. Windows and macOS currently use the generic backend and are roadmap work, not supported native implementations.

Guiding product rules:

- Keep the buddy helpful without making it intrusive.
- Keep user data local and make integrations opt-in.
- Keep time, reminder, behavior, and other domain logic independent of Qt and operating-system code whenever practical.
- Put OS-specific functionality behind the platform backend.
- Extend the existing architecture incrementally; do not perform a broad restructuring unless the active phase requires it.
- Finish and test one reliable feature path before adding more integrations.

## 2. Current development status

Last verified: 2026-11-03 on branch `main` at commit `6f057a3`.

Repository state at handoff:

- `main` is synchronized with `origin/main`.
- The working tree was clean before this guide was added.
- Phase 0 is complete: stable baseline, migrations, CI, renderer/CLI/IPC tests, screenshots, and performance measurements.
- Phase 1 is complete: platform backend abstraction and Linux/X11 isolation.
- Phase 2 is complete: tabbed preferences, onboarding, capability status, attention controls, config import/export/reset, and animation previews.
- Phase 3 is complete: pure focus state machine, configurable focus/break durations, tray/CLI/IPC actions, restoration, daily history, character feedback, and attention suppression.
- Phases 4 through 11 have not started.

Important history note: commit `6f057a3` is titled `phase-3`, but its actual changes completed Phase 2. The focus timer was implemented in the working tree after that commit; use current code and tests rather than the old commit name.

Verification at handoff:

- Ruff formatting check: passing.
- Ruff lint check: passing.
- Unit/smoke tests: 95 passing.
- Source distribution and wheel build: passing.

The next roadmap task is Phase 4, Step 1: replace fixed wellness fields with a general reminder model while preserving existing reminder data.

## 3. Repository map

### Top-level files

| Path | Purpose |
| --- | --- |
| `ROADMAP.md` | Product phases, steps, and acceptance criteria. |
| `README.md` | User-facing features, installation, commands, config, and troubleshooting. |
| `BENCHMARKS.md` | Phase 0 startup, CPU, and memory baseline. |
| `pyproject.toml` | Package metadata, dependencies, entry point, and Ruff settings. |
| `requirements.txt` | Minimal runtime dependency list. |
| `install.sh` | User-level Linux installation and autostart setup. |
| `uninstall.sh` | Removes installed launchers; `--purge` also removes user data. |
| `run.sh` | Runs the local application with the repository environment. |
| `scripts/check.sh` | Canonical formatting, lint, test, and build verification. |
| `scripts/fetch_qt_syslibs.sh` | Vendors Linux Qt/XCB runtime libraries when needed. |
| `tools/preview.py` | Renders character/theme pose previews. |
| `.github/workflows/ci.yml` | Linux CI using Python 3.12. |

### Application modules

| Path | Responsibility |
| --- | --- |
| `desktop_buddy/app.py` | Entry point, CLI parsing, controller, lifecycle, IPC, diagnostics, reminders orchestration. |
| `desktop_buddy/behavior.py` | Pure-Python movement/physics/behavior state machine; no Qt dependency. |
| `desktop_buddy/character.py` | Procedural `QPainter` character renderers and tray icon drawing. |
| `desktop_buddy/window.py` | Transparent buddy window, painting loop, input, dragging, positioning, perching. |
| `desktop_buddy/effects.py` | Particle effects such as dust, hearts, notes, drops, and sleep bubbles. |
| `desktop_buddy/config.py` | Config dataclass, validation, migration, atomic JSON persistence, themes/species. |
| `desktop_buddy/wellness.py` | Pure reminder definitions, scheduling, snooze state, and history timestamps. |
| `desktop_buddy/focus.py` | Pure focus/break state machine, versioned state, restoration, and daily history. |
| `desktop_buddy/toast.py` | Reminder card with Done and Snooze actions. |
| `desktop_buddy/sound.py` | Generated WAV reminder chimes. |
| `desktop_buddy/prefs.py` | Six-tab preferences dialog, previews, transactions, and onboarding. |
| `desktop_buddy/tray.py` | System tray icon and shared context menu. |
| `desktop_buddy/platform_utils.py` | Compatibility wrappers around the backend API. |
| `desktop_buddy/platforms/base.py` | Backend contract, capabilities, portable paths, generic backend, Qt audio. |
| `desktop_buddy/platforms/linux.py` | Linux/X11 window inspection, workspace behavior, battery, and autostart. |
| `desktop_buddy/platforms/__init__.py` | Process-wide backend selection and test override. |

### Tests

| Path | Coverage area |
| --- | --- |
| `tests/test_behavior.py` | Physics, autonomous behavior, perching, reduced motion. |
| `tests/test_window_math.py` | Window and buddy coordinate calculations. |
| `tests/test_config.py` | Defaults, validation, migrations, serialization, autostart config. |
| `tests/test_wellness.py` | Meal/interval scheduling, active hours, snooze, persisted state. |
| `tests/test_focus.py` | Focus transitions, deadline accuracy, restoration, cadence, history, corrupt state. |
| `tests/test_app_cli_ipc.py` | CLI parsing, local socket IPC, config transactions. |
| `tests/test_platform_backend.py` | Paths, capabilities, Linux services, architecture isolation. |
| `tests/test_prefs_smoke.py` | Preferences/onboarding construction, cancellation, capability messaging. |
| `tests/test_renderer_smoke.py` | Every character/theme combination renders visible pixels. |

Supporting documents:

- `docs/BASELINE.md`: supported baseline features and known constraints.
- `docs/PLATFORM_BACKENDS.md`: backend contract and platform-extension notes.
- `docs/screenshots/`: baseline Bolt pose images.

## 4. Runtime architecture and data flow

The normal application path is:

1. `desktop_buddy.app.main()` parses CLI arguments and selects a platform backend with `get_backend()`.
2. Control commands attempt to contact the running process through a `QLocalSocket`.
3. If no control command is being sent and no instance is active, `main()` creates `QApplication`, loads `Config`, and constructs `Controller`.
4. `Controller` owns the buddy window, tray, preferences, reminder and focus
   engines, toast queue, save timers, and local IPC server.
5. `BuddyWindow` owns the `Brain` behavior state and renders the selected character and particle effects.
6. Pure domain modules calculate state; Qt/UI modules schedule work and display the results; the backend performs supported OS operations.

Maintain these boundaries:

- `behavior.py`, `wellness.py`, and `focus.py` should remain deterministic, headless, and unit-testable.
- `app.py` coordinates services but should not become the home for domain rules.
- `window.py`, `prefs.py`, `tray.py`, and `toast.py` are Qt presentation layers.
- Native calls, platform paths, autostart details, active-window inspection, and platform capability decisions belong under `desktop_buddy/platforms/`.
- Unsupported capabilities must be visible and disabled in the UI rather than failing silently.

## 5. Persistence and schemas

Paths come from `PlatformBackend.paths()`. On standard Linux installations the important files are normally:

- Config: `~/.config/desktop-buddy/config.json`
- Runtime state: `~/.local/state/desktop-buddy/`
- Wellness state: `~/.local/state/desktop-buddy/reminders.json`
- Focus state/history: `~/.local/state/desktop-buddy/focus.json`
- Log: `~/.local/state/desktop-buddy/desktop-buddy.log`
- Generated/cache data: backend-provided cache directory

Do not hard-code these paths in application logic. Always use backend paths.

Config rules:

- `Config` is a dataclass in `config.py`.
- Current config schema version is `3`.
- `Config.save()` writes a temporary file and atomically replaces the target.
- Unknown JSON keys are ignored when loading.
- Values are normalized and clamped after migration.
- A persisted-format change requires a schema-version increment, migration, round-trip tests, invalid-input tests, and documentation updates.
- Migrations must use stable stored fields, never display names or translated text.

Wellness state rules:

- Current wellness schema version is `1`.
- Datetimes are local, timezone-naive ISO strings in the current implementation.
- Invalid or non-mapping persisted data falls back safely.
- State changes must remain backward compatible unless a tested migration is added.

Focus runtime/history data is kept separate from preferences in a versioned, atomically written state file. Follow the same pattern for future live/history data.

## 6. Platform capability rules

`PlatformBackend` is the only supported boundary for operating-system services. The capability enum currently covers paths, autostart, battery, active windows, always-on-top, workspace behavior, click-through, audio, and diagnostics.

When adding a platform-dependent feature:

1. Add or extend the contract in `platforms/base.py`.
2. Give the generic backend a safe unavailable/default implementation.
3. Implement Linux behavior in `platforms/linux.py`.
4. Report availability and a human-readable reason through the capability model.
5. Disable or explain unavailable UI actions in preferences and tray controls.
6. Add isolated backend tests using injected environment and temporary paths.
7. Keep `ctypes`, X11 libraries, Linux filesystem probing, and Linux-specific command/path assumptions out of non-platform modules.

Do not assume X11 merely because the OS is Linux. Wayland limitations are an expected supported condition.

## 7. UI and controller conventions

- The app is single-instance. New CLI invocations send newline-delimited local IPC commands to the primary process.
- Add a new controllable feature consistently across parser, command dispatch, controller method, tray UI, and tests where the roadmap requires those entry points.
- Preferences apply changes live through controller setters.
- Cancel must restore the complete opening snapshot, including external state such as autostart where applicable.
- New background behavior needs an explicit enable/disable control.
- Reduced motion, silent mode, do-not-disturb, and platform limitations must be respected by new features.
- Do not steal keyboard focus or turn the buddy into a normal taskbar window.
- Keep dialogs usable on common laptop screens.
- Preserve high-DPI behavior; the renderer and geometry operate in logical pixels and Qt handles device scaling.

The Focus tab in `prefs.py` provides live state, actions, durations, cadence, attention settings, and seven-day history. Keep its controls synchronized with tray and CLI behavior.

## 8. Development commands

Create/install the development environment once:

```bash
.venv/bin/pip install -e '.[dev]'
```

Run the complete required check:

```bash
PATH="$PWD/.venv/bin:$PATH" ./scripts/check.sh
```

The script performs:

1. Ruff format verification.
2. Ruff linting.
3. Offscreen unittest discovery.
4. Source distribution and wheel builds.

Useful narrower commands:

```bash
PATH="$PWD/.venv/bin:$PATH" python -m ruff format --check desktop_buddy tests tools
PATH="$PWD/.venv/bin:$PATH" python -m ruff check desktop_buddy tests tools
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m unittest tests.test_behavior -v .venv/bin/python tools/preview.py /tmp/buddy-preview.png ./run.sh --diagnose
```

Run the live app only when a display/session is available. Headless verification must use `QT_QPA_PLATFORM=offscreen`.

## 9. Coding and testing standards

- Target Python 3.10 syntax and behavior even if local development uses 3.12.
- Use Ruff's configured 88-character line length and selected lint rules.
- Prefer dataclasses and enums for domain state.
- Inject clocks, random generators, environments, and filesystem roots when it makes logic deterministic and testable.
- Avoid real sleeps in tests; advance an injected time source instead.
- Keep UI smoke tests offscreen and avoid dependence on an actual tray, audio device, X server, or user configuration.
- Test public outcomes and state transitions, not animation-frame accidents.
- Add regression tests with every bug fix.
- Keep renderer changes covered across every character and theme.
- Keep performance-sensitive polling modest; the current reminder scheduler wakes every 20 seconds and the rendering loop adapts its frame rate.
- Preserve startup and CPU baselines unless a documented feature justifies a measured change.

Before considering work complete:

- Relevant focused tests pass.
- The full `scripts/check.sh` passes.
- New user-visible behavior is documented in `README.md`.
- Completed roadmap checkboxes and acceptance criteria are updated accurately.
- Schema changes include migrations and tests.
- Platform-dependent behavior has capability handling and backend tests.
- The working tree is reviewed so unrelated user changes are not overwritten.

## 10. Phase 3 implementation reference

Phase 3 is complete. This section records the implemented design so later work does not accidentally break its guarantees.

Roadmap order:

1. Create a platform-independent focus-session state machine.
2. Support focus, short-break, and long-break durations.
3. Add start, pause, resume, skip, and stop actions.
4. Add tray and CLI controls.
5. Give Bolt distinct focus, break, and completion animations.
6. Persist an interrupted session and restore it after restart.
7. Store local daily totals and display a small history view.
8. Respect quiet hours and fullscreen/do-not-disturb settings.

Implemented structure:

### Pure focus engine

- `desktop_buddy/focus.py` owns the state machine and versioned state.
- Session kind (`focus`, `short_break`, `long_break`) is separate from lifecycle status (`stopped`, `running`, `paused`); completion is emitted as an event.
- Absolute deadlines from an injected wall clock provide sleep/resume accuracy; UI frame ticks never decrement the session clock.
- Paused sessions store their remaining time explicitly.
- Start, pause, resume, skip, stop, and time-completion transitions are tested.
- Long-break cadence is configurable and based on completed focus sessions.
- Pure methods return state/events and do not import Qt.
- `tests/test_focus.py` covers transitions, invalid/no-op actions, large clock jumps, pause/resume, cadence, restoration, corrupt state, and midnight.

### Settings and versioned state

- Validated duration/cadence preferences live in config schema version 3.
- `focus.json` stores versioned runtime state/history under the backend state directory.
- Active and paused sessions restore safely after restart.
- Atomic writes tolerate missing, corrupt, and older files.
- A completed focus session is credited to its local completion date, including sessions crossing midnight.

### Controller, timers, CLI, and IPC

- `Controller` owns the focus engine and checks it once per second.
- Controller and IPC dispatch expose start, pause, resume, skip, stop, and status.
- `build_parser()` exposes the matching CLI commands.
- The buddy animation timer is not used as a focus time source.
- Parser, IPC, restoration, and controller integration have test coverage.

### Preferences and tray

- The Focus tab contains durations, cadence, current state, actions, attention settings, and seven-day history.
- Tray actions enable or disable themselves from the focus lifecycle.
- Cancel restores settings without modifying live focus runtime state.
- Manual controls remain available while do-not-disturb suppresses automatic completion interruptions.

### Character feedback and attention rules

- Bolt uses different focus/break eye treatments, while the window provides a live badge and completion celebration without coupling the focus engine to Qt.
- Completion feedback respects reduced motion and silent mode.
- Completion notifications are suppressed by do-not-disturb, quiet hours, or detectable fullscreen windows while completed state/history remains saved.
- Unsupported fullscreen detection is handled through platform capabilities.

Phase 3 acceptance criteria:

- Timer accuracy survives rendering frame-rate changes and computer sleep.
- Tray and CLI can control sessions.
- An active session restores correctly after restart.
- The feature requires no account or network connection.

All eight Phase 3 steps and all acceptance criteria are checked in `ROADMAP.md`. The next implementation handoff is Phase 4: custom reminders and quick actions.

## 11. Known constraints and common pitfalls

- Linux/X11 is the only full desktop backend today.
- Wayland cannot reliably support arbitrary positioning, click-through, global window inspection, or forced always-on-top using standard Qt alone.
- A tray icon may be unavailable on desktops without AppIndicator support; the buddy context menu must remain usable.
- Qt audio can be unavailable in test/headless environments and must degrade safely.
- The application intentionally has no account, cloud service, or network requirement.
- Config module path constants are initialized from the selected backend at import time. Tests that override backends should do so deliberately and avoid assuming late overrides rewrite already-imported constants.
- `Controller._status_text()` reads selected private window fields for diagnostics. Do not copy this pattern into feature logic.
- Build output directories (`build/`, `dist/`, `*.egg-info`) are generated artifacts, not feature source.
- Do not use character names as stable IDs. Use species keys such as `robot`, `ghost`, and `mochi`.
- Do not put native platform code into `behavior.py`, `wellness.py`, or `focus.py`.

## 12. Agent workflow

For every task:

1. Read the relevant roadmap phase, this guide, and the modules/tests in scope.
2. Inspect `git status` before editing; preserve unrelated user changes.
3. State assumptions when requirements are ambiguous, but prefer safe, reversible progress within the requested scope.
4. Make the smallest coherent change that completes a usable slice.
5. Add or update tests alongside implementation.
6. Run focused tests during development and the full check before handoff.
7. Update user documentation and roadmap status only when behavior is real.
8. Report what changed, verification performed, remaining work, and any known limitations.

Avoid:

- Large rewrites unrelated to the active roadmap step.
- Silent capability failures.
- UI-driven clocks for timer correctness.
- Network dependencies for local features.
- Destructive Git operations or overwriting unrelated work.
- Checking a roadmap box merely because scaffolding or placeholder UI exists.

## 13. Sources of truth

When documents disagree, use this order:

1. Current code and passing tests for actual implemented behavior.
2. `ROADMAP.md` for intended scope and phase acceptance criteria.
3. `README.md` for promised user-facing behavior.
4. This file for agent workflow and architecture guidance.
5. Commit messages only as historical hints; they may be imprecise.

Keep these sources synchronized as the project evolves.
