"""Static checks for the standalone Windows packaging and release workflow."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from desktop_buddy import __version__

ROOT = Path(__file__).resolve().parent.parent


class WindowsPackagingTests(unittest.TestCase):
    def test_manifest_is_per_monitor_v2_and_non_elevated(self) -> None:
        path = ROOT / "packaging/windows/app.manifest"
        ET.parse(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("PerMonitorV2", text)
        self.assertIn('level="asInvoker"', text)
        self.assertIn("longPathAware", text)

    def test_pyinstaller_build_is_windowed_and_includes_manifest(self) -> None:
        text = (ROOT / "desktop-buddy-windows.spec").read_text(encoding="utf-8")
        self.assertIn('name="DesktopBuddy"', text)
        self.assertIn("console=False", text)
        self.assertIn("manifest=str(manifest)", text)
        self.assertIn("desktop_buddy/assets", text)

    def test_installer_version_and_data_choice_are_explicit(self) -> None:
        text = (ROOT / "packaging/windows/DesktopBuddy.iss").read_text(encoding="utf-8")
        self.assertIn(f'#define MyAppVersion "{__version__}"', text)
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn("SuppressibleMsgBox", text)
        self.assertIn("Remove Desktop Buddy settings", text)
        self.assertIn("DelTree", text)

    def test_windows_build_fails_closed_and_verifies_signatures(self) -> None:
        text = (ROOT / "scripts/build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Assert-LastExitCode", text)
        self.assertIn("Get-AuthenticodeSignature", text)
        self.assertIn('Signature.Status -ne "Valid"', text)
        self.assertIn("without producing an installer", text)

    def test_windows_validation_script_covers_release_matrix(self) -> None:
        text = (ROOT / "scripts/validate_windows_release.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Get-VerifiedSignature", text)
        self.assertIn('ArgumentList "--version"', text)
        self.assertIn("Win32_OperatingSystem", text)
        self.assertIn("PerMonitorSettings", text)
        for requirement in (
            "100% scaling",
            "200% scaling",
            "Mixed-DPI monitors",
            "negative desktop origin",
            "Exclusive-fullscreen",
            "Second launch",
            "Preserve-data uninstall",
            "Purge-data uninstall",
            "SmartScreen",
            "Windows 10 and Windows 11",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, text)
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("recursive-include scripts *.ps1", manifest)

    def test_windows_ci_builds_and_uploads_standalone_artifacts(self) -> None:
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("windows-latest", text)
        self.assertIn("desktop-buddy-windows.spec", text)
        self.assertIn("Inno Setup 6", text)
        self.assertIn("desktop-buddy-windows-unsigned", text)

    def test_signed_release_workflow_protects_and_verifies_credentials(self) -> None:
        text = (ROOT / ".github/workflows/windows-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch", text)
        self.assertIn("environment: windows-release", text)
        self.assertIn("secrets.WINDOWS_SIGNING_CERT_BASE64", text)
        self.assertIn("secrets.WINDOWS_SIGNING_PASSWORD", text)
        self.assertIn("-Installer -Sign", text)
        self.assertIn("Get-AuthenticodeSignature", text)
        self.assertIn("signtool", text.lower())
        self.assertIn("validate_windows_release.ps1", text)
        self.assertIn("windows-ci-preflight.md", text)
        self.assertIn("if: always()", text)
        self.assertIn("Remove-Item -LiteralPath", text)
        self.assertIn("desktop-buddy-windows-signed", text)


if __name__ == "__main__":
    unittest.main()
