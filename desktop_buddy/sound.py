"""Tiny generated chimes for reminders (no audio assets required)."""

from __future__ import annotations

import logging
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100

_NOTES: dict[str, tuple[tuple[float, float, float], ...]] = {
    # (frequency Hz, duration s, relative volume)
    "water": ((880.0, 0.11, 0.5), (1174.7, 0.2, 0.45)),
    "meal": ((659.3, 0.11, 0.5), (784.0, 0.11, 0.5), (987.8, 0.24, 0.45)),
    "break": ((523.3, 0.14, 0.45), (659.3, 0.26, 0.4)),
    "winddown": ((440.0, 0.2, 0.4), (349.2, 0.34, 0.35)),
    "default": ((784.0, 0.12, 0.5), (880.0, 0.22, 0.45)),
}

_PLAYERS = ("paplay", "pw-play", "aplay")


def _write_chime(path: Path, notes: tuple[tuple[float, float, float], ...]) -> None:
    frames = bytearray()
    for frequency, duration, volume in notes:
        count = int(SAMPLE_RATE * duration)
        for index in range(count):
            position = index / SAMPLE_RATE
            # gentle attack/decay envelope
            attack = min(1.0, position / 0.012)
            release = min(1.0, (duration - position) / 0.06)
            envelope = max(0.0, min(attack, release))
            value = math.sin(2.0 * math.pi * frequency * position)
            value += 0.18 * math.sin(4.0 * math.pi * frequency * position)
            sample = int(32767 * volume * envelope * value / 1.18)
            frames += struct.pack("<h", max(-32768, min(32767, sample)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


def chime_path(kind: str, base_dir: Path) -> Path:
    notes = _NOTES.get(kind, _NOTES["default"])
    path = base_dir / f"chime-{kind if kind in _NOTES else 'default'}.wav"
    if not path.is_file():
        try:
            _write_chime(path, notes)
        except OSError as exc:  # pragma: no cover - filesystem issues
            log.warning("Could not write chime: %s", exc)
    return path


def play_chime(kind: str, base_dir: Path) -> bool:
    """Play a short chime. Returns True when a player was launched."""
    path = chime_path(kind, base_dir)
    if not path.is_file():
        return False
    for player in _PLAYERS:
        executable = shutil.which(player)
        if not executable:
            continue
        try:
            subprocess.Popen(
                [executable, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue
    return False
