#!/usr/bin/env python3
"""Deterministically refresh only the independent v11 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "v11"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Independent v11 package preserves current v10 bytes without changing or committing another window work.",
    "Global planet search never bounded by observation metadata; supplied timestamps are validation only.",
    "Refit common Barghini camera and epoch using stellar proper motions and at least two distinct moving bodies.",
    "Soft ephemeris relative brightness after native-channel zero-point profiling; saturation neutral.",
    "Conservative alias, membership, visibility, solar, and causal-interval checks retain stellar fallback.",
    "Joint authoritative product view shared by PDF/FITS/identified photometry; recoverable staged adoption.",
    "Report actual-position crops, joint profile, finite boundary-truncated interval and metadata discrepancy.",
    "Correct inherited double exposure normalization: raw counts enter counts/exposure magnitude helper once.",
    "Lossless physical product and CSV-body deduplication behind legacy-compatible SQLite views; verified ZIP archives for adopted intermediate snapshots; no numerical changes.",
    "Permitted native-colour MMTO FITS demonstration with offline catalogue use and conservative regression limits.",
    "Public BSD 3-Clause release packaging with explicit software, observation, and photograph rights boundaries.",
]


def tracked_v11_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "v11"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for tracked in output:
        posix = PurePosixPath(tracked)
        if len(posix.parts) < 2 or posix.parts[0] != "v11" or ".." in posix.parts:
            raise ValueError(f"tracked path is outside v11: {tracked}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"tracked v11 source is missing: {tracked}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"tracked path resolves outside v11: {tracked}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v10-runtime.json").read_text())
    return {
        "version": "0.11.0",
        "based_on_version": "0.10.0",
        "based_on_commit": boundary["base_commit"],
        "parent_snapshot": "../docs/v10-runtime.json",
        "parent_snapshot_section": "working_tree_parent_snapshot",
        "release_status": "released as v0.11.0",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in tracked_v11_files()
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
