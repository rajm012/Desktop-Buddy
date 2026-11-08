# Linux one-directory build; Python and Qt are included in the archive.

from pathlib import Path

root = Path(SPECPATH)
analysis = Analysis(
    [str(root / "packaging/linux/entrypoint.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "desktop_buddy/assets"), "desktop_buddy/assets")],
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
    name="desktop-buddy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="desktop-buddy",
)
