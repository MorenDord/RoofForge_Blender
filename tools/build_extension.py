#!/usr/bin/env python3
"""Build a clean Blender Extension ZIP, optionally bundling native platform wheels."""
from __future__ import annotations

import argparse
import hashlib
import re
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = ("addon", "core")
EXTRA_FILES = ("INSTALL_TEST_RU.md",)
# Experimental mixed-height concave envelope code remains source/test-only.
EXCLUDED_PACKAGE_PATHS = {"core/intersection_envelope.py"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\\+[0-9A-Za-z.-]+)?$")
NATIVE_PLATFORMS = {
    "linux-x64",
    "windows-x64",
    "macos-x64",
    "macos-arm64",
}


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
    if "wheels" in data or "platforms" in data:
        raise SystemExit(
            "Source manifest must not hard-code generated wheel paths or platform tags; "
            "the build script writes them from the verified wheel set."
        )
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


def wheel_platform(filename: str) -> str:
    """Map a stable-ABI wheel filename to one supported Blender platform."""
    if not filename.endswith(".whl"):
        raise SystemExit(f"Not a wheel file: {filename}")
    parts = filename[:-4].split("-")
    if len(parts) != 5 or parts[0].lower() != "roof_forge_native":
        raise SystemExit(f"Unexpected native wheel filename: {filename}")
    if parts[2:4] != ["cp310", "abi3"]:
        raise SystemExit(
            f"Native wheel must target the CPython 3.10+ stable ABI (cp310-abi3): {filename}"
        )

    platform_tag = parts[4]
    if platform_tag == "win_amd64":
        return "windows-x64"
    if platform_tag.startswith("manylinux_2_28_x86_64"):
        return "linux-x64"
    if platform_tag.startswith("macosx_") and platform_tag.endswith("_x86_64"):
        return "macos-x64"
    if platform_tag.startswith("macosx_") and platform_tag.endswith("_arm64"):
        return "macos-arm64"
    raise SystemExit(f"Unsupported native wheel platform tag: {platform_tag}")


def collect_native_wheels(wheels_dir: Path | None, required: bool) -> list[tuple[Path, str]]:
    if wheels_dir is None:
        if required:
            raise SystemExit("--require-native-wheels needs --native-wheels-dir.")
        return []
    if not wheels_dir.is_dir():
        raise SystemExit(f"Native wheel directory does not exist: {wheels_dir}")

    wheel_paths = sorted(wheels_dir.glob("*.whl"))
    if not wheel_paths:
        raise SystemExit(f"No native wheels found in {wheels_dir}")

    result: list[tuple[Path, str]] = []
    found_platforms: set[str] = set()
    for path in wheel_paths:
        platform = wheel_platform(path.name)
        if platform in found_platforms:
            raise SystemExit(f"More than one native wheel found for {platform}.")
        with zipfile.ZipFile(path, "r") as wheel_archive:
            members = wheel_archive.namelist()
            bad_member = wheel_archive.testzip()
            if bad_member:
                raise SystemExit(f"Corrupt native wheel {path.name}: {bad_member}")
            suffixes = (".pyd",) if platform == "windows-x64" else (".so",)
            has_extension = any(
                PurePosixPath(member).name.startswith("roof_forge_native.")
                and PurePosixPath(member).name.endswith(suffixes)
                for member in members
            )
            if not has_extension:
                raise SystemExit(
                    f"{path.name} does not contain the roof_forge_native binary module."
                )
        found_platforms.add(platform)
        result.append((path, platform))

    if required and found_platforms != NATIVE_PLATFORMS:
        missing = sorted(NATIVE_PLATFORMS - found_platforms)
        extra = sorted(found_platforms - NATIVE_PLATFORMS)
        raise SystemExit(
            f"Native wheel platform matrix is incomplete. Missing={missing}, extra={extra}"
        )
    return result


def render_packaged_manifest(source_text: str, wheels: list[tuple[Path, str]]) -> str:
    if not wheels:
        return source_text
    if re.search(r"^\s*(?:platforms|wheels)\s*=", source_text, flags=re.MULTILINE):
        raise SystemExit("Source manifest already contains platforms or wheels entries.")

    platform_values = ", ".join(f'"{platform}"' for platform in sorted(NATIVE_PLATFORMS))
    wheel_values = ",\n".join(
        f'    "./wheels/{path.name}"' for path, _ in wheels
    )
    generated = (
        f"platforms = [{platform_values}]\n"
        "wheels = [\n"
        f"{wheel_values}\n"
        "]\n"
    )
    marker = 'type = "add-on"\n'
    if source_text.count(marker) != 1:
        raise SystemExit("Unable to locate the unique type = \"add-on\" manifest field.")
    return source_text.replace(marker, marker + generated, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--native-wheels-dir", type=Path)
    parser.add_argument("--require-native-wheels", action="store_true")
    args = parser.parse_args()

    manifest = read_manifest()
    files = collect_package_files()
    wheels = collect_native_wheels(args.native_wheels_dir, args.require_native_wheels)
    manifest_text = render_packaged_manifest(
        (ROOT / "blender_manifest.toml").read_text(encoding="utf-8"),
        wheels,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    package_path = args.output_dir / f"{manifest['id']}-{manifest['version']}.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            if relative == "blender_manifest.toml":
                archive.writestr(relative, manifest_text)
            else:
                archive.write(path, relative)
        for wheel_path, _ in wheels:
            # Wheels are already ZIP archives; avoid spending CPU recompressing
            # their binary payloads inside the outer extension archive.
            archive.writestr(
                f"wheels/{wheel_path.name}",
                wheel_path.read_bytes(),
                compress_type=zipfile.ZIP_STORED,
            )

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
        packaged_manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        expected_wheels = [f"./wheels/{path.name}" for path, _ in wheels]
        if packaged_manifest.get("wheels", []) != expected_wheels:
            raise SystemExit("Packaged manifest wheel list does not match the bundled wheel files.")
        if wheels and set(packaged_manifest.get("platforms", [])) != NATIVE_PLATFORMS:
            raise SystemExit("Packaged manifest platform list does not match the native wheel matrix.")
        for wheel_ref in expected_wheels:
            member = wheel_ref.removeprefix("./")
            if member not in names:
                raise SystemExit(f"Manifest wheel is missing from the ZIP: {wheel_ref}")
        bad_member = archive.testzip()
        if bad_member:
            raise SystemExit(f"Corrupt ZIP member: {bad_member}")
        if packaged_manifest["id"] != manifest["id"] or packaged_manifest["version"] != manifest["version"]:
            raise SystemExit("Packaged manifest does not match the source manifest.")

    digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
    checksum_path = package_path.with_suffix(package_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {package_path.name}\n", encoding="utf-8")
    print(f"Built {package_path}")
    print(f"Files: {len(files) + len(wheels)}")
    if wheels:
        for wheel_path, platform in wheels:
            print(f"Native wheel [{platform}]: {wheel_path.name}")
    else:
        print("Native Rust core: not bundled; Python fallback will be used.")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
