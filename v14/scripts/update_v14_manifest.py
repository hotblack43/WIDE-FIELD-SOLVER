#!/usr/bin/env python3
"""Deterministically refresh only the independent v14 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v14"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Fork the complete v13 runtime into an independent v14 development package.",
    "Predict the Moon topocentrically from each planet-date candidate and the image-derived zenith without site or time metadata.",
    "Classify possible Moons by resolved angular diameter, rejecting saturated points smaller than 0.5 degrees.",
    "Use image-level Moon presence or absence to reject incompatible retained planet-date candidates.",
    "Exclude lunar-contradicted multi-body dates before expensive joint camera and epoch profiling while retaining their audit records.",
    "Keep lunar evidence outside the Barghini point-source fit and prevent it from establishing a Moon-only epoch.",
    "Export machine-readable lunar constraint results without an all-candidate image overlay.",
    "Process MMTO nights in LIFO order, one newest-incomplete night per routine run, using v14 receipts to avoid repeats while working backward.",
]


def repository_v14_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v14"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v14" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v14: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v14 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v14: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v13-runtime.json").read_text())
    return {
        "version": "0.14.0",
        "based_on_version": "0.13.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v13-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v14_files()
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
