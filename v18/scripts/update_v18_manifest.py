#!/usr/bin/env python3
"""Deterministically refresh only the independent v18 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v18"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Continue MMTO development from the complete frozen v16 runtime while leaving v17 independent.",
    "Scan qualifying MMTO observations from 2026-06-30 and select at most the two newest analysis-incomplete nights per invocation.",
    "Download and analyse only the selected nights, using successful v16 or v18 receipts as completion evidence.",
]


def repository_v18_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v18"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v18" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v18: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v18 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v18: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v16-runtime.json").read_text())
    return {
        "version": "0.18.0",
        "based_on_version": "0.16.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v16-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v18_files()
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
