# Platform backends

Desktop Buddy routes operating-system services through `PlatformBackend`. The
animation, reminder and renderer modules do not import native APIs or Linux
paths.

The backend contract covers:

- configuration, state and cache paths through Qt `QStandardPaths`;
- login autostart;
- battery state;
- active-window information, fullscreen state and window classification;
- always-on-top, click-through and all-workspace capability reporting;
- workspace behavior for the buddy window;
- native process DPI setup, idle time, network state and credential storage;
- Qt Multimedia audio playback;
- session diagnostics and a user/session-scoped local IPC name.

`platforms/linux.py` implements the current supported Linux/X11 behavior. On
Wayland, restricted window capabilities are reported as unavailable. The tray
and preferences dialog disable those controls and display the backend's reason
instead of accepting settings that cannot take effect.

`platforms/windows.py` implements Win32 foreground-window geometry and
fullscreen detection, per-monitor DPI awareness, topmost/click-through native
styles, power and idle state, network status, Credential Manager storage, and a
Startup-folder launcher. Windows virtual-desktop pinning and native media
controls remain explicitly unavailable.

Focus completion suppression uses the same active-window capability. When the backend cannot inspect fullscreen state, the preference is disabled and focus timing/history continue without that optional suppression.

The generic backend is intentionally conservative. It supplies portable paths,
audio and IPC identity, while reporting native integrations unavailable until a
native backend implements them.

Backend behavior is tested independently in `tests/test_platform_backend.py`
and `tests/test_windows_backend.py`.
