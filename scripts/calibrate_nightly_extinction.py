#!/usr/bin/env python3
"""Read-only MMTO loader and sidecar nightly-extinction command."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import cache
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from allsky_download.cadence import observing_night_date
from allsky_download.registry import SourceRegistry
from scripts.nightly_extinction import (
    ADOPTED_MODEL,
    CalibrationConfig,
    ImageFit,
    NightCalibrationResult,
    StellarMeasurement,
    calibrate_night,
    correct_magnitude,
    select_reference_star_ids,
)

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
    database_path: str = ""
    manifest_path: str = ""


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
        database_path=str(Path(database).resolve()),
        manifest_path=str(Path(manifest).resolve()),
    )


def _csv_value(value: object) -> object:
    return "" if value is None else value


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _result_maps(
    results: dict[str, NightCalibrationResult],
):
    adopted_coefficients = {}
    zero_points = {}
    image_fits = {}
    star_weights = {}
    for result in results.values():
        for item in result.night_coefficients:
            if item.model == result.adopted_model:
                adopted_coefficients[
                    (item.night, item.catalogue_sha256, item.channel)
                ] = item
        for item in result.image_zero_points:
            zero_points[
                (
                    item.night,
                    item.source_sha256,
                    item.catalogue_sha256,
                    item.channel,
                )
            ] = item
        for item in result.image_fits:
            image_fits[
                (
                    item.night,
                    item.source_sha256,
                    item.catalogue_sha256,
                    item.channel,
                )
            ] = item
        for item in result.star_weights:
            star_weights[
                (item.night, item.catalogue_sha256, item.star_id, item.channel)
            ] = item
    return adopted_coefficients, zero_points, image_fits, star_weights


def _write_diagnostics(
    output: Path,
    results: dict[str, NightCalibrationResult],
    measurements: tuple[StellarMeasurement, ...],
    manifest_by_source: dict[str, ManifestEntry],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    all_reference_fits = [
        fit for result in results.values() for fit in result.image_fits
    ]
    all_coefficients = [
        item for result in results.values() for item in result.night_coefficients
    ]
    all_zero_points = [
        item for result in results.values() for item in result.image_zero_points
    ]
    all_weights = [item for result in results.values() for item in result.star_weights]
    measurement_by_key = {
        (
            row.night,
            row.source_sha256,
            row.catalogue_sha256,
            row.star_id,
            row.channel,
        ): row
        for row in measurements
    }

    figure, axes = plt.subplots(3, 3, figsize=(15, 12), constrained_layout=True)
    axes = axes.ravel()
    accepted_fits = [fit for fit in all_reference_fits if fit.accepted]
    fit_times = [
        manifest_by_source[fit.source_sha256].observed_utc
        for fit in accepted_fits
        if fit.source_sha256 in manifest_by_source
    ]
    fit_slopes = [
        fit.line.slope
        for fit in accepted_fits
        if fit.source_sha256 in manifest_by_source
    ]
    axes[0].plot(fit_times, fit_slopes, ".", alpha=0.7)
    axes[0].set(title="Per-image extinction", ylabel="k [mag / airmass]")

    accepted_zero_points = [
        item for item in all_zero_points if item.status == "accepted"
    ]
    axes[1].plot(
        [manifest_by_source[item.source_sha256].observed_utc for item in accepted_zero_points],
        [item.zero_point_magnitude for item in accepted_zero_points],
        ".",
        alpha=0.7,
    )
    axes[1].set(title="Fixed-slope image zero points", ylabel="Z [mag]")

    if fit_slopes:
        axes[2].hist(fit_slopes, bins="auto")
    axes[2].set(title="Accepted image-k distribution", xlabel="k [mag / airmass]")

    model_names = [
        ADOPTED_MODEL,
        "reference_ols",
        "bright_weighted",
        "faint_weighted",
        "full_airmass_ols",
    ]
    model_values = [
        [
            item.extinction_mag_per_airmass
            for item in all_coefficients
            if item.model == model and item.extinction_mag_per_airmass is not None
        ]
        for model in model_names
    ]
    axes[3].boxplot(model_values, tick_labels=model_names, showfliers=True)
    axes[3].tick_params(axis="x", rotation=25)
    axes[3].set(title="Reference versus sensitivities", ylabel="nightly k")

    residual_airmass: list[float] = []
    residual_values: list[float] = []
    for fit in accepted_fits:
        for star_key, residual in zip(fit.star_keys, fit.line.residuals, strict=True):
            row = measurement_by_key.get(
                (
                    fit.night,
                    fit.source_sha256,
                    fit.catalogue_sha256,
                    star_key[1],
                    fit.channel,
                )
            )
            if row is not None:
                residual_airmass.append(row.airmass)
                residual_values.append(residual)
    axes[4].plot(residual_airmass, residual_values, ".", alpha=0.15)
    axes[4].axhline(0.0, color="black", linewidth=0.8)
    axes[4].set(title="Reference residuals", xlabel="saved airmass", ylabel="residual [mag]")

    magnitude_by_star: dict[tuple[str, str], float] = {}
    for row in measurements:
        magnitude_by_star.setdefault(row.star_key, row.catalogue_magnitude)
    axes[5].plot(
        [magnitude_by_star.get((item.catalogue_sha256, item.star_id)) for item in all_weights],
        [item.residual_scatter_magnitude for item in all_weights],
        ".",
        alpha=0.5,
    )
    axes[5].set(title="Repeatability scatter", xlabel="catalogue magnitude", ylabel="scaled MAD [mag]")

    axes[6].plot(
        range(len(all_reference_fits)),
        [fit.line.sample_count for fit in all_reference_fits],
        ".",
    )
    axes[6].axhline(30, color="black", linestyle="--", linewidth=0.8)
    axes[6].set(title="Calibrator counts", xlabel="image/channel", ylabel="stars")

    adopted = [item for item in all_coefficients if item.model == ADOPTED_MODEL]
    plotted_adopted = [
        item
        for item in adopted
        if item.extinction_mag_per_airmass is not None and item.scaled_mad is not None
    ]
    axes[7].errorbar(
        range(len(plotted_adopted)),
        [item.extinction_mag_per_airmass for item in plotted_adopted],
        yerr=[item.scaled_mad for item in plotted_adopted],
        fmt=".",
    )
    axes[7].set(title="Nightly median and scaled MAD", xlabel="night/channel", ylabel="k")

    calibrated = sum(item.status == "accepted" for item in adopted)
    axes[8].axis("off")
    axes[8].text(
        0.02,
        0.95,
        f"Adopted model: {ADOPTED_MODEL}\n"
        f"Accepted night/channels: {calibrated}\n"
        f"Insufficient night/channels: {len(adopted) - calibrated}\n"
        f"Valid measurements: {len(measurements)}",
        va="top",
        family="monospace",
    )
    for axis in axes[:2]:
        axis.tick_params(axis="x", rotation=25)
    figure.savefig(output / "extinction_diagnostics.png", dpi=160)
    figure.savefig(output / "extinction_diagnostics.pdf")
    plt.close(figure)

    channels = ("R", "G", "B")
    accepted_by_band_night_catalogue: dict[
        tuple[str, str, str], list[ImageFit]
    ] = defaultdict(list)
    for fit in accepted_fits:
        if fit.channel in channels and fit.source_sha256 in manifest_by_source:
            accepted_by_band_night_catalogue[
                (fit.channel, fit.night, fit.catalogue_sha256)
            ].append(fit)
    nights = sorted(
        {night for _, night, _ in accepted_by_band_night_catalogue}
    )
    catalogues = sorted(
        {catalogue for _, _, catalogue in accepted_by_band_night_catalogue}
    )
    colour_map = plt.get_cmap("turbo", max(len(nights), 1))
    colours = {night: colour_map(index) for index, night in enumerate(nights)}
    adopted_by_band_night = {
        (item.channel, item.night, item.catalogue_sha256): item
        for item in adopted
        if item.status == "accepted"
        and item.extinction_mag_per_airmass is not None
    }

    band_figure, band_axes = plt.subplots(2, 3, figsize=(18, 10))
    for column, channel in enumerate(channels):
        time_axis = band_axes[0, column]
        histogram_axis = band_axes[1, column]
        band_slopes: list[float] = []
        for night in nights:
            colour = colours[night]
            night_slopes: list[float] = []
            for catalogue_sha256 in catalogues:
                fits = sorted(
                    accepted_by_band_night_catalogue.get(
                        (channel, night, catalogue_sha256), ()
                    ),
                    key=lambda fit: manifest_by_source[
                        fit.source_sha256
                    ].observed_utc,
                )
                if not fits:
                    continue
                times = [
                    manifest_by_source[fit.source_sha256].observed_utc
                    for fit in fits
                ]
                slopes = [fit.line.slope for fit in fits]
                night_slopes.extend(slopes)
                time_axis.plot(times, slopes, ".", color=colour, alpha=0.65)
                coefficient = adopted_by_band_night.get(
                    (channel, night, catalogue_sha256)
                )
                if coefficient is not None:
                    median_time = datetime.fromtimestamp(
                        sum(item.timestamp() for item in times) / len(times), tz=UTC
                    )
                    time_axis.errorbar(
                        [median_time],
                        [coefficient.extinction_mag_per_airmass],
                        yerr=[coefficient.scaled_mad or 0.0],
                        fmt="o",
                        color=colour,
                        markeredgecolor="black",
                        markeredgewidth=0.5,
                        capsize=3,
                    )
                    time_axis.hlines(
                        coefficient.extinction_mag_per_airmass,
                        times[0],
                        times[-1],
                        color=colour,
                        linewidth=1.2,
                    )
            if night_slopes:
                band_slopes.extend(night_slopes)
                histogram_axis.hist(
                    night_slopes,
                    bins="auto",
                    histtype="step",
                    color=colour,
                    linewidth=1.2,
                    label=night,
                )
        time_axis.axhline(0.0, color="0.35", linewidth=0.7)
        time_axis.set(
            title=f"{channel}: per-image k and nightly median ± scaled MAD",
            ylabel="k [mag / airmass]",
        )
        time_axis.tick_params(axis="x", rotation=30)
        histogram_axis.set(
            title=f"{channel}: per-night image-k histograms",
            xlabel="k [mag / airmass]",
            ylabel="images",
        )
        if band_slopes:
            histogram_axis.axvline(
                sorted(band_slopes)[len(band_slopes) // 2],
                color="black",
                linestyle="--",
                linewidth=0.8,
                label="all-image median" if column == 2 else None,
            )
    legend_entries: dict[str, object] = {}
    for axis in band_axes[1]:
        handles, labels = axis.get_legend_handles_labels()
        legend_entries.update(zip(labels, handles, strict=True))
    if legend_entries:
        band_figure.legend(
            legend_entries.values(),
            legend_entries.keys(),
            loc="lower center",
            ncol=min(7, len(legend_entries)),
            fontsize="small",
        )
    band_figure.suptitle(
        "MMTO accepted reference-star extinction by band and observing night\n"
        "dots: per-image Theil–Sen; circles/error bars: nightly median ± scaled MAD"
    )
    band_figure.tight_layout(rect=(0.0, 0.10, 1.0, 0.94))
    band_figure.savefig(output / "extinction_by_band_and_night.png", dpi=160)
    band_figure.savefig(output / "extinction_by_band_and_night.pdf")
    plt.close(band_figure)


def write_calibration_outputs(
    data: LoadedCalibrationData,
    output: Path,
    config: CalibrationConfig,
) -> dict[str, object]:
    """Write a complete immutable calibration sidecar without touching the DB."""

    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    by_night: dict[str, list[StellarMeasurement]] = defaultdict(list)
    for row in data.measurements:
        by_night[row.night].append(row)
    results = {
        night: calibrate_night(rows, config)
        for night, rows in sorted(by_night.items())
    }
    adopted_coefficients, zero_points, image_fits, star_weights = _result_maps(
        results
    )
    manifest_by_source = {
        entry.source_sha256: entry for entry in data.manifest_entries
    }

    fit_rows: list[dict[str, object]] = []
    for result in results.values():
        for fit in (*result.image_fits, *result.sensitivity_image_fits):
            entry = manifest_by_source.get(fit.source_sha256)
            fit_rows.append(
                {
                    "night": fit.night,
                    "channel": fit.channel,
                    "observed_utc": entry.observed_utc.isoformat() if entry else "",
                    "source_sha256": fit.source_sha256,
                    "catalogue_sha256": fit.catalogue_sha256,
                    "model": fit.model,
                    "status": fit.status,
                    "accepted": fit.accepted,
                    "intercept_magnitude": fit.line.intercept,
                    "extinction_mag_per_airmass": fit.line.slope,
                    "intercept_uncertainty_magnitude": fit.line.intercept_uncertainty,
                    "extinction_uncertainty_mag_per_airmass": fit.line.slope_uncertainty,
                    "residual_rms_magnitude": fit.line.rms,
                    "star_count": fit.line.sample_count,
                    "airmass_min": fit.line.airmass_min,
                    "airmass_max": fit.line.airmass_max,
                    "airmass_span": fit.line.airmass_span,
                }
            )
    fit_rows.sort(
        key=lambda row: (
            row["night"], row["channel"], row["observed_utc"],
            row["source_sha256"], row["model"],
        )
    )
    _write_csv(
        output / "image_extinction_fits.csv",
        (
            "night", "channel", "observed_utc", "source_sha256",
            "catalogue_sha256", "model", "status", "accepted",
            "intercept_magnitude", "extinction_mag_per_airmass",
            "intercept_uncertainty_magnitude",
            "extinction_uncertainty_mag_per_airmass", "residual_rms_magnitude",
            "star_count", "airmass_min", "airmass_max", "airmass_span",
        ),
        fit_rows,
    )

    coefficient_rows = [
        {
            "night": item.night,
            "channel": item.channel,
            "catalogue_sha256": item.catalogue_sha256,
            "model": item.model,
            "status": item.status,
            "extinction_mag_per_airmass": item.extinction_mag_per_airmass,
            "scaled_mad_mag_per_airmass": item.scaled_mad,
            "minimum_mag_per_airmass": item.minimum,
            "maximum_mag_per_airmass": item.maximum,
            "accepted_image_count": item.accepted_image_count,
        }
        for result in results.values()
        for item in result.night_coefficients
    ]
    coefficient_rows.sort(
        key=lambda row: (row["night"], row["channel"], row["model"])
    )
    _write_csv(
        output / "nightly_extinction_coefficients.csv",
        (
            "night", "channel", "catalogue_sha256", "model", "status",
            "extinction_mag_per_airmass", "scaled_mad_mag_per_airmass",
            "minimum_mag_per_airmass", "maximum_mag_per_airmass",
            "accepted_image_count",
        ),
        coefficient_rows,
    )

    zero_rows: list[dict[str, object]] = []
    for result in results.values():
        for item in result.image_zero_points:
            entry = manifest_by_source.get(item.source_sha256)
            zero_rows.append(
                {
                    "night": item.night,
                    "channel": item.channel,
                    "observed_utc": entry.observed_utc.isoformat() if entry else "",
                    "source_sha256": item.source_sha256,
                    "catalogue_sha256": item.catalogue_sha256,
                    "model": item.model,
                    "status": item.status,
                    "zero_point_magnitude": item.zero_point_magnitude,
                    "uncertainty_magnitude": item.uncertainty_magnitude,
                    "rms_magnitude": item.rms_magnitude,
                    "star_count": item.sample_count,
                    "extinction_mag_per_airmass": item.extinction_mag_per_airmass,
                }
            )
    zero_rows.sort(
        key=lambda row: (
            row["night"], row["channel"], row["observed_utc"], row["source_sha256"]
        )
    )
    _write_csv(
        output / "image_zero_points.csv",
        (
            "night", "channel", "observed_utc", "source_sha256",
            "catalogue_sha256", "model", "status", "zero_point_magnitude",
            "uncertainty_magnitude", "rms_magnitude", "star_count",
            "extinction_mag_per_airmass",
        ),
        zero_rows,
    )

    measurements_by_key = {
        (
            row.source_sha256,
            row.catalogue_sha256,
            row.star_id,
            row.channel,
        ): row
        for row in data.measurements
    }
    reference_ids_by_group: dict[tuple[str, str, str], frozenset[tuple[str, str]]] = {}
    group_rows: dict[tuple[str, str, str], list[StellarMeasurement]] = defaultdict(list)
    for row in data.measurements:
        group_rows[(row.night, row.catalogue_sha256, row.channel)].append(row)
    for key, rows in group_rows.items():
        reference_ids_by_group[key] = select_reference_star_ids(rows, config)

    audit_output: list[dict[str, object]] = []
    for audit in data.audit_rows:
        entry = manifest_by_source.get(audit.source_sha256)
        measurement = measurements_by_key.get(
            (
                audit.source_sha256,
                audit.catalogue_sha256,
                audit.star_id,
                audit.channel,
            )
        )
        reference_ids = reference_ids_by_group.get(
            (audit.night, audit.catalogue_sha256, audit.channel), frozenset()
        )
        star_key = (audit.catalogue_sha256, audit.star_id)
        fit_reasons: list[str] = []
        if audit.included and measurement is not None:
            if measurement.catalogue_magnitude >= config.max_catalogue_magnitude:
                fit_reasons.append("catalogue_magnitude_not_bright")
            elif star_key not in reference_ids:
                fit_reasons.append("insufficient_star_observations")
            if measurement.airmass > config.max_reference_airmass:
                fit_reasons.append("airmass_above_reference_limit")
        else:
            fit_reasons.extend(audit.exclusion_reasons)
        fit = image_fits.get(
            (
                audit.night,
                audit.source_sha256,
                audit.catalogue_sha256,
                audit.channel,
            )
        )
        included_in_fit = bool(
            fit is not None
            and fit.accepted
            and star_key in fit.star_keys
            and not fit_reasons
        )
        residual = None
        if included_in_fit and fit is not None:
            residual = fit.line.residuals[fit.star_keys.index(star_key)]
        weight = star_weights.get(
            (audit.night, audit.catalogue_sha256, audit.star_id, audit.channel)
        )
        audit_output.append(
            {
                "run_id": audit.run_id,
                "night": audit.night,
                "channel": audit.channel,
                "observed_utc": entry.observed_utc.isoformat() if entry else "",
                "source_sha256": audit.source_sha256,
                "catalogue_sha256": audit.catalogue_sha256,
                "detection_id": audit.detection_id,
                "star_id": audit.star_id,
                "catalogue_magnitude": audit.catalogue_magnitude,
                "count_rate_adu_per_s": audit.count_rate_adu_per_s,
                "machine_magnitude": measurement.machine_magnitude if measurement else None,
                "airmass": audit.airmass,
                "saturated": audit.saturated,
                "measurement_method": audit.measurement_method,
                "loader_included": audit.included,
                "loader_exclusion_reasons": ";".join(audit.exclusion_reasons),
                "reference_star": star_key in reference_ids,
                "included_in_adopted_fit": included_in_fit,
                "fit_exclusion_reasons": ";".join(fit_reasons),
                "residual_magnitude": residual,
                "repeatability_weight": weight.weight if weight else None,
            }
        )
    audit_output.sort(
        key=lambda row: (
            row["night"], row["channel"], row["observed_utc"],
            row["source_sha256"], row["star_id"], row["run_id"],
        )
    )
    _write_csv(
        output / "calibration_star_measurements.csv",
        (
            "run_id", "night", "channel", "observed_utc", "source_sha256",
            "catalogue_sha256", "detection_id", "star_id",
            "catalogue_magnitude", "count_rate_adu_per_s", "machine_magnitude",
            "airmass", "saturated", "measurement_method", "loader_included",
            "loader_exclusion_reasons", "reference_star",
            "included_in_adopted_fit", "fit_exclusion_reasons",
            "residual_magnitude", "repeatability_weight",
        ),
        audit_output,
    )

    corrected_rows: list[dict[str, object]] = []
    for row in data.measurements:
        coefficient = adopted_coefficients.get(
            (row.night, row.catalogue_sha256, row.channel)
        )
        zero_point = zero_points.get(
            (row.night, row.source_sha256, row.catalogue_sha256, row.channel)
        )
        corrected = None
        if coefficient is None or coefficient.extinction_mag_per_airmass is None:
            status = "missing_nightly_extinction"
        elif zero_point is None or zero_point.zero_point_magnitude is None:
            status = zero_point.status if zero_point is not None else "missing_image_zero_point"
        else:
            status = "accepted"
            corrected = correct_magnitude(
                row.machine_magnitude,
                zero_point.zero_point_magnitude,
                coefficient.extinction_mag_per_airmass,
                row.airmass,
            )
        corrected_rows.append(
            {
                "night": row.night,
                "channel": row.channel,
                "observed_utc": row.observed_utc,
                "source_sha256": row.source_sha256,
                "catalogue_sha256": row.catalogue_sha256,
                "star_id": row.star_id,
                "catalogue_magnitude": row.catalogue_magnitude,
                "count_rate_adu_per_s": row.count_rate_adu_per_s,
                "machine_magnitude": row.machine_magnitude,
                "airmass": row.airmass,
                "extinction_mag_per_airmass": (
                    coefficient.extinction_mag_per_airmass if coefficient else None
                ),
                "nightly_scaled_mad_mag_per_airmass": (
                    coefficient.scaled_mad if coefficient else None
                ),
                "zero_point_magnitude": (
                    zero_point.zero_point_magnitude if zero_point else None
                ),
                "zero_point_uncertainty_magnitude": (
                    zero_point.uncertainty_magnitude if zero_point else None
                ),
                "corrected_magnitude": corrected,
                "status": status,
            }
        )
    corrected_rows.sort(
        key=lambda row: (
            row["night"], row["channel"], row["observed_utc"],
            row["source_sha256"], row["star_id"],
        )
    )
    _write_csv(
        output / "corrected_stellar_photometry.csv",
        (
            "night", "channel", "observed_utc", "source_sha256",
            "catalogue_sha256", "star_id", "catalogue_magnitude",
            "count_rate_adu_per_s", "machine_magnitude", "airmass",
            "extinction_mag_per_airmass", "nightly_scaled_mad_mag_per_airmass",
            "zero_point_magnitude", "zero_point_uncertainty_magnitude",
            "corrected_magnitude", "status",
        ),
        corrected_rows,
    )

    _write_diagnostics(output, results, data.measurements, manifest_by_source)
    adopted = list(adopted_coefficients.values())
    summary: dict[str, object] = {
        "calibrated_nights": sum(item.status == "accepted" for item in adopted),
        "insufficient_nights": sum(item.status != "accepted" for item in adopted),
        "valid_measurements": len(data.measurements),
        "audit_rows": len(data.audit_rows),
        "output": str(output.resolve()),
    }
    manifest_payload = {
        "schema_version": 2,
        "created_utc": datetime.now(UTC).isoformat(),
        "adopted_model": ADOPTED_MODEL,
        "configuration": asdict(config),
        "formulae": {
            "machine_magnitude": "m_machine = -2.5 log10(count_rate_adu_per_s)",
            "image_fit": "m_machine - m_catalogue = Z_image + k_image X",
            "image_fit_estimator": "Theil-Sen slope with joint-median intercept",
            "nightly_coefficient": "k_night = median_i(k_image)",
            "fixed_slope_zero_point": "Z_fixed = median_s(delta_m - k_night X)",
            "corrected_magnitude": "m_corrected = m_machine - Z_fixed - k_night X",
        },
        "selected_run_ids": list(data.selected_run_ids),
        "database": data.database_path,
        "manifest": data.manifest_path,
        "catalogue_sha256": sorted(
            {row.catalogue_sha256 for row in data.measurements}
        ),
        "summary": summary,
    }
    (output / "calibration_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def default_database() -> Path:
    destination = os.environ.get("WFS_RESULTS_DIR")
    if not destination:
        config_root = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        )
        host_config = (
            config_root
            / "wide-field-solver"
            / ("results-dir." + socket.gethostname())
        )
        if host_config.is_file():
            destination = host_config.read_text(encoding="utf-8").splitlines()[0]
    return Path(destination or ROOT / "results") / "stars.sqlite"


def default_manifest(database: Path) -> Path | None:
    database = database.resolve()
    candidates = [
        database.parent / "manifest.sqlite",
        database.parent / "manifest.csv",
        database.parent.parent / "raw_allsky_samples" / "manifest.sqlite",
    ]
    if database.is_relative_to(ROOT):
        candidates.insert(0, ROOT / "raw_allsky_samples" / "manifest.sqlite")
    return next((path for path in candidates if path.is_file()), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="new sidecar directory; defaults to a timestamp beside the database",
    )
    arguments = parser.parse_args(argv)
    try:
        database = (arguments.database or default_database()).expanduser().resolve()
        manifest = arguments.manifest
        if manifest is None:
            manifest = default_manifest(database)
        if manifest is None:
            raise ValueError(
                "supply --manifest PATH; no verified MMTO SQLite/CSV manifest was found"
            )
        manifest = manifest.expanduser().resolve()
        output = arguments.output
        if output is None:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            output = database.parent / "extinction-calibration" / stamp
        output = output.expanduser().resolve()
        config = CalibrationConfig()
        data = load_mmto_calibration_data(database, manifest)
        summary = write_calibration_outputs(data, output, config)
    except (FileExistsError, OSError, sqlite3.Error, ValueError) as error:
        parser.exit(2, f"Error: {error}\n")

    print(f"Database (read-only): {database}")
    print(f"MMTO manifest: {manifest}")
    print(
        "Reference defaults: catalogue magnitude < "
        f"{config.max_catalogue_magnitude}; observations/star >= "
        f"{config.min_observations_per_star}; stars/image >= "
        f"{config.min_stars_per_image}; images/night >= "
        f"{config.min_images_per_night}"
    )
    print(
        "Calibrated night/channels: "
        f"{summary['calibrated_nights']}; insufficient: "
        f"{summary['insufficient_nights']}"
    )
    print(f"Valid stellar channel measurements: {summary['valid_measurements']}")
    print(f"Audit rows: {summary['audit_rows']}")
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
