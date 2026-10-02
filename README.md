# Desktop Buddy 🐾

A tiny creature that lives on your Ubuntu desktop. Mochi walks around, runs,
jumps, falls, sleeps, watches your cursor and reacts to being poked — while you
get on with your work.

Works best on **X11 / "Ubuntu on Xorg"**. See [Wayland](#wayland) below.

---

## Features

- Frameless, transparent, always-on-top window — no taskbar entry, no focus stealing
- Autonomous behaviour: idle breathing, blinking, looking around, walking, running,
  jumping (gravity + squash & stretch), landing dust, sleeping with `Zzz`
- Eyes follow the cursor; the buddy chases it when playful
- Drag & throw with real physics; double-click for a happy hop; `Ctrl`+wheel to resize
- Right-click menu and a system-tray icon (GNOME AppIndicator)
- Preferences dialog with a **live animated preview**
- 6 colour themes, adjustable size / speed / frame rate / sleep timeout
- Adaptive frame rate and a battery saver (lower fps on battery)
- Remembers its position and settings between sessions
- Single instance: launching again just shows the existing buddy
- XDG autostart entry so it comes back when you log in
- All artwork drawn procedurally with `QPainter` — crisp at any scale (including
  your 2.5× fractional HiDPI setup), no bitmap assets to ship

## Install

Everything is user-level; **no sudo needed**.

```bash
cd ~/desktop-buddy
./install.sh                 # add --no-autostart to skip login startup
```

The installer:

1. creates a Python 3.12 virtual environment in `.venv/` and installs PyQt6;
2. vendors `libxcb-cursor` into `vendor/syslibs/` if your system lacks it
   (Qt ≥ 6.5 needs it for the X11 platform plugin — this machine was missing it);
3. installs the launcher `~/.local/bin/desktop-buddy`;
4. installs the application-menu entry;
5. enables autostart (`~/.config/autostart/desktop-buddy.desktop`).

> If the `desktop-buddy` command is not found right away, your shell's `PATH`
> predates the new `~/.local/bin` directory. Use `~/.local/bin/desktop-buddy`
> or log out/in once (Ubuntu adds it automatically at login).

## Usage

```bash
desktop-buddy            # start it (or show it if already running)
```

Then:

| Action | How |
| --- | --- |
| Move it | Drag with the left mouse button, release to throw |
| Make it happy | Double-click it |
| Menu | Right-click it, or click the tray icon |
| Resize | `Ctrl` + mouse wheel |
| Preferences | Tray menu → Preferences… (or `desktop-buddy settings`) |

### Command line

```bash
desktop-buddy quit | show | hide | toggle | pause | resume | settings
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
| `name` | `"Mochi"` | Displayed in the greeting/about |
| `theme` | `"mint"` | `mint`, `peach`, `lavender`, `sky`, `sakura`, `charcoal` |
| `scale` | `0.8` | 0.5 – 1.8 |
| `speed` | `1.0` | 0.4 – 2.5 |
| `fps` | `30` | 10 – 60 (adaptive; idles at ≤ 15) |
| `always_on_top` | `true` | Keep above other windows |
| `click_through` | `false` | Mouse input passes through to apps below |
| `reduce_on_battery` | `true` | 20 fps active / 12 fps idle on battery |
| `playful` | `true` | Chase the cursor sometimes |
| `can_sleep` | `true` | Nap after being idle |
| `sleep_after` | `180` | Seconds of no interaction before sleeping |
| `position_x` | auto | Last position on screen |

## Performance

Measured on this machine (i5-13500H, 2.5× HiDPI, 165 Hz panel, X11, Qt 6.11):

| State | CPU (one core) | Memory |
| --- | --- | --- |
| Active (walking/jumping) | ~9 % | ~86 MB |
| Idle / sleeping | lower (adaptive fps) | ~86 MB |
| Paused or hidden | ~1 % | ~86 MB |

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
  character.py      procedural QPainter creature (poses, squash & stretch)
  effects.py        dust, sparkles, hearts, Zzz particles
  prefs.py          preferences dialog + live preview
  tray.py           tray icon and shared context menu
  config.py         JSON settings, themes, validation
  platform_utils.py battery, autostart, paths
install.sh / uninstall.sh / run.sh
scripts/fetch_qt_syslibs.sh
tests/              unittest suite (no display required)
tools/preview.py    renders a pose/theme sheet to PNG
```

## Development

```bash
.venv/bin/pip install .                 # reinstall after source changes
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/preview.py /tmp/buddy-preview.png
./run.sh --diagnose
```

The behaviour engine (`behavior.py`) has no Qt dependency, so the physics and
state machine can be tested headlessly.

## License

MIT — see [LICENSE](LICENSE).
