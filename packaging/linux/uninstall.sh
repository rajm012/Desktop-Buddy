#!/usr/bin/env bash
set -euo pipefail

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help) echo "Usage: ./uninstall.sh [--purge]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
BIN="$HOME/.local/bin/desktop-buddy"
if [ -x "$BIN" ]; then
  "$BIN" quit >/dev/null 2>&1 || true
fi
rm -f "$BIN" "$DATA_DIR/applications/desktop-buddy.desktop" \
  "$CONFIG_DIR/autostart/desktop-buddy.desktop"
rm -rf "$DATA_DIR/desktop-buddy/app"
if [ "$PURGE" = 1 ]; then
  rm -rf "$CONFIG_DIR/desktop-buddy" "$STATE_DIR/desktop-buddy" \
    "${XDG_CACHE_HOME:-$HOME/.cache}/desktop-buddy"
  echo "Removed Desktop Buddy and its settings, history and cache."
else
  echo "Removed Desktop Buddy. Settings and history were preserved."
fi
