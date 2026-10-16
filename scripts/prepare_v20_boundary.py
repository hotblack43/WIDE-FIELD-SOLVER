#!/usr/bin/env python3
"""Record the exact v19 runtime bytes frozen at the v20 boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "v19-runtime.json"
ROOT_FILES = (
    "go19.sh",
    "go_v0.19.0.sh",
    "go_mmto_photometry_v19.sh",
    "plot_mmto_variable_stars_v19.sh",
    "scripts/run_mmto_photometry_pipeline_v19.py",
)


def tracked_v19_paths() -> list[str]:
    names = subprocess.run(
        ["git", "ls-files", "v19"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return sorted((*ROOT_FILES, *names))


def build_snapshot() -> dict[str, object]:
    paths = tracked_v19_paths()
    return {
        "version": "0.19.0",
        "snapshot_kind": "v19-runtime-at-v20-boundary",
        "preserved_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in paths
        },
    }


def main() -> int:
    TARGET.write_text(
        json.dumps(build_snapshot(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
