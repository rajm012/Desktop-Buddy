# Bundled dependencies

Desktop Buddy's own source is licensed under MIT (see LICENSE). The standalone
Linux archive also includes dependencies with their own licenses:

- Python: PSF license; https://www.python.org/downloads/source/
- PyQt6: GPL v3; https://www.riverbankcomputing.com/software/pyqt/download
- Qt 6: LGPL v3/GPL v3 and component licenses;
  https://download.qt.io/archive/qt/
- PyInstaller bootloader: GPL with the bootloader exception permitting bundled
  applications; https://pyinstaller.org/en/stable/license.html

Exact versions are recorded in BUILD_INFO.json and requirements-release.txt.
PyQt6 and Qt license files are included beneath `licenses/` in the archive.
The application source is available from the corresponding GitHub release tag.
