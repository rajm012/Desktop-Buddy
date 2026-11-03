"""PyInstaller entry point with an absolute package import."""

from desktop_buddy.app import main

if __name__ == "__main__":
    raise SystemExit(main())
