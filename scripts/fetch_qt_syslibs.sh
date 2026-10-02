#!/usr/bin/env bash
# Vendor libxcb-cursor user-space when the system lacks it (Qt >= 6.5 needs it).
set -euo pipefail

APP_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEST="$APP_DIR/vendor/syslibs"

if ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
  echo "    libxcb-cursor: system copy found"
  exit 0
fi
if [ -f "$DEST/libxcb-cursor.so.0" ]; then
  echo "    libxcb-cursor: already vendored"
  exit 0
fi

ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
mkdir -p "$DEST" "$APP_DIR/vendor/tmp"
cd "$APP_DIR/vendor/tmp"

fetch_deb() {
  if command -v apt-get >/dev/null 2>&1 && apt-get download libxcb-cursor0 >/dev/null 2>&1; then
    return 0
  fi
  local fallback="http://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-cursor/libxcb-cursor0_0.1.4-1build1_${ARCH}.deb"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o libxcb-cursor0.deb "$fallback"
    return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -q -O libxcb-cursor0.deb "$fallback"
    return 0
  fi
  return 1
}

if ! fetch_deb; then
  echo "    libxcb-cursor: could not download; run 'sudo apt install libxcb-cursor0'" >&2
  exit 1
fi

DEB=$(ls libxcb-cursor0*.deb 2>/dev/null | head -1)
dpkg-deb -x "$DEB" extract
cp -a extract/usr/lib/*/libxcb-cursor.so.0* "$DEST/"
cd "$APP_DIR"
rm -rf "$APP_DIR/vendor/tmp"
echo "    libxcb-cursor: vendored to $DEST"
