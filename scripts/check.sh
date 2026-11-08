#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -d .venv ] && [ -z "${VIRTUAL_ENV:-}" ]; then
  export PATH="$PWD/.venv/bin:$PATH"
fi
python -m ruff format --check desktop_buddy tests tools scripts/linux_release.py packaging/linux/entrypoint.py
python -m ruff check desktop_buddy tests tools scripts/linux_release.py packaging/linux/entrypoint.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  python -m unittest discover -s tests -v
python -m build --outdir "${BUDDY_DIST_DIR:-dist}" "${@}"
