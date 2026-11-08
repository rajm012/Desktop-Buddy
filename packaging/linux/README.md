# Desktop Buddy for Linux

This archive includes Python and Qt. It needs no Python installation or network
access to run. Supported binary baseline: Ubuntu 24.04 or newer, x86_64,
glibc 2.39 or newer. X11 provides the full experience; Wayland has reduced window
control. A graphical desktop and its graphics/X11 libraries are required.

Run the portable application from this folder:

```bash
./desktop-buddy
./desktop-buddy --diagnose
```

Keep `desktop-buddy` beside `_internal/`; do not move the executable alone.

Or install for your user, including an application-menu entry and login startup:

```bash
./install.sh                 # --no-autostart skips login startup
```

The installer copies the bundle to `~/.local/share/desktop-buddy/app` (or beneath
`XDG_DATA_HOME`). You can then delete the extracted archive. Run the installed
`uninstall.sh` to remove it; `--purge` also removes settings, history and cache.
Reinstalling a new release preserves those files.

If Qt reports missing X11 libraries, install your distribution's packages for
`libxcb-cursor0`, `libegl1` and `libxkbcommon-x11-0`. GNOME may need an
AppIndicator extension for the tray; the buddy's right-click menu also works.

Release source and documentation: https://github.com/rajm012/Desktop-Buddy
See LICENSE and THIRD_PARTY_NOTICES.md for licensing information.
