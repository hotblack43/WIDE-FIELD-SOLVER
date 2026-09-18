from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Sequence
from zoneinfo import ZoneInfo

from .cli import main as downloader_main


UTC = timezone.utc


def cron_download_arguments(
    site: str, now: datetime, output: Path, *, dry_run: bool
) -> list[str]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("cron clock must be timezone-aware")
    if site == "rubin":
        raise ValueError(
            "Rubin has no continuing public RAW archive; only the verified static CR2 sample is public"
        )
    if site != "mmto":
        raise ValueError(f"site is not enabled for recurring RAW acquisition: {site}")
    local_date = now.astimezone(ZoneInfo("America/Phoenix")).date().isoformat()
    args = [
        "--site", "mmto",
        "--camera", "mmto-skycam",
        "--date", local_date,
        "--cadence", "20m",
        "--max-files", "1",
        "--latest",
        "--output", str(output),
    ]
    if dry_run:
        args.append("--dry-run")
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one safe 20-minute incremental RAW all-sky acquisition cycle."
    )
    parser.add_argument("--site", required=True, choices=("mmto", "rubin"))
    parser.add_argument("--output", type=Path, default=Path("raw_allsky_samples"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        downloader_args = cron_download_arguments(
            args.site, datetime.now(UTC), args.output, dry_run=args.dry_run
        )
    except ValueError as exc:
        print(f"raw all-sky cron cycle refused: {exc}", file=sys.stderr)
        return 3
    return downloader_main(downloader_args)
