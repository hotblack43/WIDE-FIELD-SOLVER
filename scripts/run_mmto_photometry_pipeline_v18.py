#!/usr/bin/env python3
"""Scan the MMTO backlog and process at most two incomplete nights with v18."""
from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from allsky_download.cadence import (
    observing_night_date,
    select_candidates,
    site_night_range,
)
from allsky_download.cli import _destination
from allsky_download.http import HttpClient
from allsky_download.manifest import Manifest, output_lock
from allsky_download.model import Candidate, DateRange, Site
from allsky_download.processing import OperationalFailure, validated_input
from allsky_download.registry import SourceRegistry
from allsky_download.solar import filter_by_solar_altitude
from scripts.run_mmto_photometry_pipeline_v16 import (
    _list_figures,
    _message,
    _pipeline_lock,
    _run_command,
    _stage_commands,
    _write_summary,
)


SOLVER_VERSION = "0.18.0"
SOLVER_LAUNCHER = "go18.sh"
COMPATIBLE_SUCCESS_VERSIONS = ("0.16.0", SOLVER_VERSION)
DEFAULT_START_NIGHT = date(2026, 6, 30)
MAX_WORK_NIGHTS = 2
UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class MmtoImage:
    source_sha256: str
    observed_utc: str
    local_path: Path
    observed_bytes: int
    remote_url: str
    observing_night: date


@dataclass(frozen=True, slots=True)
class ProcessingPlan:
    eligible_images: int
    successful_receipts: int
    pending: tuple[MmtoImage, ...]


@dataclass(frozen=True, slots=True)
class AcquisitionSummary:
    nights_scanned: int
    files_selected: int
    files_missing: int
    files_downloaded: int
    backlog_files_missing: int = 0
    selected_nights: tuple[date, ...] = ()
    backlog_files_incomplete: int = 0


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    nights_scanned: int
    files_selected: int
    backlog_files_missing: int
    backlog_files_incomplete: int
    selected_nights: tuple[date, ...]
    missing: tuple[Candidate, ...]


def observing_nights(start_night: date, end_night: date) -> tuple[date, ...]:
    """Return an inclusive newest-first sequence of observing-night dates."""
    if end_night < start_night:
        raise ValueError("end observing night precedes start observing night")
    count = (end_night - start_night).days
    return tuple(end_night - timedelta(days=offset) for offset in range(count + 1))


def _successful_source_digests(results_database: Path) -> set[str]:
    results_database = Path(results_database)
    if not results_database.is_file():
        return set()
    placeholders = ",".join("?" for _ in COMPATIBLE_SUCCESS_VERSIONS)
    with closing(_read_only_database(results_database)) as database:
        return {
            str(row[0])
            for row in database.execute(
                f"""
                SELECT DISTINCT source_sha256
                FROM runs
                WHERE source_sha256 IS NOT NULL
                  AND exit_code=0
                  AND (
                      solver_version IN ({placeholders})
                      OR CASE
                          WHEN json_valid(source_manifest_json)
                          THEN json_extract(source_manifest_json, '$.version')
                               IN ({placeholders})
                          ELSE 0
                      END
                  )
                """,
                COMPATIBLE_SUCCESS_VERSIONS + COMPATIBLE_SUCCESS_VERSIONS,
            )
        }


def _verified_source_digests_by_url(archive: Path) -> dict[str, str]:
    manifest = Path(archive) / "manifest.sqlite"
    if not manifest.is_file():
        return {}
    with closing(_read_only_database(manifest)) as database:
        return {
            str(row[0]): str(row[1])
            for row in database.execute(
                """
                SELECT remote_url, sha256
                FROM downloads
                WHERE download_status='downloaded'
                  AND validation_status='verified'
                  AND sha256 IS NOT NULL
                """
            )
        }


def build_acquisition_plan(
    archive: Path,
    start_night: date,
    end_night: date,
    *,
    results_database: Path,
    adapter,
    client,
    site: Site,
) -> AcquisitionPlan:
    """Scan the complete range and select the newest analysis-incomplete nights."""
    nights = observing_nights(start_night, end_night)
    first = site_night_range(site, start_night)
    last = site_night_range(site, end_night)
    date_range = DateRange(first.start_utc, last.end_utc)
    candidates = adapter.list_candidates(client, site, date_range)
    dark = filter_by_solar_altitude(
        candidates,
        {(site.source_id, site.camera_id): site},
        sun_below_deg=-12,
    )
    selection = select_candidates(
        dark,
        {(site.source_id, site.camera_id): date_range},
        timedelta(minutes=20),
        max(1, len(dark)),
    )
    verified_by_url = _verified_source_digests_by_url(archive)
    successful = _successful_source_digests(results_database)
    backlog_incomplete = tuple(
        sorted(
            (
                candidate
                for candidate in selection.candidates
                if verified_by_url.get(candidate.url) not in successful
            ),
            key=lambda candidate: (candidate.observed_at, candidate.url),
            reverse=True,
        )
    )
    backlog_missing = tuple(
        candidate
        for candidate in selection.candidates
        if candidate.url not in verified_by_url
    )
    selected_nights = tuple(
        sorted(
            {
                observing_night_date(site, candidate.observed_at)
                for candidate in backlog_incomplete
            },
            reverse=True,
        )[:MAX_WORK_NIGHTS]
    )
    selected_night_set = set(selected_nights)
    missing = tuple(
        candidate
        for candidate in backlog_missing
        if observing_night_date(site, candidate.observed_at) in selected_night_set
    )
    return AcquisitionPlan(
        nights_scanned=len(nights),
        files_selected=len(selection.candidates),
        backlog_files_missing=len(backlog_missing),
        backlog_files_incomplete=len(backlog_incomplete),
        selected_nights=selected_nights,
        missing=missing,
    )


def sync_downloads(
    archive: Path,
    start_night: date,
    end_night: date,
    *,
    results_database: Path,
    dry_run: bool,
    adapter=None,
    client=None,
    site: Site | None = None,
) -> AcquisitionSummary:
    """Select two analysis-incomplete nights and download their manifest gaps."""
    registry = SourceRegistry.from_json(REPO_ROOT / "sources.json")
    adapter = adapter or registry.get_adapter("mmto")
    site = site or adapter.sites("mmto-skycam")[0]
    client = client or HttpClient()
    plan = build_acquisition_plan(
        archive,
        start_night,
        end_night,
        results_database=results_database,
        adapter=adapter,
        client=client,
        site=site,
    )
    if dry_run:
        return AcquisitionSummary(
            nights_scanned=plan.nights_scanned,
            files_selected=plan.files_selected,
            files_missing=len(plan.missing),
            files_downloaded=0,
            backlog_files_missing=plan.backlog_files_missing,
            selected_nights=plan.selected_nights,
            backlog_files_incomplete=plan.backlog_files_incomplete,
        )

    downloaded = 0
    by_night: dict[date, list[Candidate]] = {}
    for candidate in plan.missing:
        night = observing_night_date(site, candidate.observed_at)
        by_night.setdefault(night, []).append(candidate)
    for night in sorted(by_night, reverse=True):
        with output_lock(archive):
            with Manifest(Path(archive) / "manifest.sqlite") as manifest:
                for candidate in by_night[night]:
                    if manifest.verified_download(candidate, archive) is not None:
                        continue
                    manifest.record_attempt(candidate)
                    try:
                        result = client.download_atomic(
                            candidate,
                            _destination(archive, candidate, site),
                        )
                        manifest.record_success(candidate, result, archive)
                        downloaded += 1
                    except Exception as exc:
                        manifest.record_failure(candidate, str(exc))
                        raise
    return AcquisitionSummary(
        nights_scanned=plan.nights_scanned,
        files_selected=plan.files_selected,
        files_missing=len(plan.missing),
        files_downloaded=downloaded,
        backlog_files_missing=plan.backlog_files_missing,
        selected_nights=plan.selected_nights,
        backlog_files_incomplete=plan.backlog_files_incomplete,
    )


def _read_only_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _night_from_local_path(value: str) -> date | None:
    try:
        return date.fromisoformat(Path(value).parent.name)
    except ValueError:
        return None


def build_processing_plan(
    archive: Path,
    results_database: Path,
    *,
    start_night: date,
    end_night: date,
    selected_nights: Sequence[date],
) -> ProcessingPlan:
    """Select verified incomplete inputs from the bounded work nights."""
    if end_night < start_night:
        raise ValueError("end observing night precedes start observing night")
    manifest = Path(archive) / "manifest.sqlite"
    if not manifest.is_file():
        raise ValueError(f"acquisition manifest is missing: {manifest}")
    with closing(_read_only_database(manifest)) as database:
        rows = database.execute(
            """
            SELECT sha256, observed_utc, local_path, observed_bytes, remote_url
            FROM downloads
            WHERE source_id='mmto'
              AND camera_id='mmto-skycam'
              AND download_status='downloaded'
              AND validation_status='verified'
              AND sha256 IS NOT NULL
              AND local_path IS NOT NULL
              AND observed_bytes IS NOT NULL
            ORDER BY observed_utc, remote_url
            """
        ).fetchall()
    by_digest: dict[str, MmtoImage] = {}
    for row in rows:
        observing_night = _night_from_local_path(str(row[2]))
        if observing_night is None or not start_night <= observing_night <= end_night:
            continue
        digest = str(row[0])
        by_digest.setdefault(
            digest,
            MmtoImage(
                source_sha256=digest,
                observed_utc=str(row[1]),
                local_path=Path(str(row[2])),
                observed_bytes=int(row[3]),
                remote_url=str(row[4]),
                observing_night=observing_night,
            ),
        )
    successful = _successful_source_digests(results_database)
    selected_night_set = set(selected_nights)
    pending = tuple(
        sorted(
            (
                image
                for digest, image in by_digest.items()
                if digest not in successful
                and image.observing_night in selected_night_set
            ),
            key=lambda image: (
                image.observing_night,
                image.observed_utc,
                image.remote_url,
            ),
            reverse=True,
        )
    )
    return ProcessingPlan(
        eligible_images=len(by_digest),
        successful_receipts=len(set(by_digest) & successful),
        pending=pending,
    )


def solver_command(repo_root: Path, source: Path, results: Path) -> list[str]:
    return [
        str(Path(repo_root) / SOLVER_LAUNCHER),
        str(Path(source)),
        "--results-dir",
        str(Path(results)),
    ]


def _latest_solver_receipt(database_path: Path, source_sha256: str) -> int | None:
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
            (source_sha256, SOLVER_VERSION, SOLVER_VERSION),
        ).fetchone()
    return None if row is None else int(row[0])


def _has_successful_receipt(database_path: Path, source_sha256: str) -> bool:
    if not Path(database_path).is_file():
        return False
    placeholders = ",".join("?" for _ in COMPATIBLE_SUCCESS_VERSIONS)
    with closing(_read_only_database(database_path)) as database:
        row = database.execute(
            f"""
            SELECT 1 FROM runs
            WHERE source_sha256=? AND exit_code=0
              AND (
                  solver_version IN ({placeholders})
                  OR CASE
                      WHEN json_valid(source_manifest_json)
                      THEN json_extract(source_manifest_json, '$.version')
                           IN ({placeholders})
                      ELSE 0
                  END
              )
            LIMIT 1
            """,
            (
                source_sha256,
                *COMPATIBLE_SUCCESS_VERSIONS,
                *COMPATIBLE_SUCCESS_VERSIONS,
            ),
        ).fetchone()
    return row is not None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def current_mmto_night(repo_root: Path, now: datetime | None = None) -> date:
    instant = datetime.now(UTC) if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("current-time value must be timezone-aware")
    registry = SourceRegistry.from_json(Path(repo_root) / "sources.json")
    site = registry.get_adapter("mmto").sites("mmto-skycam")[0]
    return observing_night_date(site, instant)


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


def _date_value(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan dark-sky 20-minute MMTO samples from 2026-06-30 onward, "
            "select at most two newest nights without complete successful v16/v18 "
            "receipts, then download and analyse only those selected nights."
        )
    )
    parser.add_argument("--start-night", type=_date_value, default=DEFAULT_START_NIGHT)
    parser.add_argument("--end-night", type=_date_value)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path("/tmp/wide-field-solver-mmto-photometry-v18.lock"),
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    archive = (args.archive or repo_root / "raw_allsky_samples").resolve()
    results = (args.results_dir or _default_results_dir(repo_root)).resolve()
    end_night = args.end_night or current_mmto_night(repo_root)
    output = args.output
    summary: dict[str, object] | None = None
    try:
        observing_nights(args.start_night, end_night)
        if not args.dry_run:
            results.mkdir(parents=True, exist_ok=True)
            if output is None:
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                output = results / "photometry-runs" / f"v18-{timestamp}"
            output = output.resolve()
            if output.exists():
                raise OperationalFailure(f"output path already exists: {output}")

        lock_context = (
            _pipeline_lock(args.lock_file) if not args.dry_run else nullcontext()
        )
        with lock_context:
            database = results / "stars.sqlite"
            acquisition = sync_downloads(
                archive,
                args.start_night,
                end_night,
                results_database=database,
                dry_run=args.dry_run,
            )
            mode = "dry-run" if args.dry_run else "download"
            selected_nights = ",".join(
                night.isoformat() for night in acquisition.selected_nights
            ) or "none"
            print(
                f"MMTO_ACQUISITION start={args.start_night.isoformat()} "
                f"end={end_night.isoformat()} nights={acquisition.nights_scanned} "
                f"backlog_incomplete={acquisition.backlog_files_incomplete} "
                f"backlog_missing={acquisition.backlog_files_missing} "
                f"selected_nights={selected_nights} "
                f"scheduled_missing={acquisition.files_missing} "
                f"downloaded={acquisition.files_downloaded} mode={mode}"
            )
            plan = build_processing_plan(
                archive,
                database,
                start_night=args.start_night,
                end_night=end_night,
                selected_nights=acquisition.selected_nights,
            )
            print(
                f"MMTO_ANALYSIS eligible={plan.eligible_images} "
                f"successful_v16_or_v18={plan.successful_receipts} "
                f"selected_nights={selected_nights} "
                f"pending_selected={len(plan.pending)}"
            )
            if args.dry_run:
                print("DRY_RUN no files downloaded, no images processed, no products written")
                return 0

            assert output is not None
            output.mkdir(parents=True)
            summary = {
                "status": "running",
                "started_utc": _utc_now(),
                "solver_version": SOLVER_VERSION,
                "archive": str(archive),
                "database": str(database),
                "output": str(output),
                "boundary": {
                    "start_night": args.start_night.isoformat(),
                    "end_night": end_night.isoformat(),
                    "ordering": "newest_first",
                    "sun_below_deg": -12,
                    "cadence": "20m",
                },
                "acquisition": {
                    "nights_scanned": acquisition.nights_scanned,
                    "files_selected": acquisition.files_selected,
                    "files_missing": acquisition.files_missing,
                    "files_downloaded": acquisition.files_downloaded,
                    "backlog_files_missing": acquisition.backlog_files_missing,
                    "backlog_files_incomplete": acquisition.backlog_files_incomplete,
                    "selected_nights": [
                        night.isoformat() for night in acquisition.selected_nights
                    ],
                },
                "selection": {
                    "eligible_images": plan.eligible_images,
                    "successful_v16_or_v18_receipts": plan.successful_receipts,
                    "pending_at_start": len(plan.pending),
                },
                "processing": {
                    "attempted": 0,
                    "succeeded": 0,
                    "solver_failed": 0,
                    "concurrently_completed": 0,
                },
                "stages": [],
            }
            _write_summary(output, summary)
            with (output / "pipeline.log").open("a", encoding="utf-8") as log:
                _message(f"MMTO v18 pipeline started: {summary['started_utc']}", log)
                processing = summary["processing"]
                assert isinstance(processing, dict)
                for number, image in enumerate(plan.pending, 1):
                    if _has_successful_receipt(database, image.source_sha256):
                        processing["concurrently_completed"] += 1
                        _message(
                            f"SKIP [{number}/{len(plan.pending)}] successful receipt appeared: "
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
                    _message(f"PROCESS [{number}/{len(plan.pending)}] {source}", log)
                    return_code = _run_command(
                        solver_command(repo_root, source, results),
                        log,
                        cwd=repo_root,
                    )
                    receipt = _latest_solver_receipt(database, image.source_sha256)
                    if receipt is None:
                        raise OperationalFailure(
                            "go18 produced no v18 database receipt for "
                            f"{image.source_sha256}"
                        )
                    if (return_code == 0) != (receipt == 0):
                        raise OperationalFailure(
                            "go18 exit status disagrees with its database receipt for "
                            f"{image.source_sha256}"
                        )
                    processing["succeeded" if receipt == 0 else "solver_failed"] += 1
                    _write_summary(output, summary)

                if not database.is_file():
                    raise OperationalFailure(
                        f"results database does not exist after processing: {database}"
                    )
                stages = summary["stages"]
                assert isinstance(stages, list)
                for name, command in _stage_commands(repo_root, database, archive / "manifest.sqlite", output):
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
                _message(f"MMTO v18 pipeline complete: {output}", log)
                _list_figures(output, log)
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error, OperationalFailure) as exc:
        if output is not None and Path(output).is_dir() and summary is not None:
            try:
                summary["status"] = "operational_failed"
                summary["finished_utc"] = _utc_now()
                summary["error"] = str(exc)
                _write_summary(Path(output), summary)
            except OSError:
                pass
        print(f"MMTO v18 pipeline failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

