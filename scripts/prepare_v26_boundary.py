#!/usr/bin/env python3
"""Record the final v25 runtime before independent v26 development."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]
V25_ROOT_FILES = (
    "calibrate_mmto_extinction_v25.sh",
    "go25.sh",
    "go_v0.25.0.sh",
    "go_v0.25.1.sh",
    "go_mmto_photometry_v25.sh",
    "go_visible_sky_v25.sh",
    "plot_mmto_variable_stars_v25.sh",
    "quickstart.sh",
    "run_v25_aperture_radius_benchmark.sh",
    "run_v25_photometry_benchmark.sh",
    "scripts/calibrate_nightly_extinction_v25.py",
    "scripts/map_mmto_sidereal_transmission_v25.py",
    "scripts/run_v25_aperture_radius_benchmark.py",
    "scripts/run_mmto_photometry_pipeline_v25.py",
    "scripts/run_v25_photometry_benchmark.py",
    "scripts/validate_mmto_site_time_v25.py",
)


def runtime_files() -> list[str]:
    names = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v25"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    package = [name for name in names if name != "v25/SOURCE_MANIFEST.json"]
    return sorted(set(package) | set(V25_ROOT_FILES))


def main() -> int:
    hashes = {}
    for name in runtime_files():
        posix = PurePosixPath(name)
        if ".." in posix.parts:
            raise ValueError(f"runtime path escapes repository: {name}")
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"runtime source is not an owned file: {name}")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {
        "version": "0.25.1",
        "snapshot_kind": "v25-runtime-at-v26-boundary",
        "sha256": hashes,
    }
    output = ROOT / "docs/v25-runtime.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
