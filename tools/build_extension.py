#!/usr/bin/env python3
"""Build a clean Blender Extension ZIP from the current RoofForge sources."""
from __future__ import annotations

import argparse
import hashlib
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = ("addon", "core")
EXTRA_FILES = ("INSTALL_TEST_RU.md",)
# Experimental mixed-height concave envelope code remains source/test-only.
EXCLUDED_PACKAGE_PATHS = {"core/intersection_envelope.py"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def read_manifest() -> dict:
    manifest_path = ROOT / "blender_manifest.toml"
    data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "id", "version", "name", "tagline",
        "maintainer", "type", "blender_version_min", "license",
    }
    missing = required - data.keys()
    if missing:
        raise SystemExit(f"Manifest is missing required keys: {sorted(missing)}")
    if data["type"] != "add-on":
        raise SystemExit("RoofForge package must have type = 'add-on'.")
    if not SEMVER.fullmatch(data["version"]):
        raise SystemExit(f"Invalid semantic version: {data['version']!r}")
    if len(data["tagline"]) > 64 or data["tagline"].endswith((".", "!", "?")):
        raise SystemExit("Manifest tagline must be <=64 characters and have no trailing punctuation.")
    if tuple(int(part) for part in data["blender_version_min"].split(".")) < (5, 0, 0):
        raise SystemExit("This test build requires Blender 5.0.0 or newer.")
    return data


def collect_package_files() -> list[Path]:
    required = ("blender_manifest.toml", "__init__.py", *EXTRA_FILES)
    files = [ROOT / item for item in required]
    for directory in PACKAGE_DIRS:
        package_root = ROOT / directory
        if not (package_root / "__init__.py").is_file():
            raise SystemExit(f"Missing Python package initializer: {directory}/__init__.py")
        for path in package_root.rglob("*.py"):
            relative_path = path.relative_to(ROOT).as_posix()
            if (
                "__pycache__" not in path.parts
                and path.is_file()
                and relative_path not in EXCLUDED_PACKAGE_PATHS
            ):
                files.append(path)
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing package files: {missing}")
    return sorted(set(files), key=lambda path: path.relative_to(ROOT).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    manifest = read_manifest()
    files = collect_package_files()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    package_path = args.output_dir / f"{manifest['id']}-{manifest['version']}.zip"

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())

    with zipfile.ZipFile(package_path, "r") as archive:
        names = set(archive.namelist())
        required_names = {"blender_manifest.toml", "__init__.py", "INSTALL_TEST_RU.md"}
        missing = required_names - names
        if missing:
            raise SystemExit(f"Package is missing required root files: {sorted(missing)}")
        if any(name.startswith(("tests/", "docs/", "roof_forge_2.8.4/")) for name in names):
            raise SystemExit("Development tests/docs or legacy add-on files leaked into the extension ZIP.")
        leaked_experiments = EXCLUDED_PACKAGE_PATHS & names
        if leaked_experiments:
            raise SystemExit(
                f"Experimental modules leaked into the extension ZIP: {sorted(leaked_experiments)}"
            )
        bad_member = archive.testzip()
        if bad_member:
            raise SystemExit(f"Corrupt ZIP member: {bad_member}")
        packaged_manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        if packaged_manifest["id"] != manifest["id"] or packaged_manifest["version"] != manifest["version"]:
            raise SystemExit("Packaged manifest does not match the source manifest.")

    digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
    checksum_path = package_path.with_suffix(package_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {package_path.name}\n", encoding="utf-8")
    print(f"Built {package_path}")
    print(f"Files: {len(files)}")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
