#!/usr/bin/env bash
# Install the prebuilt bundle for the current user; no Python or downloads.
set -euo pipefail

AUTOSTART=1
for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    -h|--help) echo "Usage: ./install.sh [--no-autostart]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_DIR/desktop-buddy/app"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_DIR/applications"
if [ "$BUNDLE_DIR" = "$INSTALL_DIR" ]; then
  echo "Run this installer from the extracted release archive." >&2
  exit 1
fi
# Check the executable before replacing a previous installation.
"$BUNDLE_DIR/desktop-buddy" --version
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR"
if [ -x "$BIN_DIR/desktop-buddy" ]; then
  "$BIN_DIR/desktop-buddy" quit >/dev/null 2>&1 || true
fi
cp -a "$BUNDLE_DIR/." "$INSTALL_DIR/"
ln -sfn "$INSTALL_DIR/desktop-buddy" "$BIN_DIR/desktop-buddy"

# Desktop-entry quoted arguments escape backslashes, quotes, backticks and $.
desktop_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\`/\\\`}"
  value="${value//\$/\\\$}"
  value="${value//%/%%}"
  printf '"%s"' "$value"
}
cat > "$APPS_DIR/desktop-buddy.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Desktop Buddy
Comment=A tiny creature that lives on your desktop
Exec=$(desktop_quote "$BIN_DIR/desktop-buddy")
Icon=$INSTALL_DIR/_internal/desktop_buddy/assets/icon.svg
Terminal=false
Categories=Utility;Game;
StartupNotify=false
EOF
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if [ "$AUTOSTART" = 1 ]; then
  "$BIN_DIR/desktop-buddy" autostart on
fi
echo "Installed. Start Desktop Buddy from your application menu or $BIN_DIR/desktop-buddy."
echo "Uninstall: $INSTALL_DIR/uninstall.sh (add --purge to remove settings/history)."
