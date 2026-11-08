# Local Linux releases

The current public release is Linux-only. Build on Ubuntu 24.04 x86_64 with
Python 3.12 and glibc 2.39. The bundle includes Python and Qt; users need a
compatible graphical desktop and system graphics/X11 libraries. X11 is fully
supported and Wayland provides reduced window control. Windows builds and
release workflows are deferred.

## Build and publish

Install `python3-venv`, Git and the GitHub CLI (`gh`) on the build machine. Log in
with `gh auth login` using an account allowed to push and create releases in
`rajm012/Desktop-Buddy`. GitHub CLI uploads use the API, not Actions minutes.

Commit the release changes on `main`, then run:

```bash
./scripts/build_linux.sh
./scripts/release_linux.sh --publish-only
```

`./scripts/release_linux.sh` performs both steps. `--build-only` builds without
publishing. Both commands work from any directory. The build creates the
separate `.venv-release/` environment from `requirements-release.txt`, leaving
the development environment alone. It runs formatting, lint, all offscreen
tests, source/wheel builds, PyInstaller and packaged CLI/Qt diagnostic checks.

Assets in `dist/releases/v<VERSION>/`:

- `desktop-buddy-<VERSION>-linux-x86_64.tar.gz`: standalone bundle with portable
  launch, user-level install/uninstall scripts, icon and dependency licenses.
- `desktop_buddy-<VERSION>-py3-none-any.whl`: Python package (requires Python and
  PyQt6; Linux is the supported release platform).
- `desktop_buddy-<VERSION>.tar.gz`: source distribution, including build scripts.
- `BUILD_INFO.json`: source commit, clean/dirty state, Python/glibc and package
  versions. A copy is also inside the standalone archive.
- `SHA256SUMS`: checksums of all four assets above.

Publishing requires a clean checkout at the exact recorded build commit and
valid checksums. It pushes `main` and the annotated version tag, creates a draft
release, uploads the assets, then makes the release public. An interrupted draft
upload can be retried with `--publish-only`; public releases are never overwritten.
Do not edit source after building: commit your edits and rebuild first.

## Verify an archive

```bash
cd dist/releases/v1.8.0
sha256sum -c SHA256SUMS
tar -xzf desktop-buddy-1.8.0-linux-x86_64.tar.gz
./desktop-buddy/desktop-buddy --version
./desktop-buddy/desktop-buddy --diagnose
./desktop-buddy/install.sh --no-autostart
```

Check the app on an X11 desktop, including tray/context menu, animation,
preferences, CLI/IPC and autostart. Installation copies the app into
`${XDG_DATA_HOME:-~/.local/share}/desktop-buddy/app` and links the executable from
`~/.local/bin`. Test installation and uninstall with temporary HOME/XDG roots to
avoid changing your daily installation. Upgrades preserve settings and state;
uninstall preserves them unless `--purge` is explicitly passed.

## Next release

1. Update `pyproject.toml`, `desktop_buddy/__init__.py` and the retained version
   in `packaging/windows/DesktopBuddy.iss` together (the source test checks it).
2. Add reviewed notes at `docs/releases/v<VERSION>.md` and update the README
   download examples/changelog.
3. Commit, run the local build, verify the bundle, and publish.

Use the source tag and pinned `requirements-release.txt` on the documented build
baseline to rebuild the same application. Archive bytes are not guaranteed to
be identical because build tools may include timestamps and local build paths.
`BUILD_INFO.json` makes the source and dependency versions inspectable.

## GitHub Actions

`.github/workflows/ci.yml` runs Linux checks only on `workflow_dispatch`; pushes,
tags and pull requests consume no hosted-runner minutes. The Windows signed
release workflow is removed. Do not dispatch the manual Linux workflow while
Actions credits are exhausted; use `./scripts/check.sh` locally instead.
