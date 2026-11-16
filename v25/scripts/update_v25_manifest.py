#!/usr/bin/env python3
"""Deterministically refresh only the independent v25 source manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "v25"
MANIFEST = PACKAGE / "SOURCE_MANIFEST.json"

CHANGES = [
    "Fork the complete frozen v24 runtime into an independent v25 development package.",
    "Add a configuration-driven automatic mask command with fixed held-out and five-fold gates while retaining separate manual proposal, revision, approval, and activation tools.",
    "Add an installation-specific visible-sky mask without changing the generic unmasked numerical path.",
    "Add native-FITS aperture-radius and sky-annulus sweeps on held-out nights.",
    "Retain the v22 aperture unless one global RGB geometry passes validation and final-test gates.",
    "Batch post-fit coordinate validation, use TDB for fitted Julian epochs, and replace individual transmission-map paths in stage and final terminal output with one count-and-directory summary.",
    "Prioritize remote MMTO nights before cached backlog and mark distance-only recent planet measurements explicitly when nightly extinction is unavailable.",
    "Gate MMTO acquisition on fresh public summit humidity below 80 percent, fail open when telemetry is unavailable, and retain per-image audit decisions.",
    "Rebuild every differential-photometry figure from the fresh cumulative database population instead of a fixed legacy run list.",
    "Plot every accumulated planet identity and every finite injected-signal recovery row without display truncation, reporting total recovery counts.",
    "Report each v25 MMTO invocation's downloaded and reused images by observing night before optional photometry stages, and list latest plots with labelled older fallbacks.",
    "Replace chronological variable-star time-series plotting with phase-folded curves using each star's earliest plotted UTC as phase zero.",
    "Run bounded MMTO image solves concurrently and bypass batch-only display-name network waits without changing numerical fitting.",
    "Generate RGB planet photometry in one process so each source FITS is verified and decoded once while preserving separate channel products.",
    "Continue the v25 MMTO backlog from the durable v24 cursor and treat v23 and v24 receipts as completed acquisition progress.",
    "Apply the approved MMTO installation mask in production, accepting the same camera model when a known FITS header generation omits its serial while rejecting a different explicit serial.",
    "Ship self-contained v25 launchers for every configured derived photometry stage and verify that their exact pipeline commands start.",
    "Combine v21, v23, v24, and v25 FITS-header observation sidecars read-only when replaying the cumulative differential-photometry control population.",
    "Generalize visible-sky calibration into sealed proposals, immutable approval, layered registries, checksum assignments, and automatic launcher resolution for supported fixed cameras.",
    "Integrate opt-in assignment with new and bounded historical downloads while preserving verified-but-unassigned originals on validation failure.",
    "Reproduce the MMTO proposal from 3,194 freshly verified originals with whole-date holdout evidence before revealing the approved reference mask.",
    "Record the visually accepted MMTO cold-start baseline and enforce its fixed regression thresholds against recomputed mask metrics.",
]


def repository_v25_files() -> list[tuple[str, Path]]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v25"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: list[tuple[str, Path]] = []
    for name in output:
        posix = PurePosixPath(name)
        if len(posix.parts) < 2 or posix.parts[0] != "v25" or ".." in posix.parts:
            raise ValueError(f"repository path is outside v25: {name}")
        relative = PurePosixPath(*posix.parts[1:]).as_posix()
        if relative == "SOURCE_MANIFEST.json":
            continue
        source = PACKAGE / relative
        if not source.is_file():
            raise FileNotFoundError(f"v25 source is missing: {name}")
        if PACKAGE not in source.resolve().parents:
            raise ValueError(f"repository path resolves outside v25: {name}")
        files.append((relative, source))
    return sorted(files)


def build_manifest() -> dict[str, object]:
    boundary = json.loads((ROOT / "docs/v24-runtime.json").read_text())
    return {
        "version": "0.25.0",
        "based_on_version": "0.24.0",
        "based_on_snapshot_kind": boundary["snapshot_kind"],
        "parent_snapshot": "../docs/v24-runtime.json",
        "release_status": "development",
        "changes": CHANGES,
        "sha256": {
            relative: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative, source in repository_v25_files()
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
