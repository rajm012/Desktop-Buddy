#!/usr/bin/env bash
# Remove Desktop Buddy user-level artifacts.
set -euo pipefail

PURGE=0
if [ "${1:-}" = "--purge" ]; then
  PURGE=1
fi

BIN="$HOME/.local/bin/desktop-buddy"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications/desktop-buddy.desktop"
AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/desktop-buddy.desktop"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/desktop-buddy"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/desktop-buddy"

if [ -x "$BIN" ]; then
  "$BIN" quit >/dev/null 2>&1 || true
fi
rm -f "$BIN" "$APPS" "$AUTO"

if [ "$PURGE" = "1" ]; then
  rm -rf "$CONF_DIR" "$STATE_DIR"
  echo "Removed launcher, desktop entry, autostart, settings and logs."
else
  echo "Removed launcher, desktop entry and autostart."
  echo "Settings kept in $CONF_DIR (run with --purge to delete them)."
fi
echo "The project folder itself (including .venv) was left untouched."
