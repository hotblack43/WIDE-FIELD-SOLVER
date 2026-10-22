#!/usr/bin/env python3
"""Record the final v22 runtime before independent v23 development."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
V22_ROOT_FILES = (
    "calibrate_mmto_extinction_v22.sh",
    "go22.sh",
    "go_v0.22.0.sh",
    "go_mmto_photometry_v22.sh",
    "plot_mmto_variable_stars_v22.sh",
    "run_v22_photometry_benchmark.sh",
    "scripts/calibrate_nightly_extinction_v22.py",
    "scripts/map_mmto_sidereal_transmission_v22.py",
    "scripts/run_mmto_photometry_pipeline_v22.py",
    "scripts/run_v22_photometry_benchmark.py",
    "scripts/validate_mmto_site_time_v22.py",
)


def _tracked_package_files(root: Path, version: str) -> tuple[str, ...]:
    package = f"v{version}"
    completed = subprocess.run(
        ["git", "ls-files", package], cwd=root, check=True,
        capture_output=True, text=True)
    return tuple(sorted(
        raw for raw in completed.stdout.splitlines()
        if raw != f"{package}/SOURCE_MANIFEST.json"
        and PurePosixPath(raw).parts[0] == package
        and ".." not in PurePosixPath(raw).parts
    ))


def snapshot_runtime(root: Path, version: str, root_files: Iterable[str]):
    root = root.resolve(strict=True)
    names = set(_tracked_package_files(root, version))
    names.update(str(PurePosixPath(name)) for name in root_files)
    hashes = {}
    for name in sorted(names):
        source = root / name
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"runtime source is not an owned file: {name}")
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "version": f"0.{version}.0",
        "snapshot_kind": f"v{version}-runtime-at-v{int(version) + 1}-boundary",
        "sha256": hashes,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/v22-runtime.json")
    args = parser.parse_args(argv)
    args.output.write_text(
        json.dumps(snapshot_runtime(ROOT, "22", V22_ROOT_FILES),
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
