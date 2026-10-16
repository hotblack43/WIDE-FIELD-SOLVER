#!/usr/bin/env python3
"""Deterministically refresh only the independent v19 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v19"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Fork the complete frozen v16 runtime into an independent v19 development package.",
    "Retain every v16 solver and MMTO photometry product unchanged.",
    "Add nightly flux-averaged extinction-corrected variable-star time series for confirmed VSX stars with configurable period and catalogue-magnitude limits.",
    "Fit independent R/G/B sinusoids with fixed catalogue periods and export brightest-light phase offsets and diagnostics.",
]


def repository_v19_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v19"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v19" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v19: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v19 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v19: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v16-runtime.json").read_text())
    return {
        "version": "0.19.0",
        "based_on_version": "0.16.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v16-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v19_files()
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
