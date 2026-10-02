#!/usr/bin/env bash
# Run Desktop Buddy straight from the source tree (development launcher).
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$APP_DIR/vendor/syslibs" ]; then
  export LD_LIBRARY_PATH="$APP_DIR/vendor/syslibs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
unset PYTHONPATH
exec "$APP_DIR/.venv/bin/python" -m desktop_buddy "$@"
