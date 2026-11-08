"""Record local build provenance and validate assets before publishing."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desktop_buddy import __version__  # noqa: E402


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def asset_names() -> list[str]:
    return [
        f"desktop-buddy-{__version__}-linux-x86_64.tar.gz",
        f"desktop_buddy-{__version__}.tar.gz",
        f"desktop_buddy-{__version__}-py3-none-any.whl",
        "BUILD_INFO.json",
    ]


def record(bundle: Path) -> None:
    import tomllib

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    if metadata["project"]["version"] != __version__:
        raise ValueError("Package and application versions differ.")
    packages = {
        dist.metadata["Name"]: dist.version
        for dist in importlib.metadata.distributions()
    }
    info = {
        "version": __version__,
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": "linux-x86_64",
        "glibc": platform.libc_ver()[1],
        "packages": dict(sorted(packages.items())),
    }
    (bundle / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n")
    licenses = bundle / "licenses"
    licenses.mkdir(exist_ok=True)
    for name in ("PyQt6", "PyQt6-Qt6", "PyQt6_sip", "pyinstaller"):
        dist = importlib.metadata.distribution(name)
        for file in dist.files or ():
            if "license" in str(file).lower() and dist.locate_file(file).is_file():
                target = licenses / name / str(file)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(file), target)


def validate(release: Path) -> None:
    info = json.loads((release / "BUILD_INFO.json").read_text())
    if info["version"] != __version__ or info["platform"] != "linux-x86_64":
        raise ValueError("The release version or platform does not match.")
    if info["dirty"] or git("status", "--porcelain"):
        raise ValueError("Commit all source changes, then rebuild before publishing.")
    if info["commit"] != git("rev-parse", "HEAD"):
        raise ValueError("Release assets are from another commit; rebuild first.")
    sums = {}
    for line in (release / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    if set(sums) != set(asset_names()):
        raise ValueError("Checksums must cover exactly the current Linux assets.")
    for name in asset_names():
        path = release / name
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != sums[name]:
            raise ValueError(f"Checksum mismatch: {name}")
    print(f"Verified v{__version__} at {info['commit']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("record", "validate"))
    parser.add_argument("release", type=Path)
    parser.add_argument("bundle", type=Path, nargs="?")
    args = parser.parse_args()
    if args.command == "record":
        if args.bundle is None:
            parser.error("record requires the bundle path")
        record(args.bundle)
    else:
        validate(args.release)


if __name__ == "__main__":
    main()
