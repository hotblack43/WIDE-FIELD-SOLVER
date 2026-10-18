#!/usr/bin/env python3
"""Bounded newest-first MMTO acquisition and v21 analysis pipeline."""
from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
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
    site_night_range,
)
from allsky_download.cli import _destination
from allsky_download.http import HttpClient
from allsky_download.manifest import Manifest, output_lock
from allsky_download.model import Candidate
from allsky_download.processing import OperationalFailure, validated_input
from allsky_download.registry import SourceRegistry
from allsky_download.solar import filter_by_solar_altitude
from scripts.run_mmto_photometry_pipeline_v19 import (
    _list_figures,
    _message,
    _pipeline_lock,
    _run_command,
    _stage_commands as _v19_stage_commands,
    _write_summary,
)


SOLVER_VERSION = "0.21.0"
SOLVER_LAUNCHER = "go21.sh"
DEFAULT_MAX_IMAGES = 40
DEFAULT_OLDEST_NIGHT = date(2026, 6, 30)
UTC = timezone.utc
CADENCE = timedelta(minutes=20)
CADENCE_BOUNDARY_TOLERANCE = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class BackfillState:
    archive: Path
    next_night: date


@dataclass(frozen=True, slots=True)
class SelectedImage:
    candidate: Candidate
    source_sha256: str | None
    local_path: Path | None
    observed_bytes: int | None
    downloaded: bool


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    candidate: Candidate
    source_sha256: str | None
    local_path: Path | None
    observed_bytes: int | None
    downloaded: bool


@dataclass(frozen=True, slots=True)
class ReadyImage:
    candidate: Candidate
    source_sha256: str
    path: Path
    observed_bytes: int


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    max_images: int
    cursor_before: date
    cursor_after: date
    nights_listed: tuple[date, ...]
    files_listed: int
    processed_receipts_skipped: int
    selected: tuple[SelectedImage, ...]


def _date_value(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Select at most 40 unfinished MMTO images through bounded one-night "
            "requests and walk backward from the current observing night."
        )
    )
    parser.add_argument("--max-images", type=_positive_int, default=DEFAULT_MAX_IMAGES)
    parser.add_argument(
        "--oldest-night", type=_date_value, default=DEFAULT_OLDEST_NIGHT
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--variable-min-period-days",
        type=float,
        default=5.0,
        help="exclusive lower variable-star period limit in days (default: 5)",
    )
    parser.add_argument(
        "--variable-max-period-days",
        type=float,
        default=30.0,
        help="exclusive upper variable-star period limit in days (default: 30)",
    )
    parser.add_argument(
        "--variable-max-catalogue-magnitude",
        type=float,
        default=5.0,
        help="exclusive catalogue-magnitude limit (default: 5)",
    )
    parser.add_argument(
        "--variable-start-utc",
        default="2026-06-30T00:00:00Z",
        help="inclusive UTC start for variable-star time series",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path("/tmp/wide-field-solver-mmto-photometry-v21.lock"),
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser


def _read_only_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _processed_source_digests(results_database: Path) -> set[str]:
    results_database = Path(results_database)
    if not results_database.is_file():
        return set()
    with closing(_read_only_database(results_database)) as database:
        tables = {
            str(row[0])
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "runs" not in tables:
            return set()
        return {
            str(row[0])
            for row in database.execute(
                "SELECT DISTINCT source_sha256 FROM runs "
                "WHERE source_sha256 IS NOT NULL"
            )
        }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"manifest observation time is not timezone-aware: {value}")
    return parsed.astimezone(UTC)


def _manifest_entries(archive: Path) -> dict[str, ManifestEntry]:
    manifest = Path(archive) / "manifest.sqlite"
    if not manifest.is_file():
        return {}
    with closing(_read_only_database(manifest)) as database:
        rows = database.execute(
            """
            SELECT remote_url, observed_utc, observed_raw, remote_filename,
                   advertised_bytes, local_path, observed_bytes, sha256,
                   download_status, validation_status
            FROM downloads
            WHERE source_id='mmto' AND camera_id='mmto-skycam'
            ORDER BY observed_utc, remote_url
            """
        ).fetchall()
    entries: dict[str, ManifestEntry] = {}
    for row in rows:
        observed = _parse_utc(str(row[1]))
        item = Candidate(
            "mmto",
            "mmto-skycam",
            observed,
            str(row[2]),
            str(row[0]),
            str(row[3]),
            None if row[4] is None else int(row[4]),
            {},
        )
        downloaded = row[8:10] == ("downloaded", "verified")
        entries[item.url] = ManifestEntry(
            candidate=item,
            source_sha256=None if row[7] is None else str(row[7]),
            local_path=None if row[5] is None else Path(str(row[5])),
            observed_bytes=None if row[6] is None else int(row[6]),
            downloaded=downloaded,
        )
    return entries


def load_backfill_state(
    state_path: Path, archive: Path, default_night: date
) -> BackfillState:
    archive = Path(archive).resolve()
    state_path = Path(state_path)
    if not state_path.is_file():
        return BackfillState(archive, default_night)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"unsupported v21 backfill state: {state_path}")
    recorded_archive = Path(str(payload.get("archive", ""))).resolve()
    if recorded_archive != archive:
        raise ValueError(
            "v21 backfill state belongs to a different archive: "
            f"{recorded_archive} != {archive}"
        )
    try:
        next_night = date.fromisoformat(str(payload["next_night"]))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid v21 backfill state: {state_path}") from exc
    return BackfillState(archive, next_night)


def write_backfill_state_atomic(
    state_path: Path, archive: Path, next_night: date
) -> None:
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "archive": str(Path(archive).resolve()),
        "next_night": next_night.isoformat(),
    }
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, state_path)


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


def current_mmto_night(site, now: datetime | None = None) -> date:
    instant = datetime.now(UTC) if now is None else now
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("current-time value must be timezone-aware")
    return observing_night_date(site, instant)


def _cadence_slot(site, item: Candidate) -> tuple[date, int]:
    """Assign jittered exposures to the nearest nominal 20-minute instant."""
    night = observing_night_date(site, item.observed_at)
    requested = site_night_range(site, night)
    seconds = (
        item.observed_at.astimezone(UTC) - requested.start_utc
    ).total_seconds()
    slot = int(seconds // CADENCE.total_seconds())
    return night, slot


def _cadence_winners(site, candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
    """Choose one exposure per fixed slot and collapse boundary jitter."""
    winners: dict[tuple[date, int], Candidate] = {}
    for item in candidates:
        key = _cadence_slot(site, item)
        previous = winners.get(key)
        if previous is None or (item.observed_at.astimezone(UTC), item.url) < (
            previous.observed_at.astimezone(UTC), previous.url
        ):
            winners[key] = item
    collapsed: list[Candidate] = []
    cadence_seconds = CADENCE.total_seconds()

    def boundary_score(item: Candidate) -> tuple[float, datetime, str]:
        requested = site_night_range(site, observing_night_date(site, item.observed_at))
        seconds = (item.observed_at.astimezone(UTC) - requested.start_utc).total_seconds()
        phase = seconds % cadence_seconds
        return min(phase, cadence_seconds - phase), item.observed_at.astimezone(UTC), item.url

    for item in sorted(winners.values(), key=lambda value: (value.observed_at, value.url)):
        if (collapsed and item.observed_at.astimezone(UTC)
                - collapsed[-1].observed_at.astimezone(UTC)
                <= CADENCE_BOUNDARY_TOLERANCE):
            if boundary_score(item) < boundary_score(collapsed[-1]):
                collapsed[-1] = item
        else:
            collapsed.append(item)
    return tuple(collapsed)


def _covered_cadence(
    site,
    item: Candidate,
    slots: set[tuple[date, int]],
    representatives: Sequence[Candidate],
) -> bool:
    key = _cadence_slot(site, item)
    if key in slots:
        return True
    observed = item.observed_at.astimezone(UTC)
    return any(
        observing_night_date(site, other.observed_at) == key[0]
        and abs(other.observed_at.astimezone(UTC) - observed)
        <= CADENCE_BOUNDARY_TOLERANCE
        for other in representatives
    )


def _stage_commands(
    repo_root: Path,
    database: Path,
    manifest: Path,
    output: Path,
    *,
    variable_min_period_days: float = 5.0,
    variable_max_period_days: float = 30.0,
    variable_max_catalogue_magnitude: float = 5.0,
    variable_start_utc: str = "2026-06-30T00:00:00Z",
) -> tuple[tuple[str, list[str]], ...]:
    stages = list(
        _v19_stage_commands(
            repo_root,
            database,
            manifest,
            output,
            variable_min_period_days=variable_min_period_days,
            variable_max_period_days=variable_max_period_days,
            variable_max_catalogue_magnitude=variable_max_catalogue_magnitude,
            variable_start_utc=variable_start_utc,
        )
    )
    for index, (name, command) in enumerate(stages):
        if name == "variable_star_time_series":
            stages[index] = (
                name,
                [str(Path(repo_root) / "plot_mmto_variable_stars_v21.sh"), *command[1:]],
            )
    return tuple(stages)


def _selected_from_entry(entry: ManifestEntry) -> SelectedImage:
    return SelectedImage(
        candidate=entry.candidate,
        source_sha256=entry.source_sha256,
        local_path=entry.local_path,
        observed_bytes=entry.observed_bytes,
        downloaded=entry.downloaded,
    )


def _selected_from_candidate(
    item: Candidate, entry: ManifestEntry | None
) -> SelectedImage:
    if entry is not None:
        return SelectedImage(
            candidate=item,
            source_sha256=entry.source_sha256,
            local_path=entry.local_path,
            observed_bytes=entry.observed_bytes,
            downloaded=entry.downloaded,
        )
    return SelectedImage(item, None, None, None, False)


def build_acquisition_plan(
    archive: Path,
    results_database: Path,
    *,
    state_path: Path,
    current_night: date,
    oldest_night: date,
    max_images: int,
    adapter,
    client,
    site,
) -> AcquisitionPlan:
    """Select a bounded batch without listing a multi-night MMTO range."""

    if max_images <= 0:
        raise ValueError("max_images must be positive")
    if oldest_night > current_night:
        raise ValueError("oldest observing night follows current observing night")
    state = load_backfill_state(state_path, archive, current_night)
    if state.next_night > current_night:
        raise ValueError("v21 backfill cursor is later than the current night")

    processed = _processed_source_digests(results_database)
    entries = _manifest_entries(archive)
    selected: list[SelectedImage] = []
    selected_urls: set[str] = set()
    selected_digests: set[str] = set()
    completed_slots = {
        _cadence_slot(site, entry.candidate)
        for entry in entries.values()
        if entry.source_sha256 is not None and entry.source_sha256 in processed
    }
    completed_candidates = tuple(
        entry.candidate
        for entry in entries.values()
        if entry.source_sha256 is not None and entry.source_sha256 in processed
    )
    selected_slots: set[tuple[date, int]] = set()
    selected_candidates: list[Candidate] = []
    skipped: set[tuple[str, str]] = set()

    local_pending = sorted(
        _cadence_winners(site, tuple(
            entry.candidate
            for entry in entries.values()
            if entry.downloaded
            and entry.source_sha256 is not None
            and entry.source_sha256 not in processed
            and not _covered_cadence(
                site, entry.candidate, completed_slots, completed_candidates
            )
            and oldest_night
            <= observing_night_date(site, entry.candidate.observed_at)
            <= current_night
        )),
        key=lambda item: (item.observed_at, item.url),
        reverse=True,
    )
    for entry in entries.values():
        if entry.source_sha256 is not None and entry.source_sha256 in processed:
            skipped.add(("digest", entry.source_sha256))
    for candidate_item in local_pending:
        entry = entries[candidate_item.url]
        assert entry.source_sha256 is not None
        if entry.source_sha256 in selected_digests:
            continue
        slot = _cadence_slot(site, entry.candidate)
        if slot in selected_slots:
            continue
        selected.append(_selected_from_entry(entry))
        selected_urls.add(entry.candidate.url)
        selected_digests.add(entry.source_sha256)
        selected_slots.add(slot)
        selected_candidates.append(entry.candidate)
        if len(selected) == max_images:
            return AcquisitionPlan(
                max_images,
                state.next_night,
                state.next_night,
                (),
                0,
                len(skipped),
                tuple(selected),
            )

    nights_listed: list[date] = []
    files_listed = 0
    cursor_after = state.next_night

    def scan_night(night: date) -> bool:
        """Append available work and return whether the whole night was considered."""
        nonlocal files_listed
        requested = site_night_range(site, night)
        raw = adapter.list_candidates(client, site, requested)
        nights_listed.append(night)
        dark = filter_by_solar_altitude(
            raw, {(site.source_id, site.camera_id): site}, sun_below_deg=-12
        )
        cadence_items = tuple(
            sorted(
                _cadence_winners(site, tuple(dark)),
                key=lambda item: (item.observed_at, item.url),
                reverse=True,
            )
        )
        files_listed += len(cadence_items)
        unfinished: list[SelectedImage] = []
        for item in cadence_items:
            slot = _cadence_slot(site, item)
            if (_covered_cadence(site, item, completed_slots, completed_candidates)
                    or _covered_cadence(site, item, selected_slots, selected_candidates)):
                continue
            if item.url in selected_urls:
                continue
            entry = entries.get(item.url)
            digest = None if entry is None else entry.source_sha256
            if digest is not None and digest in processed:
                skipped.add(("digest", digest))
                continue
            if digest is not None and digest in selected_digests:
                continue
            unfinished.append(_selected_from_candidate(item, entry))
        capacity = max_images - len(selected)
        chosen = unfinished[:capacity]
        selected.extend(chosen)
        selected_urls.update(item.candidate.url for item in chosen)
        selected_slots.update(_cadence_slot(site, item.candidate) for item in chosen)
        selected_candidates.extend(item.candidate for item in chosen)
        selected_digests.update(
            item.source_sha256
            for item in chosen
            if item.source_sha256 is not None
        )
        return len(chosen) == len(unfinished)

    if current_night >= oldest_night:
        complete = scan_night(current_night)
        if len(selected) == max_images:
            if state.next_night == current_night and complete:
                cursor_after = current_night - timedelta(days=1)
            return AcquisitionPlan(
                max_images,
                state.next_night,
                cursor_after,
                tuple(nights_listed),
                files_listed,
                len(skipped),
                tuple(selected),
            )

    cursor = state.next_night
    if cursor == current_night:
        cursor -= timedelta(days=1)
        cursor_after = cursor
    while cursor >= oldest_night and len(selected) < max_images:
        complete = scan_night(cursor)
        if complete:
            cursor_after = cursor - timedelta(days=1)
        else:
            cursor_after = cursor
        if len(selected) == max_images:
            break
        cursor -= timedelta(days=1)

    return AcquisitionPlan(
        max_images=max_images,
        cursor_before=state.next_night,
        cursor_after=cursor_after,
        nights_listed=tuple(nights_listed),
        files_listed=files_listed,
        processed_receipts_skipped=len(skipped),
        selected=tuple(selected),
    )


def acquire_selected_images(
    archive: Path,
    selected: Sequence[SelectedImage],
    *,
    client,
    site,
) -> tuple[tuple[ReadyImage, ...], int, int]:
    """Validate/reuse known files and download only selected manifest gaps."""

    archive = Path(archive)
    ready: list[ReadyImage] = []
    reused = 0
    downloaded = 0
    with output_lock(archive):
        with Manifest(archive / "manifest.sqlite") as manifest:
            for item in selected:
                existing = manifest.verified_download(item.candidate, archive)
                if existing is not None:
                    reused += 1
                else:
                    manifest.record_attempt(item.candidate)
                    try:
                        existing = client.download_atomic(
                            item.candidate,
                            _destination(archive, item.candidate, site),
                        )
                        manifest.record_success(item.candidate, existing, archive)
                        downloaded += 1
                    except Exception as exc:
                        manifest.record_failure(item.candidate, str(exc))
                        raise
                ready.append(
                    ReadyImage(
                        candidate=item.candidate,
                        source_sha256=existing.sha256,
                        path=existing.path,
                        observed_bytes=existing.size_bytes,
                    )
                )
    return tuple(ready), reused, downloaded


def _has_any_receipt(database_path: Path, source_sha256: str) -> bool:
    if not Path(database_path).is_file():
        return False
    with closing(_read_only_database(database_path)) as database:
        row = database.execute(
            "SELECT 1 FROM runs WHERE source_sha256=? LIMIT 1", (source_sha256,)
        ).fetchone()
    return row is not None


def _latest_v21_receipt(database_path: Path, source_sha256: str) -> int | None:
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


def solver_command(repo_root: Path, source: Path, results: Path) -> list[str]:
    return [
        str(Path(repo_root) / SOLVER_LAUNCHER),
        str(Path(source)),
        "--results-dir",
        str(Path(results)),
    ]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter=None,
    client=None,
    site=None,
    now: datetime | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    archive = (args.archive or repo_root / "raw_allsky_samples").resolve()
    results = (args.results_dir or _default_results_dir(repo_root)).resolve()
    database = results / "stars.sqlite"
    state_path = (args.state_file or results / "mmto-v21-backfill-state.json").resolve()
    output = args.output
    summary: dict[str, object] | None = None
    registry = SourceRegistry.from_json(REPO_ROOT / "sources.json")
    adapter = adapter or registry.get_adapter("mmto")
    site = site or adapter.sites("mmto-skycam")[0]
    client = client or HttpClient()
    current_night = current_mmto_night(site, now)
    try:
        if args.oldest_night > current_night:
            raise ValueError("oldest observing night follows current observing night")
        if not args.dry_run:
            results.mkdir(parents=True, exist_ok=True)
            if output is None:
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                output = results / "photometry-runs" / f"v21-{timestamp}"
            output = output.resolve()
            if output.exists():
                raise OperationalFailure(f"output path already exists: {output}")

        lock_context = _pipeline_lock(args.lock_file) if not args.dry_run else nullcontext()
        with lock_context:
            plan = build_acquisition_plan(
                archive,
                database,
                state_path=state_path,
                current_night=current_night,
                oldest_night=args.oldest_night,
                max_images=args.max_images,
                adapter=adapter,
                client=client,
                site=site,
            )
            print(
                f"MMTO_V21_PLAN current={current_night.isoformat()} "
                f"oldest={args.oldest_night.isoformat()} max_images={plan.max_images} "
                f"cursor_before={plan.cursor_before.isoformat()} "
                f"cursor_after={plan.cursor_after.isoformat()} "
                f"nights_listed={len(plan.nights_listed)} "
                f"files_listed={plan.files_listed} "
                f"receipt_skipped={plan.processed_receipts_skipped} "
                f"selected={len(plan.selected)}"
            )
            for item in plan.selected:
                source = item.local_path if item.local_path is not None else item.candidate.url
                print(f"SELECT\t{item.candidate.observed_at.isoformat()}\t{source}")
            if args.dry_run:
                print("DRY_RUN no files downloaded, no images processed, no state advanced")
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
                "state_file": str(state_path),
                "selection": {
                    "max_images": plan.max_images,
                    "current_night": current_night.isoformat(),
                    "oldest_night": args.oldest_night.isoformat(),
                    "cursor_before": plan.cursor_before.isoformat(),
                    "cursor_after_proposed": plan.cursor_after.isoformat(),
                    "nights_listed": [night.isoformat() for night in plan.nights_listed],
                    "files_listed": plan.files_listed,
                    "processed_receipts_skipped": plan.processed_receipts_skipped,
                    "selected": len(plan.selected),
                },
                "acquisition": {"reused": 0, "downloaded": 0},
                "processing": {
                    "attempted": 0,
                    "succeeded": 0,
                    "solver_failed": 0,
                    "receipt_skipped": 0,
                },
                "stages": [],
                "outputs": {
                    "stellar_lightcurves": str(output / "stellar-lightcurves"),
                    "nightly_extinction": str(output / "nightly-extinction"),
                    "variable_star_time_series": str(output / "variable-stars"),
                    "planet_photometry": str(output / "planet-photometry"),
                    "planet_empirical_extinction": str(
                        output / "planet-empirical-extinction"
                    ),
                },
            }
            _write_summary(output, summary)
            with (output / "pipeline.log").open("a", encoding="utf-8") as log:
                _message(f"MMTO v21 pipeline started: {summary['started_utc']}", log)
                ready, reused, downloaded = acquire_selected_images(
                    archive, plan.selected, client=client, site=site
                )
                acquisition = summary["acquisition"]
                assert isinstance(acquisition, dict)
                acquisition.update({"reused": reused, "downloaded": downloaded})
                _write_summary(output, summary)

                processing = summary["processing"]
                assert isinstance(processing, dict)
                for number, image in enumerate(ready, 1):
                    if _has_any_receipt(database, image.source_sha256):
                        processing["receipt_skipped"] += 1
                        _message(
                            f"SKIP [{number}/{len(ready)}] receipt exists: "
                            f"{image.source_sha256}",
                            log,
                        )
                        continue
                    source = validated_input(
                        archive,
                        image.path.relative_to(archive).as_posix(),
                        image.observed_bytes,
                        image.source_sha256,
                    )
                    processing["attempted"] += 1
                    _message(f"PROCESS [{number}/{len(ready)}] {source}", log)
                    return_code = _run_command(
                        solver_command(repo_root, source, results), log, cwd=repo_root
                    )
                    receipt = _latest_v21_receipt(database, image.source_sha256)
                    if receipt is None:
                        raise OperationalFailure(
                            "go20 produced no v21 database receipt for "
                            f"{image.source_sha256}"
                        )
                    if (return_code == 0) != (receipt == 0):
                        raise OperationalFailure(
                            "go20 exit status disagrees with its database receipt for "
                            f"{image.source_sha256}"
                        )
                    processing["succeeded" if receipt == 0 else "solver_failed"] += 1
                    _write_summary(output, summary)

                write_backfill_state_atomic(state_path, archive, plan.cursor_after)
                selection_summary = summary["selection"]
                assert isinstance(selection_summary, dict)
                selection_summary["cursor_committed"] = plan.cursor_after.isoformat()
                _write_summary(output, summary)

                if not database.is_file():
                    raise OperationalFailure(
                        f"results database does not exist after processing: {database}"
                    )
                stages = summary["stages"]
                assert isinstance(stages, list)
                for name, command in _stage_commands(
                    repo_root,
                    database,
                    archive / "manifest.sqlite",
                    output,
                    variable_min_period_days=args.variable_min_period_days,
                    variable_max_period_days=args.variable_max_period_days,
                    variable_max_catalogue_magnitude=(
                        args.variable_max_catalogue_magnitude
                    ),
                    variable_start_utc=args.variable_start_utc,
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
                _message(f"MMTO v21 pipeline complete: {output}", log)
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
        print(f"MMTO v21 pipeline failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
