# Windows build and release guide

The native Windows backend and packaging pipeline are implemented, but a public
Windows release is not complete until the signed installer passes the physical
Windows 10/11 validation matrix below.

## Implemented native behavior

- foreground-window title, class, physical geometry, hidden/minimized state and
  monitor-relative fullscreen detection through Win32;
- always-on-top and click-through extended window styles without activation;
- battery percentage/power source, last-input idle duration and local network
  connectivity state;
- Windows Credential Manager for integration secrets;
- per-monitor-v2 DPI awareness before Qt creates the application;
- Startup-folder autostart through a hidden `Desktop Buddy.vbs` launcher;
- exclusive-fullscreen adaptation: native topmost is lowered and perching is
  disabled while another application covers its monitor;
- user/session-scoped Qt local IPC, tray controls and multi-monitor logical
  placement using the shared Qt window layer.

Windows virtual-desktop pinning and System Media Transport Controls are not yet
implemented. Preferences reports both capabilities as unavailable.

## Development build

Run in PowerShell on 64-bit Windows 10 or Windows 11:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,windows]"
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -v
.\scripts\build_windows.ps1
```

The standalone application is written to `dist\DesktopBuddy`. It includes the
Python runtime, PyQt6, Qt plugins and application modules; the target machine
does not need Python installed.

Build the installer with:

```powershell
.\scripts\build_windows.ps1 -Installer
```

Inno Setup 6 must be installed in its standard location. The installer is
per-user, requires no administrator rights, and asks during uninstall whether
Desktop Buddy settings, history, logs, plugins and cache should be preserved or
removed.

## Production signing

Never place signing credentials in the repository. Set these variables in the
secured release environment:

```powershell
$env:WINDOWS_SIGNING_CERT = "C:\secure\desktop-buddy.pfx"
$env:WINDOWS_SIGNING_PASSWORD = "<secret>"
$env:SIGNTOOL_PATH = "C:\Program Files (x86)\Windows Kits\10\bin\<sdk>\x64\signtool.exe"
.\scripts\build_windows.ps1 -Installer -Sign
```

The script signs the application executable before installer creation and then
signs the final installer, using SHA-256 and a trusted timestamp. Release
automation must inject the certificate/password as protected secrets and delete
temporary certificate material after signing.

## Release validation matrix

Do not check the remaining Phase 7 roadmap gates until these tests pass.

| Area | Required coverage |
| --- | --- |
| Operating systems | Current supported Windows 10 and Windows 11 builds |
| DPI | 100%, 125%, 150%, 175%, 200%, and a mixed-DPI two-monitor setup |
| Displays | Primary/secondary placement, negative monitor origins, taskbar on each edge, monitor disconnect/reconnect |
| Rendering | Transparent background, no black rectangle, correct scale, no focus/taskbar entry |
| Window behavior | Topmost, click-through recovery, dragging, throwing, perching, fullscreen lowering |
| Desktop services | Tray menu, notifications, audio, Startup-folder autostart, battery state |
| IPC | Second launch controls the existing process; concurrent duplicate is not created |
| Lifecycle | Clean install, upgrade from prior installer, preserve-data uninstall, purge-data uninstall |
| Security | Signed executable/installer validate with `Get-AuthenticodeSignature`; SmartScreen reputation reviewed |

Record the OS build, hardware/VM, display scaling, test result, and any workaround
in the release notes. CI's offscreen tests and unsigned artifact prove packaging
repeatability, not real compositor, tray, notification, or DPI behavior.
