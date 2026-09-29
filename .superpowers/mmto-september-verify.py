#!/usr/bin/env python3
"""Verify MMTO September 1--11 cadence selections have no missing files."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from allsky_download.cli import main


status = 0
for day in range(1, 12):
    night = f"2026-09-{day:02d}"
    output = StringIO()
    with redirect_stdout(output):
        result = main([
            "--site", "mmto",
            "--camera", "mmto-skycam",
            "--night", night,
            "--sun-below", "-12",
            "--cadence", "20m",
            "--max-files", "1000",
            "--backfill-missing",
            "--dry-run",
            "--output", "raw_allsky_samples",
        ])
    match = re.search(r"^SUMMARY\t(.+)$", output.getvalue(), re.MULTILINE)
    summary = match.group(1) if match else "SUMMARY_MISSING"
    complete = result == 0 and "selected=0" in summary and "eligible=0" in summary
    print(f"{night}\tcomplete={str(complete).lower()}\t{summary}", flush=True)
    if not complete:
        status = 2

raise SystemExit(status)
