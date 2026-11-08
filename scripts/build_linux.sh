#!/usr/bin/env bash
# Build and verify all Linux release assets locally. No GitHub Actions.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
if [ "${1:-}" = "--help" ]; then
  echo "Usage: ./scripts/build_linux.sh (Python 3.12, Linux x86_64, glibc 2.39)"
  exit 0
fi
if [ "$#" -ne 0 ]; then
  echo "Unknown argument: $1" >&2
  exit 2
fi
"$PYTHON" - <<'PY'
import platform
import sys
if sys.platform != "linux" or platform.machine() != "x86_64":
    sys.exit("Build on Linux x86_64; Windows builds are deferred.")
if sys.version_info[:2] != (3, 12):
    sys.exit("Use Python 3.12 for the release environment.")
if platform.libc_ver() != ("glibc", "2.39"):
    sys.exit("Build on Ubuntu 24.04 / glibc 2.39 for the supported binary baseline.")
PY

VENV="$ROOT/.venv-release"
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi
export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"
python -m pip install -r requirements-release.txt
python -m pip install --no-deps --no-build-isolation -e .
VERSION="$(python -c 'from desktop_buddy import __version__; print(__version__)')"
RELEASE_DIR="$ROOT/dist/releases/v$VERSION"
mkdir -p "$RELEASE_DIR"
export BUDDY_DIST_DIR="$RELEASE_DIR"
./scripts/check.sh --no-isolation
python -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist/linux" --workpath "$ROOT/build/linux" \
  desktop-buddy-linux.spec
BUNDLE="$ROOT/dist/linux/desktop-buddy"
cp packaging/linux/install.sh packaging/linux/uninstall.sh packaging/linux/README.md \
  LICENSE THIRD_PARTY_NOTICES.md requirements-release.txt "$BUNDLE/"
chmod +x "$BUNDLE/install.sh" "$BUNDLE/uninstall.sh"
python scripts/linux_release.py record "$RELEASE_DIR" "$BUNDLE"
"$BUNDLE/desktop-buddy" --version
QT_QPA_PLATFORM=offscreen "$BUNDLE/desktop-buddy" --diagnose
tar -czf "$RELEASE_DIR/desktop-buddy-$VERSION-linux-x86_64.tar.gz" \
  -C "$ROOT/dist/linux" desktop-buddy
cp "$BUNDLE/BUILD_INFO.json" "$RELEASE_DIR/BUILD_INFO.json"
(
  cd "$RELEASE_DIR"
  sha256sum "desktop-buddy-$VERSION-linux-x86_64.tar.gz" \
    "desktop_buddy-$VERSION.tar.gz" "desktop_buddy-$VERSION-py3-none-any.whl" \
    BUILD_INFO.json > SHA256SUMS
)
echo "Built Linux release assets in $RELEASE_DIR"
