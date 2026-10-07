#!/usr/bin/env python3
"""Deterministically refresh only the independent v15 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v15"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Fork the complete v14 runtime into an independent v15 development package.",
    "Combine the Sun and Moon above/below-horizon tests after cheap interpolated planet proposals and before exact planet refinement.",
    "Require a Moon-like image object to be at least 0.5 degrees across, at least 5 degrees above the derived horizon, and saturated or peak SNR at least 25.",
    "Use a plus/minus 5-degree lunar horizon guard; phase and positional coincidence do not enter the early gate.",
    "Keep celestial evidence outside the Barghini fit and prevent it from establishing a Sun- or Moon-only epoch.",
    "Record early gate rejection and exact-call timing in the planet-search performance audit.",
    "Process MMTO nights in LIFO order, one newest-incomplete night per routine run, using v15 receipts to avoid repeats while working backward.",
]


def repository_v15_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v15"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v15" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v15: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v15 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v15: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v14-runtime.json").read_text())
    return {
        "version": "0.15.0",
        "based_on_version": "0.14.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v14-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v15_files()
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
