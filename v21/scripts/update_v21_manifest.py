#!/usr/bin/env python3
"""Deterministically refresh only the independent v21 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v21"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Fork the complete frozen v20 runtime into an independent v21 development package.",
    "Reprocess verified local MMTO FITS files under v21 before downloading selected archive gaps.",
    "Use validated FITS-header exposure midpoints and known MMTO site coordinates only for separate post-fit products.",
    "Retain the blind planet epoch search as a separately inspectable secondary result.",
    "Add per-exposure grey-transparency terms and same-sidereal-time differential transmission maps.",
    "Prioritize current and intervening recent MMTO nights before filling the invocation cap from historical backlog.",
    "Retry only transient JPL Horizons failures in v21 planet photometry while preserving failed attempts and retaining correct output provenance.",
]


def repository_v21_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v21"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v21" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v21: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v21 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v21: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v20-runtime.json").read_text())
    return {
        "version": "0.21.0",
        "based_on_version": "0.20.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v20-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v21_files()
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
