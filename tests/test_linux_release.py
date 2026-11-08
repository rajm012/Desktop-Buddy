"""Publishing must reject stale sources and altered local release assets."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import linux_release


class LinuxReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.release = Path(temporary.name)
        self.info = {
            "version": linux_release.__version__,
            "platform": "linux-x86_64",
            "commit": "release-commit",
            "dirty": False,
        }
        for name in linux_release.asset_names():
            (self.release / name).write_bytes(b"release asset")
        self.write_manifest()
        git = patch.object(linux_release, "git", side_effect=self.git_output)
        self.git_mock = git.start()
        self.addCleanup(git.stop)

    @staticmethod
    def git_output(*args: str) -> str:
        return "" if args == ("status", "--porcelain") else "release-commit"

    def write_manifest(self) -> None:
        (self.release / "BUILD_INFO.json").write_text(json.dumps(self.info))
        checksums = []
        for name in linux_release.asset_names():
            digest = hashlib.sha256((self.release / name).read_bytes()).hexdigest()
            checksums.append(f"{digest}  {name}\n")
        (self.release / "SHA256SUMS").write_text("".join(checksums))

    def test_matching_clean_source_and_assets_can_be_published(self) -> None:
        linux_release.validate(self.release)

    def test_modified_asset_cannot_be_published(self) -> None:
        name = linux_release.asset_names()[0]
        (self.release / name).write_bytes(b"changed after building")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            linux_release.validate(self.release)

    def test_checksums_must_cover_every_release_asset(self) -> None:
        sums = self.release / "SHA256SUMS"
        sums.write_text("".join(sums.read_text().splitlines(keepends=True)[:-1]))
        with self.assertRaisesRegex(ValueError, "exactly the current Linux assets"):
            linux_release.validate(self.release)

    def test_build_from_another_commit_cannot_be_published(self) -> None:
        self.info["commit"] = "older-commit"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "another commit"):
            linux_release.validate(self.release)

    def test_dirty_build_cannot_be_published(self) -> None:
        self.info["dirty"] = True
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Commit all source changes"):
            linux_release.validate(self.release)

    def test_changes_after_build_cannot_be_published(self) -> None:
        self.git_mock.side_effect = lambda *args: " M README.md"
        with self.assertRaisesRegex(ValueError, "Commit all source changes"):
            linux_release.validate(self.release)

    def test_wrong_version_or_platform_cannot_be_published(self) -> None:
        for key, value in (("version", "0.0.0"), ("platform", "windows-x86_64")):
            with self.subTest(key=key):
                original = self.info[key]
                self.info[key] = value
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "version or platform"):
                    linux_release.validate(self.release)
                self.info[key] = original
