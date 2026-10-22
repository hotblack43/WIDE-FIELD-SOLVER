#!/usr/bin/env python3
"""Remeasure native MMTO FITS over a guarded v23 aperture-radius sweep."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v23.mmto_aperture_radius_benchmark import run_aperture_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--v21-control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-runs-per-night", type=int, default=2)
    parser.add_argument("--maximum-stars", type=int, default=128)
    parser.add_argument(
        "--reuse-aperture-run", type=Path,
        help="Reuse an input-matched completed aperture sweep and measure annuli only.")
    args = parser.parse_args()
    if args.maximum_runs_per_night < 1 or args.maximum_stars < 1:
        parser.error("sample limits must be positive")

    def progress(index: int, total: int, source: str) -> None:
        print(f"[{index}/{total}] {source}", flush=True)

    summary = run_aperture_benchmark(
        args.database, args.manifest, args.v21_control, args.output,
        maximum_runs_per_night=args.maximum_runs_per_night,
        maximum_stars=args.maximum_stars,
        reuse_aperture_run=args.reuse_aperture_run,
        progress=progress,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
