#!/usr/bin/env python3
"""Process unattempted MMTO images, then regenerate photometry products."""

from __future__ import annotations

import argparse
from contextlib import closing
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Iterator, Sequence, TextIO


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from allsky_download.processing import OperationalFailure, validated_input


V11_VERSION = "0.11.0"
UTC = timezone.utc
FIGURE_SUFFIXES = frozenset({".pdf", ".png"})


class PipelineBusyError(OperationalFailure):
    """Another complete MMTO pipeline owns the orchestration lock."""


@dataclass(frozen=True, slots=True)
class MmtoImage:
    source_sha256: str
    observed_utc: str
    local_path: Path
    observed_bytes: int
    remote_url: str


@dataclass(frozen=True, slots=True)
class ProcessingPlan:
    verified_mmto_images: int
    skipped_v11_receipts: int
    pending: tuple[MmtoImage, ...]


def _read_only_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def build_processing_plan(
    archive: Path,
    results_database: Path,
    *,
    solver_version: str = V11_VERSION,
) -> ProcessingPlan:
    """Return verified MMTO images lacking any receipt for the selected solver."""

    manifest = Path(archive) / "manifest.sqlite"
    if not manifest.is_file():
        raise ValueError(f"acquisition manifest is missing: {manifest}")
    with closing(_read_only_database(manifest)) as database:
        rows = database.execute(
            """
            SELECT source_sha256, observed_utc, local_path, observed_bytes, remote_url
            FROM (
                SELECT sha256 AS source_sha256, observed_utc, local_path,
                       observed_bytes, remote_url,
                       row_number() OVER (
                           PARTITION BY sha256 ORDER BY observed_utc, remote_url
                       ) AS duplicate_number
                FROM downloads
                WHERE source_id='mmto'
                  AND download_status='downloaded'
                  AND validation_status='verified'
                  AND sha256 IS NOT NULL
                  AND local_path IS NOT NULL
                  AND observed_bytes IS NOT NULL
            )
            WHERE duplicate_number=1
            ORDER BY observed_utc, remote_url
            """
        ).fetchall()
    images = tuple(
        MmtoImage(
            source_sha256=str(row[0]),
            observed_utc=str(row[1]),
            local_path=Path(str(row[2])),
            observed_bytes=int(row[3]),
            remote_url=str(row[4]),
        )
        for row in rows
    )

    processed: set[str] = set()
    results_database = Path(results_database)
    if results_database.is_file():
        with closing(_read_only_database(results_database)) as database:
            processed = {
                str(row[0])
                for row in database.execute(
                    """
                    SELECT DISTINCT source_sha256
                    FROM runs
                    WHERE source_sha256 IS NOT NULL
                      AND (
                          solver_version=?
                          OR CASE
                              WHEN json_valid(source_manifest_json)
                              THEN json_extract(source_manifest_json, '$.version')=?
                              ELSE 0
                          END
                      )
                    """,
                    (solver_version, solver_version),
                )
            }
    pending = tuple(
        image for image in images if image.source_sha256 not in processed
    )
    return ProcessingPlan(
        verified_mmto_images=len(images),
        skipped_v11_receipts=len(images) - len(pending),
        pending=pending,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _latest_v11_receipt(database_path: Path, source_sha256: str) -> int | None:
    if not Path(database_path).is_file():
        return None
    with closing(_read_only_database(database_path)) as database:
        row = database.execute(
            """
            SELECT exit_code FROM runs
            WHERE source_sha256=?
              AND (
                  solver_version=?
                  OR CASE
                      WHEN json_valid(source_manifest_json)
                      THEN json_extract(source_manifest_json, '$.version')=?
                      ELSE 0
                  END
              )
            ORDER BY rowid DESC LIMIT 1
            """,
            (source_sha256, V11_VERSION, V11_VERSION),
        ).fetchone()
    return None if row is None else int(row[0])


@contextmanager
def _pipeline_lock(path: Path) -> Iterator[None]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineBusyError(f"pipeline lock is already held: {path}") from exc
        lock.seek(0)
        lock.truncate()
        lock.write(f"pid={os.getpid()} acquired_utc={_utc_now()}\n")
        lock.flush()
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_summary(output: Path, summary: dict[str, object]) -> None:
    (output / "pipeline_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _message(message: str, log: TextIO) -> None:
    print(message, flush=True)
    log.write(message + "\n")
    log.flush()


def _list_figures(output: Path, log: TextIO) -> None:
    paths = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES
    )
    _message(f"FIGURES ({len(paths)})", log)
    for path in paths:
        _message(str(path), log)


def _run_command(command: list[str], log: TextIO, *, cwd: Path) -> int:
    _message("COMMAND\t" + "\t".join(command), log)
    with subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        return process.wait()


def _default_results_dir(repo_root: Path) -> Path:
    override = os.environ.get("WFS_RESULTS_DIR")
    if override:
        return Path(override)
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config = config_root / "wide-field-solver" / f"results-dir.{os.uname().nodename}"
    if config.is_file():
        configured = Path(config.read_text(encoding="utf-8").splitlines()[0])
        if not configured.is_absolute() or not configured.is_dir():
            raise ValueError(f"configured results directory is unavailable: {configured}")
        return configured
    return Path(repo_root) / "results"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process verified MMTO images without v11 receipts, then regenerate "
            "stellar and extinction-corrected planetary photometry."
        )
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path("/tmp/wide-field-solver-mmto-photometry.lock"),
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser


def _stage_commands(
    repo_root: Path,
    database: Path,
    manifest: Path,
    output: Path,
) -> tuple[tuple[str, list[str]], ...]:
    nightly = output / "nightly-extinction"
    return (
        (
            "stellar_lightcurves",
            [
                str(repo_root / "plot_mmto_lightcurves.sh"),
                "--database", str(database),
                "--manifest", str(manifest),
                "--output", str(output / "stellar-lightcurves"),
            ],
        ),
        (
            "nightly_extinction",
            [
                str(repo_root / "calibrate_mmto_extinction.sh"),
                "--database", str(database),
                "--manifest", str(manifest),
                "--output", str(nightly),
            ],
        ),
        (
            "planet_photometry",
            [
                str(repo_root / "plot_ALL_planets.sh"),
                "--database", str(database),
                "--nightly-calibration", str(nightly),
                "--output", str(output / "planet-photometry"),
            ],
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    archive = (args.archive or repo_root / "raw_allsky_samples").resolve()
    results = (args.results_dir or _default_results_dir(repo_root)).resolve()
    database = results / "stars.sqlite"
    manifest = archive / "manifest.sqlite"
    try:
        plan = build_processing_plan(archive, database)
        print(
            f"MMTO_PLAN verified={plan.verified_mmto_images} "
            f"skipped_v11={plan.skipped_v11_receipts} pending={len(plan.pending)}"
        )
        for image in plan.pending:
            print(
                f"PENDING\t{image.observed_utc}\t{image.source_sha256}\t"
                f"{archive / image.local_path}"
            )
        if args.dry_run:
            print("DRY_RUN no images processed and no products written")
            return 0

        results.mkdir(parents=True, exist_ok=True)
        output = args.output
        if output is None:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            output = results / "photometry-runs" / timestamp
        output = output.resolve()
        if output.exists():
            raise OperationalFailure(f"output path already exists: {output}")

        with _pipeline_lock(args.lock_file):
            output.mkdir(parents=True)
            summary: dict[str, object] = {
                "status": "running",
                "started_utc": _utc_now(),
                "solver_version": V11_VERSION,
                "archive": str(archive),
                "database": str(database),
                "output": str(output),
                "selection": {
                    "verified_mmto_images": plan.verified_mmto_images,
                    "skipped_v11_receipts": plan.skipped_v11_receipts,
                    "pending_at_start": len(plan.pending),
                },
                "processing": {
                    "attempted": 0,
                    "succeeded": 0,
                    "solver_failed": 0,
                    "concurrently_completed": 0,
                },
                "stages": [],
                "outputs": {
                    "stellar_lightcurves": str(output / "stellar-lightcurves"),
                    "nightly_extinction": str(output / "nightly-extinction"),
                    "planet_photometry": str(output / "planet-photometry"),
                },
            }
            _write_summary(output, summary)
            with (output / "pipeline.log").open("a", encoding="utf-8") as log:
                _message(
                    f"MMTO pipeline started: {summary['started_utc']}", log
                )
                processing = summary["processing"]
                assert isinstance(processing, dict)
                for number, image in enumerate(plan.pending, 1):
                    if _latest_v11_receipt(database, image.source_sha256) is not None:
                        processing["concurrently_completed"] += 1
                        _message(
                            f"SKIP [{number}/{len(plan.pending)}] receipt appeared: "
                            f"{image.source_sha256}",
                            log,
                        )
                        continue
                    source = validated_input(
                        archive,
                        image.local_path.as_posix(),
                        image.observed_bytes,
                        image.source_sha256,
                    )
                    processing["attempted"] += 1
                    _message(
                        f"PROCESS [{number}/{len(plan.pending)}] {source}", log
                    )
                    return_code = _run_command(
                        [
                            str(repo_root / "go11.sh"),
                            str(source),
                            "--results-dir", str(results),
                        ],
                        log,
                        cwd=repo_root,
                    )
                    receipt = _latest_v11_receipt(database, image.source_sha256)
                    if receipt is None:
                        raise OperationalFailure(
                            "go11 produced no v11 database receipt for "
                            f"{image.source_sha256}"
                        )
                    if (return_code == 0) != (receipt == 0):
                        raise OperationalFailure(
                            "go11 exit status disagrees with its database receipt for "
                            f"{image.source_sha256}"
                        )
                    key = "succeeded" if receipt == 0 else "solver_failed"
                    processing[key] += 1
                    _write_summary(output, summary)

                if not database.is_file():
                    raise OperationalFailure(
                        f"results database does not exist after processing: {database}"
                    )
                stages = summary["stages"]
                assert isinstance(stages, list)
                for name, command in _stage_commands(
                    repo_root, database, manifest, output
                ):
                    _message(f"STAGE {name}", log)
                    return_code = _run_command(command, log, cwd=repo_root)
                    stages.append({"name": name, "exit_code": return_code})
                    _write_summary(output, summary)
                    if return_code != 0:
                        raise OperationalFailure(
                            f"photometry stage {name} exited {return_code}"
                        )
                summary["status"] = "complete"
                summary["finished_utc"] = _utc_now()
                _write_summary(output, summary)
                _message(f"MMTO pipeline complete: {output}", log)
                _list_figures(output, log)
        return 0
    except (OSError, ValueError, sqlite3.Error, OperationalFailure) as exc:
        if "output" in locals() and isinstance(output, Path) and output.is_dir():
            try:
                summary["status"] = "operational_failed"
                summary["finished_utc"] = _utc_now()
                summary["error"] = str(exc)
                _write_summary(output, summary)
            except (NameError, OSError):
                pass
        print(f"MMTO photometry pipeline failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
