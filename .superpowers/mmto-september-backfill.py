#!/usr/bin/env python3
"""Backfill the missing MMTO observing nights before 2026-09-12."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from allsky_download.cli import main


status = 0
for day in range(1, 12):
    night = f"2026-09-{day:02d}"
    print(f"BEGIN_NIGHT {night}", flush=True)
    result = main([
        "--site", "mmto",
        "--camera", "mmto-skycam",
        "--night", night,
        "--sun-below", "-12",
        "--cadence", "20m",
        "--max-files", "1000",
        "--backfill-missing",
        "--enqueue-processing",
        "--output", "raw_allsky_samples",
    ])
    print(f"END_NIGHT {night} status={result}", flush=True)
    status = max(status, result)

raise SystemExit(status)
