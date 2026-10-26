#!/usr/bin/env python3
"""List newest v23 figures by relative product path, including failed runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


FIGURE_SUFFIXES = {".pdf", ".png", ".svg", ".jpg", ".jpeg"}
REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir", type=Path,
        default=REPO_ROOT / "results" / "photometry-runs",
        help="directory containing v23-* photometry runs",
    )
    args = parser.parse_args()
    runs = sorted(
        (path for path in args.runs_dir.glob("v23-*") if path.is_dir()),
        key=lambda path: path.name, reverse=True,
    )
    if not runs:
        parser.exit(1, f"No v23 photometry runs found in {args.runs_dir}\n")

    latest = runs[0]
    print(f"Latest v23 run: {latest.resolve()}")
    summary_path = latest / "pipeline_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        processing = summary.get("processing", {})
        print(
            f"Status: {summary.get('status', 'unknown')}; "
            f"{processing.get('attempted', 0)} attempted, "
            f"{processing.get('succeeded', 0)} solved, "
            f"{processing.get('solver_failed', 0)} solver failed"
        )
        if summary.get("error"):
            print(f"Stopped at: {summary['error']}")
        print(f"Summary: {summary_path.resolve()}")

    newest: dict[Path, tuple[Path, Path]] = {}
    for run in runs:
        for figure in run.rglob("*"):
            if figure.is_file() and figure.suffix.lower() in FIGURE_SUFFIXES:
                relative = figure.relative_to(run)
                newest.setdefault(relative, (run, figure))

    current_count = sum(run == latest for run, _ in newest.values())
    print(f"Plots: {current_count} from latest run; {len(newest) - current_count} from earlier runs")
    timeline = Path("acquisition_timeline.pdf")
    ordered = sorted(newest, key=lambda path: (path != timeline, str(path)))
    for relative in ordered:
        run, figure = newest[relative]
        origin = "latest run" if run == latest else f"earlier run {run.name}"
        print(f"[{origin}] {relative}: {figure.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
