#!/usr/bin/env python3
"""Command-line entry point for the read-only v22 photometry benchmark."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v22.mmto_differential_benchmark import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline, read-only v22 stellar nuisance benchmark"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--v21-control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "v22/config/differential_photometry.json",
    )
    parser.add_argument("--run-ids", type=Path)
    args = parser.parse_args()
    summary = run_benchmark(
        args.database,
        args.manifest,
        args.v21_control,
        args.output,
        args.config,
        run_ids=args.run_ids,
    )
    print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
