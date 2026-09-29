#!/usr/bin/env python3
"""Deterministically refresh only the independent v13 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v13"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Fork the complete v12 runtime into an independent v13 development package.",
    "Jointly fit atmospheric refraction and the Barghini camera with radial soft-L1 least squares.",
    "Refit the coupled model during epoch trials and propagate selected corrections to saved coordinates and FITS export.",
    "Select refraction with deterministic angular-block robust validation and exact-zero fallback.",
    "Replay exact saved associations across MMTO, APICAM, Subaru and historical full-fisheye families.",
]


def repository_v13_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v13"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v13" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v13: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v13 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v13: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v12-runtime.json").read_text())
    return {
        "version": "0.13.0",
        "based_on_version": "0.12.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v12-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v13_files()
        },
    }


def main() -> int:
    MANIFEST.write_text(
        json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
