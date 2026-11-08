"""Standalone Linux entry point, also usable for CLI commands."""

from desktop_buddy.app import main

if __name__ == "__main__":
    raise SystemExit(main())
