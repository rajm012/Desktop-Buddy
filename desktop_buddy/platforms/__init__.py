"""Platform backend selection."""

from __future__ import annotations

import sys

from .base import GenericPlatformBackend, PlatformBackend

_BACKEND: PlatformBackend | None = None


def get_backend() -> PlatformBackend:
    """Return the process-wide backend for the current operating system."""
    global _BACKEND
    if _BACKEND is None:
        if sys.platform.startswith("linux"):
            from .linux import LinuxBackend

            _BACKEND = LinuxBackend()
        else:
            _BACKEND = GenericPlatformBackend()
    return _BACKEND


def set_backend_for_tests(backend: PlatformBackend | None) -> None:
    """Override backend selection in isolated tests."""
    global _BACKEND
    _BACKEND = backend


__all__ = ["PlatformBackend", "get_backend", "set_backend_for_tests"]
