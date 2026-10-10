#!/usr/bin/env python3
"""Freeze the complete v15 runtime boundary before v16 development."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "v15" / "SOURCE_MANIFEST.json"
TARGET = ROOT / "docs" / "v15-runtime.json"
ROOT_RUNTIME = (
    "go15.sh",
    "go_v0.15.0.sh",
    "go_mmto_photometry_v15.sh",
    "scripts/run_mmto_photometry_pipeline_v15.py",
    "plot_mmto_lightcurves.sh",
    "calibrate_mmto_extinction.sh",
    "plot_ALL_planets.sh",
    "scripts/plot_star_lightcurves.py",
    "scripts/calibrate_nightly_extinction.py",
    "scripts/nightly_extinction.py",
    "scripts/plot_planet_photometry.py",
    "scripts/plot_planet_colours.py",
    "scripts/plot_brightness_matched_planet_extinction.py",
    "pyproject.toml",
    "uv.lock",
    "sources.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def root_runtime_dependencies() -> tuple[str, ...]:
    """Return the explicit v15 MMTO stage closure outside the v15 package."""
    tracked_package = subprocess.run(
        ["git", "ls-files", "allsky_download"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return tuple(dict.fromkeys((*ROOT_RUNTIME, *tracked_package)))


def main() -> int:
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    hashes = {f"v15/{name}": value for name, value in manifest["sha256"].items()}
    hashes["v15/SOURCE_MANIFEST.json"] = digest(SOURCE)
    for relative in root_runtime_dependencies():
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        hashes[relative] = digest(path)
    record = {
        "version": "0.15.0",
        "snapshot_kind": (
            "early celestial Sun/Moon gating v0.15.0 boundary before "
            "planet-only empirical extinction v16"
        ),
        "sha256": dict(sorted(hashes.items())),
    }
    TARGET.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
