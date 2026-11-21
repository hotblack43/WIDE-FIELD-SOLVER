#!/usr/bin/env python3
"""Deterministically refresh only the independent v26 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v26"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Retain direct fluxes, accepted saturated-wing model fluxes, and clipped-aperture lower bounds as distinct planet-brightness evidence.",
    "Order otherwise comparable blind planet aliases with robust, uncertainty-weighted photometric costs without altering astrometry or claiming a unique date from photometry alone.",
    "Propagate accepted saturated PSF-wing estimates into cumulative MMTO planet photometry with explicit provenance and a conservative 1.8 mag uncertainty floor.",
]


def repository_v26_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v26"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v26" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v26: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v26 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v26: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v25-runtime.json").read_text())
    return {
        "version": "0.26.0",
        "based_on_version": "0.25.1",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v25-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v26_files()
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
