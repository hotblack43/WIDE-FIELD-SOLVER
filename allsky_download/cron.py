from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shlex
import sys
from typing import Sequence
from .cadence import observing_night_date
from .cli import main as downloader_main
from .registry import SourceRegistry


UTC = timezone.utc
DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "sources.json"
PROCESSING_CRON_MARKER = "# WIDE_FIELD_SOLVER_MMTO_PROCESSING_ACTIVE"


def processing_cron_lines(repo_root: Path, uv_executable: Path) -> tuple[str, str]:
    repo = Path(repo_root)
    archive = repo / "raw_allsky_samples"
    logs = archive / "processing-logs"
    results = repo / "results" / "mmto-automatic"
    quote = lambda path: shlex.quote(str(path))
    command = (
        "*/2 * * * * "
        f"cd {quote(repo)} && "
        f"mkdir -p {quote(logs)} {quote(results)} && "
        f"{quote(uv_executable)} run --frozen python run_allsky_processing.py "
        f"--archive {quote(archive)} --results-dir {quote(results)} "
        "--worker-lock /tmp/wide-field-solver-mmto-processing.lock "
        "work --once "
        f">> {quote(archive / 'mmto-processing-cron.log')} 2>&1"
    )
    return PROCESSING_CRON_MARKER, command


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
    registry = SourceRegistry.from_json(DEFAULT_REGISTRY)
    mmto = registry.get_adapter("mmto").sites("mmto-skycam")[0]
    night_date = observing_night_date(mmto, now)
    args = [
        "--site", "mmto",
        "--camera", "mmto-skycam",
        "--night", night_date.isoformat(),
        "--sun-below", "-12",
        "--cadence", "20m",
        "--max-files", "1",
        "--latest",
        "--enqueue-processing",
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
