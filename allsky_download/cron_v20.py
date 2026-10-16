"""Current MMTO cron configuration with one canonical solver database.

The v15-era ``allsky_download.cron`` module is frozen evidence.  Acquisition
behavior remains imported from it; only the active processing destination is
defined here.
"""
from __future__ import annotations

from pathlib import Path
import shlex

from .cron import *  # noqa: F401,F403 - preserve the frozen acquisition API
from .cron import PROCESSING_CRON_MARKER


def processing_cron_lines(repo_root: Path, uv_executable: Path) -> tuple[str, str]:
    repo = Path(repo_root)
    archive = repo / "raw_allsky_samples"
    logs = archive / "processing-logs"
    results = repo / "results"
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
