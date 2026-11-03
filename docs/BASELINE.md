# Phase 0 baseline

This document defines the supported Desktop Buddy 1.3 baseline. Changes in
later roadmap phases should retain this behaviour unless a release explicitly
documents a replacement.

## Supported features

- Linux desktop operation, with full window control on X11.
- Bolt, Boo-ombastic and Mochi renderers with seven colour themes.
- Idle, walk, run, jump/fall, land, dance, sleep, drag and window-perch states.
- Transparent, frameless, always-on-top presentation with optional click-through.
- Mouse dragging/throwing, cursor tracking, double-click interaction and resizing.
- Browser and terminal perching through active-window detection.
- Tray and context menus, animated preferences preview and XDG autostart.
- Local wellness schedules for meals, water, stretch breaks and wind-down, with
  chimes, toast cards, completion and snoozing.
- Command-line controls connected to one running instance over local IPC.
- Local JSON persistence for settings and wellness state. Both files carry a
  schema version and are upgraded without inspecting character display names.

The eight required Bolt pose references are in [screenshots](screenshots/):
idle, walk, run, jump, fall, land, dance and sleep. They can be regenerated with:

```bash
QT_QPA_PLATFORM=offscreen python tools/preview.py \
  docs/screenshots/bolt-poses.png robot \
  --individual-dir docs/screenshots
```

## Known limitations

- X11 is the only fully supported display system. Wayland compositors can block
  positioning, always-on-top, sticky-workspace and click-through behaviour.
- Windows has a native backend and packaging preview, but public support remains
  gated on signed installers and Windows 10/11 mixed-DPI validation. macOS is not
  supported yet.
- Perching is heuristic and limited to recognizable X11 browser and terminal
  windows; unusual window managers or application class names may not match.
- Click-through and workspace stickiness depend on best-effort X11 calls.
- Reminder audio depends on Qt Multimedia and an available system audio output.
- The tray icon depends on the desktop's StatusNotifier/AppIndicator support.
- Active-window inspection and some diagnostics are Linux/X11-specific.
- Configuration and state are local to the current user and are not synchronized.
- Automated UI tests use Qt's offscreen backend; release validation on a real X11
  desktop is still required for compositor-specific behaviour.
