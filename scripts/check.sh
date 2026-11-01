#!/usr/bin/env bash
set -euo pipefail

python -m ruff format --check desktop_buddy tests tools
python -m ruff check desktop_buddy tests tools
QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  python -m unittest discover -s tests -v
python -m build
