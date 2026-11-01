# Performance baseline

Phase 0 baseline recorded on 2026-11-01 for Desktop Buddy 1.3 on an Intel
i5-13500H laptop, Linux/X11, Qt 6.11, a 2.5× HiDPI scale and a 165 Hz display.
CPU percentages are percentages of one logical core. Results are approximate
and intended to catch regressions, not compare different computers.

| Scenario | Result | Measurement notes |
| --- | ---: | --- |
| Startup to first paint | 174 ms | Fresh Python process, Qt offscreen backend, default Bolt window |
| Idle/sleeping | ~4% CPU | Adaptive idle frame rate, visible window |
| Active walk/dance/perch | ~7% CPU | Normal 30 fps configuration |
| Paused or hidden | ~1% CPU | Event loop and reminder scheduler still running |
| Resident memory | ~85 MB | Stable across the three runtime states |

The startup measurement includes Python imports, `QApplication`, configuration
construction, `BuddyWindow.show()` and the first processed Qt event. The CPU and
memory figures were observed on the real X11 desktop over steady-state samples.
The reminder scheduler wakes every 20 seconds and did not measurably change idle
CPU use.

Future measurements should record the date, commit, Qt/PyQt versions, display
backend, scale factor, configured FPS and sampling duration. A regression should
be investigated when the same machine and method show a sustained increase of
more than 20%.
