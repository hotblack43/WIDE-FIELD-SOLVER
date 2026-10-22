#!/usr/bin/env python3
"""Record the final v21 runtime before independent v22 development."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
V21_ROOT_FILES = (
    "calibrate_mmto_extinction_v21.sh",
    "go21.sh",
    "go_v0.21.0.sh",
    "go_mmto_photometry_v21.sh",
    "plot_mmto_variable_stars_v21.sh",
    "scripts/calibrate_nightly_extinction_v21.py",
    "scripts/map_mmto_sidereal_transmission_v21.py",
    "scripts/run_mmto_photometry_pipeline_v21.py",
    "scripts/validate_mmto_site_time_v21.py",
)


def _tracked_package_files(root: Path, version: str) -> tuple[str, ...]:
    package = f"v{version}"
    completed = subprocess.run(
        ["git", "ls-files", package],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    names: list[str] = []
    for raw in completed.stdout.splitlines():
        path = PurePosixPath(raw)
        if not path.parts or path.parts[0] != package or ".." in path.parts:
            raise ValueError(f"runtime path is outside {package}: {raw}")
        if raw != f"{package}/SOURCE_MANIFEST.json":
            names.append(raw)
    return tuple(sorted(names))


def snapshot_runtime(
    root: Path,
    version: str,
    root_files: Iterable[str],
) -> dict[str, object]:
    root = root.resolve(strict=True)
    names = set(_tracked_package_files(root, version))
    names.update(str(PurePosixPath(name)) for name in root_files)
    hashes: dict[str, str] = {}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "v21-runtime.json",
    )
    args = parser.parse_args(argv)
    payload = snapshot_runtime(ROOT, "21", V21_ROOT_FILES)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
