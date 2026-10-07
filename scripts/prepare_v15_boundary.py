#!/usr/bin/env python3
"""Freeze the complete v14 runtime boundary before v15 development."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "v14" / "SOURCE_MANIFEST.json"
TARGET = ROOT / "docs" / "v14-runtime.json"
ROOT_RUNTIME = (
    "go14.sh",
    "go_v0.14.0.sh",
    "go_mmto_photometry_v14.sh",
    "scripts/run_mmto_photometry_pipeline_v14.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    hashes = {
        f"v14/{name}": value
        for name, value in manifest["sha256"].items()
    }
    hashes["v14/SOURCE_MANIFEST.json"] = digest(SOURCE)
    for relative in ROOT_RUNTIME:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        hashes[relative] = digest(path)
    record = {
        "version": "0.14.0",
        "snapshot_kind": (
            "lunar-corroboration v0.14.0 boundary before early celestial "
            "Sun/Moon gating v15"
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
