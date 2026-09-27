#!/usr/bin/env python3
"""Read-only MMTO loader and sidecar nightly-extinction command."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import urlparse

from allsky_download.cadence import observing_night_date
from allsky_download.registry import SourceRegistry
from scripts.nightly_extinction import StellarMeasurement


ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


@dataclass(frozen=True)
class ManifestEntry:
    source_sha256: str
    observed_utc: datetime
    night: str
    source_url: str
    local_path: str | None


@dataclass(frozen=True)
class CalibrationAuditRow:
    run_id: str
    source_sha256: str
    catalogue_sha256: str
    night: str
    star_id: str
    detection_id: str
    channel: str
    catalogue_magnitude: float | None
    count_rate_adu_per_s: float | None
    airmass: float | None
    saturated: bool | None
    measurement_method: str
    included: bool
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class LoadedCalibrationData:
    measurements: tuple[StellarMeasurement, ...]
    audit_rows: tuple[CalibrationAuditRow, ...]
    selected_run_ids: tuple[str, ...]
    manifest_entries: tuple[ManifestEntry, ...]


def _utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Observation time must include a timezone: {value}")
    return parsed.astimezone(UTC)


@cache
def _mmto_site():
    registry = SourceRegistry.from_json(ROOT / "sources.json")
    return registry.get_adapter("mmto").sites("mmto-skycam")[0]


def _add_manifest_entry(
    entries: dict[str, ManifestEntry],
    *,
    digest: str,
    observed_text: str,
    source_url: str,
    local_path: str | None,
) -> None:
    observed_utc = _utc_time(observed_text)
    entry = ManifestEntry(
        source_sha256=digest,
        observed_utc=observed_utc,
        night=observing_night_date(_mmto_site(), observed_utc).isoformat(),
        source_url=source_url,
        local_path=local_path,
    )
    previous = entries.get(digest)
    if previous is not None and previous.observed_utc != observed_utc:
        raise ValueError(f"Conflicting manifest UTC times for image hash {digest}")
    entries[digest] = entry


def _read_sqlite_manifest(path: Path) -> dict[str, ManifestEntry]:
    entries: dict[str, ManifestEntry] = {}
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as database:
        database.execute("PRAGMA query_only=ON")
        rows = database.execute(
            """
            SELECT remote_url, observed_utc, local_path, sha256
            FROM downloads
            WHERE source_id = 'mmto'
              AND camera_id = 'mmto-skycam'
              AND download_status = 'downloaded'
              AND validation_status = 'verified'
              AND sha256 IS NOT NULL
              AND sha256 != ''
            ORDER BY remote_url
            """
        ).fetchall()
    for source_url, observed_text, local_path, digest in rows:
        _add_manifest_entry(
            entries,
            digest=str(digest),
            observed_text=str(observed_text),
            source_url=str(source_url),
            local_path=str(local_path) if local_path is not None else None,
        )
    return entries


def _read_csv_manifest(path: Path) -> dict[str, ManifestEntry]:
    entries: dict[str, ManifestEntry] = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            source_url = row.get("source_url", "")
            parsed_url = urlparse(source_url)
            if (
                parsed_url.hostname != "skycam.mmto.arizona.edu"
                or not parsed_url.path.startswith("/skycam/archive/")
            ):
                continue
            digest = row.get("sha256", "")
            observed_text = row.get("utc_mid", "")
            if not digest or not observed_text:
                continue
            _add_manifest_entry(
                entries,
                digest=digest,
                observed_text=observed_text,
                source_url=source_url,
                local_path=row.get("local_path") or None,
            )
    return entries


def read_mmto_manifest(path: Path) -> dict[str, ManifestEntry]:
    """Read verified MMTO source hashes and archive exposure midpoints."""

    path = Path(path)
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        entries = _read_sqlite_manifest(path)
    else:
        entries = _read_csv_manifest(path)
    if not entries:
        raise ValueError(
            "Manifest contains no verified MMTO skycam image hashes with UTC times"
        )
    return entries


def _finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _audit_run(
    run: tuple[object, ...],
    reason: str,
    manifest_entries: dict[str, ManifestEntry],
) -> CalibrationAuditRow:
    run_id, _, _, source_sha256, catalogue_sha256, _ = run
    digest = str(source_sha256 or "")
    entry = manifest_entries.get(digest)
    return CalibrationAuditRow(
        run_id=str(run_id),
        source_sha256=digest,
        catalogue_sha256=str(catalogue_sha256 or ""),
        night=entry.night if entry is not None else "",
        star_id="",
        detection_id="",
        channel="",
        catalogue_magnitude=None,
        count_rate_adu_per_s=None,
        airmass=None,
        saturated=None,
        measurement_method="",
        included=False,
        exclusion_reasons=(reason,),
    )


def _boolean(value: object) -> bool | None:
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _audit_measurement(
    *,
    run_id: str,
    entry: ManifestEntry,
    catalogue_sha256: str,
    star_id: str,
    detection_id: str,
    channel: str,
    catalogue_magnitude: float | None,
    count_rate: float | None,
    airmass: float | None,
    saturated: bool | None,
    measurement_method: str,
    reasons: tuple[str, ...],
) -> CalibrationAuditRow:
    return CalibrationAuditRow(
        run_id=run_id,
        source_sha256=entry.source_sha256,
        catalogue_sha256=catalogue_sha256,
        night=entry.night,
        star_id=star_id,
        detection_id=detection_id,
        channel=channel,
        catalogue_magnitude=catalogue_magnitude,
        count_rate_adu_per_s=count_rate,
        airmass=airmass,
        saturated=saturated,
        measurement_method=measurement_method,
        included=not reasons,
        exclusion_reasons=reasons,
    )


def load_mmto_calibration_data(
    database: Path,
    manifest: Path,
) -> LoadedCalibrationData:
    """Materialize one read-only database snapshot for MMTO calibration."""

    manifest_entries = read_mmto_manifest(manifest)
    audit_rows: list[CalibrationAuditRow] = []
    measurements: list[StellarMeasurement] = []
    selected_run_ids: list[str] = []
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        runs = connection.execute(
            """
            SELECT run_id, recorded_at_utc, source_path, source_sha256,
                   catalogue_sha256, exit_code
            FROM runs
            ORDER BY recorded_at_utc, run_id
            """
        ).fetchall()
        latest: dict[tuple[str, str], tuple[object, ...]] = {}
        for run in runs:
            source_sha256 = str(run[3] or "")
            catalogue_sha256 = str(run[4] or "")
            if int(run[5]) != 0:
                audit_rows.append(_audit_run(run, "failed_run", manifest_entries))
                continue
            if source_sha256 not in manifest_entries:
                audit_rows.append(
                    _audit_run(run, "missing_manifest_hash", manifest_entries)
                )
                continue
            if not catalogue_sha256:
                audit_rows.append(
                    _audit_run(run, "missing_catalogue_sha256", manifest_entries)
                )
                continue
            key = source_sha256, catalogue_sha256
            previous = latest.get(key)
            if previous is not None:
                audit_rows.append(
                    _audit_run(
                        previous, "superseded_successful_run", manifest_entries
                    )
                )
            latest[key] = run

        for key in sorted(latest):
            run = latest[key]
            run_id = str(run[0])
            source_sha256, catalogue_sha256 = key
            entry = manifest_entries[source_sha256]
            selected_run_ids.append(run_id)
            rows = connection.execute(
                """
                SELECT row_number, star_id, detection_id, values_json
                FROM measurements
                WHERE run_id = ? AND product = 'stellar_photometry.csv'
                ORDER BY row_number
                """,
                (run_id,),
            ).fetchall()
            seen_stars: set[str] = set()
            for _, raw_star_id, raw_detection_id, values_json in rows:
                star_id = str(raw_star_id or "")
                detection_id = str(raw_detection_id or "")
                try:
                    values = json.loads(values_json)
                    if not isinstance(values, dict):
                        raise ValueError("measurement JSON is not an object")
                except (json.JSONDecodeError, TypeError, ValueError):
                    audit_rows.append(
                        _audit_measurement(
                            run_id=run_id,
                            entry=entry,
                            catalogue_sha256=catalogue_sha256,
                            star_id=star_id,
                            detection_id=detection_id,
                            channel="",
                            catalogue_magnitude=None,
                            count_rate=None,
                            airmass=None,
                            saturated=None,
                            measurement_method="",
                            reasons=("malformed_values_json",),
                        )
                    )
                    continue
                row_reasons: list[str] = []
                if not star_id:
                    row_reasons.append("missing_star_id")
                elif star_id in seen_stars:
                    row_reasons.append("duplicate_star_measurement")
                seen_stars.add(star_id)
                catalogue_magnitude = _finite(values.get("catalogue_magnitude"))
                airmass = _finite(values.get("airmass"))
                if catalogue_magnitude is None:
                    row_reasons.append("invalid_catalogue_magnitude")
                if airmass is None or airmass <= 0.0:
                    row_reasons.append("invalid_airmass")
                saturation_known = _boolean(values.get("saturation_known"))
                if saturation_known is not True:
                    row_reasons.append("saturation_unknown")

                for channel in ("R", "G", "B"):
                    reasons = list(row_reasons)
                    count_rate = _finite(
                        values.get(f"{channel}_count_rate_adu_per_s")
                    )
                    if count_rate is None or count_rate <= 0.0:
                        reasons.append("invalid_count_rate")
                    saturated = _boolean(values.get(f"{channel}_saturated"))
                    if saturated is None:
                        reasons.append("channel_saturation_unknown")
                    elif saturated:
                        reasons.append("channel_saturated")
                    saved_method = str(
                        values.get(f"{channel}_measurement_method", "")
                    )
                    if saved_method == "aperture":
                        measurement_method = "ordinary_aperture"
                    else:
                        measurement_method = saved_method
                        reasons.append("not_ordinary_aperture")
                    reason_tuple = tuple(dict.fromkeys(reasons))
                    audit_rows.append(
                        _audit_measurement(
                            run_id=run_id,
                            entry=entry,
                            catalogue_sha256=catalogue_sha256,
                            star_id=star_id,
                            detection_id=detection_id,
                            channel=channel,
                            catalogue_magnitude=catalogue_magnitude,
                            count_rate=count_rate,
                            airmass=airmass,
                            saturated=saturated,
                            measurement_method=measurement_method,
                            reasons=reason_tuple,
                        )
                    )
                    if reason_tuple:
                        continue
                    uncertainty = _finite(
                        values.get(f"{channel}_count_rate_uncertainty_adu_per_s")
                    )
                    if uncertainty is not None and uncertainty <= 0.0:
                        uncertainty = None
                    measurements.append(
                        StellarMeasurement(
                            night=entry.night,
                            source_sha256=source_sha256,
                            catalogue_sha256=catalogue_sha256,
                            star_id=star_id,
                            channel=channel,
                            catalogue_magnitude=catalogue_magnitude,
                            count_rate_adu_per_s=count_rate,
                            count_rate_uncertainty_adu_per_s=uncertainty,
                            airmass=airmass,
                            saturated=False,
                            measurement_method="ordinary_aperture",
                            observed_utc=entry.observed_utc.isoformat(),
                        )
                    )
        connection.rollback()
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()

    measurements.sort(
        key=lambda row: (
            row.night,
            row.observed_utc,
            row.catalogue_sha256,
            row.star_id,
            row.channel,
        )
    )
    return LoadedCalibrationData(
        measurements=tuple(measurements),
        audit_rows=tuple(audit_rows),
        selected_run_ids=tuple(selected_run_ids),
        manifest_entries=tuple(
            manifest_entries[key] for key in sorted(manifest_entries)
        ),
    )
