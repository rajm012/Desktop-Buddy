# PyInstaller one-directory Windows build. Run only on Windows.

from pathlib import Path

root = Path(SPECPATH)
manifest = root / "packaging" / "windows" / "app.manifest"

analysis = Analysis(
    [str(root / "packaging" / "windows" / "entrypoint.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (
            str(root / "desktop_buddy" / "assets"),
            "desktop_buddy/assets",
        )
    ],
    hiddenimports=["PyQt6.QtMultimedia"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DesktopBuddy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest=str(manifest),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DesktopBuddy",
)
