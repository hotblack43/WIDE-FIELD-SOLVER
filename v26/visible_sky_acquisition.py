"""Bounded managed-archive acquisition before automatic mask calibration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Callable, Sequence
from zoneinfo import ZoneInfo


UTC = timezone.utc


@dataclass(frozen=True)
class AcquisitionRequest:
    source_id: str
    camera_id: str
    night_date: str
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class AcquisitionResult:
    attempted_requests: int
    failed_requests: int


def _verified_date_counts(
    manifest: Path, source_id: str, camera_id: str
) -> dict[str, int]:
    if not manifest.is_file():
        return {}
    uri = f"{manifest.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT observed_utc
            FROM downloads
            WHERE source_id=? AND camera_id=?
              AND download_status='downloaded'
              AND validation_status='verified'
            """,
            (source_id, camera_id),
        ).fetchall()
    counts: dict[str, int] = {}
    for (observed_utc,) in rows:
        observed = datetime.fromisoformat(str(observed_utc).replace("Z", "+00:00"))
        key = observed.date().isoformat()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _latest_complete_night(now_utc: datetime, timezone_name: str) -> date:
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("automatic acquisition clock must be timezone-aware")
    local = now_utc.astimezone(ZoneInfo(timezone_name))
    days_back = 1 if local.timetz().replace(tzinfo=None) >= time(12) else 2
    return local.date() - timedelta(days=days_back)


def _request(
    root: Path,
    source_id: str,
    camera: dict[str, object],
    night: date,
) -> AcquisitionRequest:
    camera_id = str(camera["id"])
    arguments = [
        "--site", source_id,
        "--camera", camera_id,
        "--night", night.isoformat(),
        "--cadence", "30m",
        "--max-files", "10",
        "--backfill-missing",
        "--output", str(root / "raw_allsky_samples"),
    ]
    if camera.get("latitude_deg") is not None and camera.get("longitude_deg") is not None:
        arguments.extend(("--sun-below", "-12"))
    return AcquisitionRequest(source_id, camera_id, night.isoformat(), tuple(arguments))


def plan_managed_acquisition(
    repository_root: Path,
    *,
    calibrated_keys: frozenset[tuple[str, str]],
    now_utc: datetime | None = None,
) -> tuple[AcquisitionRequest, ...]:
    """Plan no more than ten nights and ten originals per night per camera."""
    root = Path(repository_root).expanduser().resolve()
    registry_path = root / "sources.json"
    if not registry_path.is_file():
        return ()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("sources.json schema_version must be 1")
    now = now_utc or datetime.now(UTC)
    manifest = root / "raw_allsky_samples/manifest.sqlite"
    requests: list[AcquisitionRequest] = []
    for source in payload.get("sources", []):
        if not source.get("automatic_acquisition"):
            continue
        source_id = str(source["id"])
        for camera in source.get("cameras", []):
            camera_id = str(camera["id"])
            key = (source_id, camera_id)
            if key in calibrated_keys:
                continue
            counts = _verified_date_counts(manifest, source_id, camera_id)
            dates = sorted(counts)
            selected: list[date] = []
            if len(dates) < 10:
                needed = 10 - len(dates)
                latest = _latest_complete_night(now, str(camera["timezone"]))
                candidates = (latest - timedelta(days=offset) for offset in range(60))
                selected = [
                    candidate
                    for candidate in candidates
                    if candidate.isoformat() not in counts
                ][:needed]
                selected.sort()
            else:
                held_out = dates[0::5]
                deficit = max(0, 20 - sum(counts[value] for value in held_out))
                for value in sorted(held_out, key=lambda item: (counts[item], item)):
                    if deficit <= 0:
                        break
                    if counts[value] < 10:
                        selected.append(date.fromisoformat(value))
                        deficit -= 10
            requests.extend(
                _request(root, source_id, camera, night) for night in selected[:10]
            )
    return tuple(requests)


def _run_downloader(repository_root: Path, arguments: Sequence[str]) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            str(repository_root / "download_samples.py"),
            *arguments,
        ],
        cwd=repository_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return completed.returncode


def acquire_managed_calibration_inputs(
    repository_root: Path,
    calibrated_keys: frozenset[tuple[str, str]],
    *,
    now_utc: datetime | None = None,
    runner: Callable[[Path, Sequence[str]], int] = _run_downloader,
) -> AcquisitionResult:
    """Execute one bounded acquisition plan without exposing CLI arguments."""
    root = Path(repository_root).expanduser().resolve()
    requests = plan_managed_acquisition(
        root, calibrated_keys=calibrated_keys, now_utc=now_utc
    )
    failures = sum(runner(root, request.arguments) != 0 for request in requests)
    return AcquisitionResult(len(requests), failures)
