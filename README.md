# Desktop Buddy 👻🐾

Tiny creatures that live on your Ubuntu desktop.

**Boo-ombastic** is a floaty little ghost who drifts around, dances on your
browser's search bar, hangs out near your terminal prompt, investigates your
cursor and gets very excited when poked. **Mochi**, the original round
blob-cat, is still available from the tray menu if you want the classic.

Works best on **X11 / "Ubuntu on Xorg"**. See [Wayland](#wayland) below.

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
- **Two characters**: Boo-ombastic the ghost (floats, dances) and Mochi the cat
  (jumps, wags) — switch live from the tray or with `desktop-buddy character ghost|mochi`
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
| Move it anywhere | Drag with the left mouse button, release to throw |
| Make it dance (Boo) | Double-click it, tray → Dance!, or `desktop-buddy dance` |
| Menu | Right-click it, or click the tray icon |
| Resize | `Ctrl` + mouse wheel |
| Change character | Tray → Character → Boo-ombastic / Mochi |
| Preferences | Tray menu → Preferences… (or `desktop-buddy settings`) |

### Command line

```bash
desktop-buddy quit | show | hide | toggle | pause | resume | dance | settings
desktop-buddy status                    # what is the buddy doing right now?
desktop-buddy character ghost|mochi     # switch characters
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
| `name` | `"Boo-ombastic"` | Displayed in the greeting/about |
| `species` | `"ghost"` | `ghost` (Boo-ombastic) or `mochi` (the cat) |
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
| `perch_on_windows` | `true` | Sit on the focused browser/terminal window |
| `perch_delay` | `1.2` | Seconds a window must stay focused before climbing |
| `position_x` | auto | Last position on screen |

## Performance

Measured on this machine (i5-13500H, 2.5× HiDPI, 165 Hz panel, X11, Qt 6.11):

| State | CPU (one core) | Memory |
| --- | --- | --- |
| Active (walking/dancing/perched) | ~7 % | ~85 MB |
| Idle / sleeping | ~4 % (adaptive fps) | ~85 MB |
| Paused or hidden | ~1 % | ~85 MB |

The window is only ~112 × 128 logical pixels, so even where it overlaps other
windows it blocks almost nothing.

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
  character.py      procedural QPainter creatures (Boo + Mochi)
  effects.py        dust, sparkles, hearts, Zzz, music notes, wisps
  window_probe.py   X11 active-window probe (browser/terminal detection)
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

## Changelog

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
