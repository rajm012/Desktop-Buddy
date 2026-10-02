#!/usr/bin/env bash
# Desktop Buddy installer - fully user-level, no sudo required.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$APP_DIR/.venv"
PYTHON="${PYTHON:-/usr/bin/python3}"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART=1

for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    -h|--help)
      echo "Usage: ./install.sh [--no-autostart]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

echo "==> Desktop Buddy installer"
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is required")
print(f"    python: {sys.version.split()[0]} ({sys.executable})")
PY

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> Creating virtual environment ($VENV)"
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
echo "==> Installing/updating dependencies"
"$VENV/bin/pip" install --quiet "$APP_DIR"

echo "==> Checking Qt X11 libraries"
bash "$APP_DIR/scripts/fetch_qt_syslibs.sh" "$APP_DIR"

mkdir -p "$BIN_DIR" "$APPS_DIR"

echo "==> Installing launcher ($BIN_DIR/desktop-buddy)"
cat > "$BIN_DIR/desktop-buddy" <<EOF
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$APP_DIR"
if [ -d "\$APP_DIR/vendor/syslibs" ]; then
  export LD_LIBRARY_PATH="\$APP_DIR/vendor/syslibs\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
fi
unset PYTHONPATH
exec "\$APP_DIR/.venv/bin/python" -m desktop_buddy "\$@"
EOF
chmod +x "$BIN_DIR/desktop-buddy"

cat > "$APPS_DIR/desktop-buddy.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Desktop Buddy
GenericName=Desktop pet
Comment=A tiny creature that lives on your desktop
Exec=$BIN_DIR/desktop-buddy
Icon=$APP_DIR/desktop_buddy/assets/icon.svg
Terminal=false
Categories=Utility;Game;
StartupNotify=false
EOF
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

if [ "$AUTOSTART" = "1" ]; then
  "$BIN_DIR/desktop-buddy" autostart on >/dev/null
  echo "==> Autostart enabled (disable: desktop-buddy autostart off)"
else
  echo "==> Autostart skipped (--no-autostart)"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "NOTE: $BIN_DIR is not on your PATH; use the full path or add it." ;;
esac

echo "==> Installed. Start it with: desktop-buddy"
