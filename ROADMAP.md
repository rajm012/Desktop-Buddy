# Desktop Buddy Development Roadmap

This roadmap develops Desktop Buddy from a Linux/X11 desktop pet into a useful,
extensible companion that can run across desktop operating systems. Every phase
should leave the application usable, tested, and releasable.

## Guiding principles

- Keep Bolt helpful without making it intrusive.
- Preserve privacy: integrations are opt-in and data stays local by default.
- Keep animation and reminder logic independent from operating-system code.
- Deliver desktop support before building a separate mobile application.
- Add one reliable integration at a time instead of building many incomplete ones.

## Target architecture

```text
desktop_buddy/
  core/                 platform-independent application logic
    events.py
    actions.py
    reminders.py
    focus.py
  characters/           character renderers and animation poses
  integrations/         optional calendar, media and system integrations
  platforms/
    base.py              platform capability interface
    linux.py
    windows.py
    macos.py
  ui/                    Qt windows, tray, preferences and onboarding
  plugins/               plugin discovery and built-in plugins
```

The restructuring should be incremental. Existing modules should be moved only
when a phase needs them; avoid a large rewrite.

---

## Phase 0 — Establish a stable baseline

Goal: make later changes measurable and safe.

### Steps

- [x] Document the currently supported features and known limitations.
- [x] Add screenshots for Bolt's idle, walk, run, jump, fall, land, dance and sleep poses.
- [x] Add renderer smoke tests for every character and theme.
- [x] Add tests for CLI parsing, single-instance IPC and config migrations.
- [x] Add a `schema_version` field to configuration and wellness state files.
- [x] Set up continuous integration on Linux with formatting, tests and package builds.
- [x] Record baseline startup time, idle CPU use and active CPU use.

### Acceptance criteria

- [x] Tests run with one documented command.
- [x] Configuration upgrades do not depend on character names.
- [x] CI builds and tests every commit.
- [x] Performance measurements are recorded in the README or a benchmark document.

---

## Phase 1 — Separate platform-specific code

Goal: prepare the current application for Windows and macOS without changing its
visible behaviour.

### Steps

- [x] Define a `PlatformBackend` interface with capabilities for:
   - configuration and state paths;
   - autostart;
   - battery status;
   - active-window information;
   - always-on-top and workspace behaviour;
   - click-through support;
   - audio playback;
   - session diagnostics.
- [x] Move the current X11 implementation into `platforms/linux.py`.
- [x] Replace direct X11 construction in the window and controller with backend calls.
- [x] Replace XDG-only paths with Qt `QStandardPaths` or backend-provided paths.
- [x] Replace `os.getuid()` in the IPC server name with a cross-platform user/session ID.
- [x] Replace `paplay`, `pw-play` and `aplay` with a Qt audio implementation.
- [x] Add a capability model so unsupported features are disabled in the UI instead
   of silently failing.
- [x] Keep X11 behaviour and tests unchanged after the refactor.

### Acceptance criteria

- [x] Linux/X11 retains perching, click-through, autostart and audio.
- [x] Core modules do not import `ctypes`, X11 libraries or Linux paths.
- [x] The preferences dialog explains when a platform capability is unavailable.
- [x] Existing tests pass and platform backends have isolated unit tests.

---

## Phase 2 — Improve the settings and onboarding experience

Goal: make the growing feature set understandable.

### Steps

1. [x] Split preferences into tabs: Character, Behaviour, Reminders, Focus,
   Integrations and System.
2. [x] Add first-run onboarding for character, scale, reminder hours and autostart.
3. [x] Add a platform capability/permission status page.
4. [x] Add reduced-motion, silent and do-not-disturb options.
5. [x] Add import, export and reset controls for configuration.
6. [x] Add a preview for themes and important animation states.

### Acceptance criteria

- [x] Preferences fit on common laptop screens.
- [x] Every background integration can be disabled.
- [x] Cancel reliably restores the previous configuration.
- [x] Reduced-motion mode removes high-energy movement and particles.

---

## Phase 3 — Focus timer

Goal: deliver the first major productivity feature.

### Steps

1. Create a platform-independent focus-session state machine.
2. Support focus, short-break and long-break durations.
3. Add start, pause, resume, skip and stop actions.
4. Add tray and CLI controls.
5. Give Bolt distinct focus, break and completion animations.
6. Persist an interrupted session and restore it after restart.
7. Store local daily totals and display a small history view.
8. Respect quiet hours and fullscreen/do-not-disturb settings.

### Acceptance criteria

- Timer accuracy survives UI frame-rate changes and computer sleep.
- Sessions can be controlled from the tray and CLI.
- Restarting the application restores an active session correctly.
- No account or network connection is required.

---

## Phase 4 — Custom reminders and quick actions

Goal: allow users to configure Bolt around their own routine.

### Steps

1. Replace fixed reminder fields with a general reminder model.
2. Support one-time, daily, weekday and interval reminders.
3. Add local parsing for phrases such as “in 20 minutes” and “weekdays at 9”.
4. Add reminder history with done, missed and snoozed states.
5. Create an action registry for safe built-in actions.
6. Add configurable actions for launching applications, opening URLs and running
   explicitly approved commands.
7. Add confirmation and clear warning UI for custom commands.
8. Expose reminders and actions through CLI and IPC.

### Acceptance criteria

- Existing wellness reminders migrate without data loss.
- Custom commands never run unless explicitly configured by the user.
- Reminder recurrence and time-zone behaviour are unit-tested.
- Quiet hours prevent non-urgent interruptions.

---

## Phase 5 — Plugin system

Goal: add integrations without continually enlarging the controller.

### Steps

1. Define plugin metadata, lifecycle and compatibility version fields.
2. Create an internal event bus for application and system events.
3. Expose limited APIs for actions, reminders, tray items and settings pages.
4. Load built-in plugins before supporting external plugins.
5. Add enable/disable controls and per-plugin permissions.
6. Isolate plugin failures so they cannot crash the buddy.
7. Document a minimal example plugin.
8. Add external plugin discovery only after the API is stable.

### Acceptance criteria

- A faulty plugin is disabled and logged without closing the application.
- Plugins declare required platform capabilities and permissions.
- The core application works with every optional plugin disabled.
- The example plugin is covered by an integration test.

---

## Phase 6 — Context awareness and system integrations

Goal: make Bolt useful while respecting user attention and privacy.

### Steps

1. Add reliable idle-time and fullscreen detection to each desktop backend.
2. Add per-application profiles and do-not-disturb rules.
3. Add low-battery and network-state events.
4. Add optional media controls through platform-native APIs.
5. Add an optional calendar plugin with read-only access first.
6. Add upcoming-event reminders and meeting-aware quiet mode.
7. Show exactly which data each integration reads.
8. Keep all integrations opt-in and local where possible.

### Acceptance criteria

- Bolt does not interrupt fullscreen applications when suppression is enabled.
- Revoking an integration's permission deactivates it cleanly.
- Calendar credentials and tokens are stored using the operating-system keychain.
- System polling has negligible idle CPU impact.

---

## Phase 7 — Windows support

Goal: ship a supported Windows desktop version.

### Steps

1. Implement the Windows backend using Win32 APIs for active windows, geometry,
   always-on-top, click-through and battery state.
2. Implement Windows autostart using the Startup folder or an approved startup task.
3. Validate transparent-window rendering at common DPI scaling levels.
4. Test tray behaviour, single-instance IPC and multi-monitor placement.
5. Disable or adapt features that behave differently under exclusive fullscreen.
6. Create a signed installer and uninstall flow.
7. Add Windows CI for tests and packaged builds.
8. Test Windows 10 and Windows 11 on physical or virtual machines.

### Acceptance criteria

- Installation requires no Python installation.
- Autostart, audio, tray, click-through and active-window perching work.
- The application behaves correctly across mixed-DPI monitors.
- Uninstalling preserves or removes user data according to an explicit choice.

---

## Phase 8 — macOS support

Goal: ship a supported macOS desktop version.

### Steps

1. Implement the macOS backend using AppKit, Quartz and PyObjC where required.
2. Use a floating panel/window level that does not steal focus.
3. Implement click-through and active-application detection.
4. Add guided Accessibility or Screen Recording permission requests only for
   features that require them.
5. Implement login-item support using the current Apple-recommended API.
6. Test Spaces, multiple displays, Retina scaling and fullscreen applications.
7. Build, sign and notarize the `.app` bundle and installer image.
8. Add macOS CI for tests and unsigned development builds.

### Acceptance criteria

- Basic pet behaviour works without sensitive permissions.
- Features requiring permissions explain why before prompting.
- The signed application launches without Gatekeeper warnings.
- Spaces, Retina and multi-monitor behaviour are documented and tested.

---

## Phase 9 — Linux Wayland strategy

Goal: provide an honest, useful experience on modern Linux desktops.

### Steps

1. Define a reduced Wayland mode using only standard Qt capabilities.
2. Disable unsupported arbitrary positioning, global click-through and window
   inspection with clear UI explanations.
3. Investigate layer-shell support for compatible compositors.
4. Prototype an optional GNOME extension for positioning and active-window data.
5. Evaluate KDE-specific integration separately.
6. Keep X11 as the full-featured backend where available.

### Acceptance criteria

- The application starts reliably on GNOME and KDE Wayland sessions.
- Unsupported features never fail invisibly.
- Optional extensions are not required for reminders and focus features.
- Documentation contains an accurate feature matrix by session type.

---

## Phase 10 — Packaging, updates and release engineering

Goal: make releases safe for non-technical users.

### Steps

1. Build packages on Linux, Windows and macOS in CI.
2. Add semantic versioning and generated release notes.
3. Add an opt-in update checker with signed release metadata.
4. Add crash recovery and a user-visible diagnostics/log viewer.
5. Test clean installation, upgrade and uninstall paths.
6. Publish checksums and signatures for every release.
7. Create a platform support and minimum-version policy.

### Acceptance criteria

- Users do not need Python or a terminal to install the application.
- Updates preserve settings and reminder state.
- Diagnostics never expose private information without confirmation.
- Every release can be reproduced from its source tag.

---

## Phase 11 — Android companion application

Goal: build a mobile companion without forcing desktop assumptions onto Android.

The Android application should be a separate project, preferably Kotlin with
Jetpack Compose or Flutter. Reuse product concepts and data formats rather than
the current PyQt window code.

### Steps

1. Choose the first supported experience:
   - home-screen widget;
   - live wallpaper;
   - notification companion;
   - optional floating overlay.
2. Implement reminders and focus sessions before a floating character.
3. Design mobile-specific animations and touch interactions.
4. If an overlay is added, use `SYSTEM_ALERT_WINDOW` and a foreground service.
5. Explain persistent notifications and battery impact before enabling overlays.
6. Add optional encrypted synchronization with the desktop application.
7. Review Google Play policies before distribution.
8. Test different manufacturers' background-process restrictions.

### Acceptance criteria

- Core reminders work without overlay permission.
- The application remains useful if Android terminates background work.
- Synchronization is optional and encrypted.
- Overlay behaviour follows Play Store policy and can be disabled immediately.

### iOS note

iOS does not permit a general always-on-top character over other applications.
An iOS version should use widgets, notifications and Live Activities instead.

---

## Recommended execution order

1. Phase 0 — stable baseline
2. Phase 1 — platform abstraction
3. Phase 2 — settings and onboarding
4. Phase 3 — focus timer
5. Phase 4 — custom reminders and quick actions
6. Phase 5 — plugin system
7. Phase 7 — Windows support
8. Phase 8 — macOS support
9. Phase 9 — improved Wayland support
10. Phase 6 — deeper integrations as plugins mature
11. Phase 10 — polished multi-platform releases
12. Phase 11 — separate Android companion

Windows work begins only after the platform abstraction is complete. Android
work begins only after reminder and focus models are stable enough to share.

## First implementation milestone

Start with Phase 0 and Phase 1 in this order:

1. Add config schema versioning and migrations.
2. Expand renderer, CLI and IPC tests.
3. Add Linux CI and performance baselines.
4. Define the platform capability interface.
5. Move existing Linux/X11 integrations behind that interface.
6. Replace Linux-only paths, IPC naming and sound playback.
7. Verify that the live Linux application behaves exactly as before.

Do not begin new productivity features until this milestone is complete; it is
the foundation for every later desktop platform.
