#!/usr/bin/env python3
"""Fit and plot nightly planet-only empirical airmass corrections."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import uuid

from scipy.stats import theilslopes


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.plot_planet_photometry import (
    PLANET_COLOURS,
    _camera_marker_map,
    _distance_corrected_magnitude,
    _horizons_distance_lookup,
    _hours_past_local_noon,
    _mmto_observing_night,
    load_mmto_manifest_planet_measurements,
)

PRODUCER_VERSION = "0.16.0"


FIT_FIELDS = (
    "night", "channel", "planet", "camera_label", "status",
    "input_measurement_count", "measurement_count",
    "invalid_measurement_count", "measurements_above_maximum_airmass",
    "airmass_min", "airmass_max",
    "airmass_span",
    "planet_empirical_extinction_coefficient_mag_per_airmass",
    "planet_empirical_extinction_intercept_magnitude",
    "planet_empirical_extinction_coefficient_low_95",
    "planet_empirical_extinction_coefficient_high_95",
    "planet_empirical_extinction_reference_airmass",
)
MEASUREMENT_FIELDS = (
    "night", "channel", "planet", "camera_label", "observation_time_utc",
    "hours_past_local_noon",
    "source_path", "source_sha256", "catalogue_sha256", "run_id",
    "recorded_at_utc", "detection_id", "source_class",
    "camera_provenance", "identity_status", "photometry_usable",
    "exclusion_reason", "exposure_seconds", "exposure_source",
    "saturation_known", "channel_saturated", "measurement_method",
    "planet_measured_altitude_deg", "planet_airmass",
    "count_rate_adu_per_s", "machine_magnitude",
    "stellar_only_fit_rms_arcmin", "metadata_association_status",
    "metadata_association_time_utc", "metadata_association_epoch_tdb",
    "metadata_association_epoch_source", "metadata_association_method",
    "metadata_association_jd_tdb", "association_gate_arcmin",
    "association_positional_sigma_arcmin", "association_measured_x_px",
    "association_measured_y_px", "association_predicted_x_px",
    "association_predicted_y_px", "association_separation_px",
    "association_separation_arcmin", "association_catalogue_residual_px",
    "association_catalogue_residual_arcmin",
    "sun_planet_distance_au", "earth_planet_distance_au",
    "distance_correction_mag", "distance_corrected_magnitude",
    "machine_magnitude_uncertainty",
    "distance_ephemeris_source", "planet_only_input_status",
    "planet_empirical_extinction_coefficient_mag_per_airmass",
    "planet_empirical_extinction_reference_airmass",
    "planet_empirical_extinction_corrected_distance_magnitude",
    "planet_only_airmass_correction_status",
)


def prepare_planet_measurements(rows, distance_lookup, *, uncertainty_lookup):
    """Prepare metadata-time planet rows without consulting stellar fits."""
    prepared = []
    audited = []
    for original in rows:
        row = dict(original)
        row["planet_only_input_status"] = ""
        if row.get("identity_status") != "metadata_time_match":
            row["planet_only_input_status"] = "non_metadata_time_identity"
        elif not row.get("photometry_usable"):
            row["planet_only_input_status"] = (
                row.get("exclusion_reason") or "source_photometry_unusable"
            )
        else:
            night = _mmto_observing_night(row.get("observation_time_utc"))
            airmass = _finite(row.get("planet_airmass"))
            magnitude = _finite(row.get("machine_magnitude"))
            if night is None:
                row["planet_only_input_status"] = "invalid_observation_time"
            elif airmass is None or airmass <= 0.0 or magnitude is None:
                row["planet_only_input_status"] = "invalid_planet_measurement"
            else:
                distance = distance_lookup.get((
                    row.get("planet"), row.get("observation_time_utc")
                ))
                if distance is None:
                    row["planet_only_input_status"] = "distance_ephemeris_unavailable"
                else:
                    row.update(distance)
                    corrected = _distance_corrected_magnitude(
                        magnitude,
                        row.get("sun_planet_distance_au"),
                        row.get("earth_planet_distance_au"),
                    )
                    if corrected is None:
                        row["planet_only_input_status"] = "distance_correction_failed"
                    else:
                        row.update(uncertainty_lookup.get(
                            (row.get("run_id"), str(row.get("detection_id"))),
                            {},
                        ))
                        row.update({
                            "night": night,
                            "hours_past_local_noon": _hours_past_local_noon(
                                row.get("observation_time_utc"), night
                            ),
                            "planet_airmass": airmass,
                            "machine_magnitude": magnitude,
                            "distance_correction_mag": magnitude - corrected,
                            "distance_corrected_magnitude": corrected,
                            "planet_only_input_status": "ready",
                        })
                        prepared.append(row)
        audited.append(row)
    return prepared, audited


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


PLANET_EMPIRICAL_EXTINCTION_METHOD = "planet_only_theil_sen"
PLANET_EMPIRICAL_EXTINCTION_FORMULA = (
    "m_planet_corrected = m_distance - "
    "planet_empirical_extinction_coefficient_mag_per_airmass * (airmass - 1)"
)


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_sqlite_database(source, destination):
    """Create one standalone SQLite snapshot, including committed WAL state."""
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"manifest snapshot already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.as_uri() + "?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_connection:
        with sqlite3.connect(destination) as snapshot_connection:
            source_connection.backup(snapshot_connection)
    return _file_sha256(destination)


def _create_planet_empirical_extinction_schema(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS planet_empirical_extinction_generations (
            generation_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id TEXT NOT NULL UNIQUE,
            generated_at_utc TEXT NOT NULL,
            producer_version TEXT NOT NULL,
            method TEXT NOT NULL,
            formula TEXT NOT NULL,
            manifest_path TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            output_path TEXT NOT NULL,
            minimum_measurements INTEGER NOT NULL,
            minimum_airmass_span REAL NOT NULL,
            maximum_airmass REAL NOT NULL,
            reference_airmass REAL NOT NULL,
            source_audits_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS planet_nightly_empirical_extinction_coefficients (
            generation_id TEXT NOT NULL REFERENCES
                planet_empirical_extinction_generations(generation_id),
            night TEXT NOT NULL,
            channel TEXT NOT NULL CHECK(channel IN ('R','G','B')),
            planet TEXT NOT NULL,
            camera_label TEXT NOT NULL,
            status TEXT NOT NULL,
            input_measurement_count INTEGER NOT NULL,
            measurement_count INTEGER NOT NULL,
            invalid_measurement_count INTEGER NOT NULL,
            measurements_above_maximum_airmass INTEGER NOT NULL,
            airmass_min REAL,
            airmass_max REAL,
            airmass_span REAL NOT NULL,
            planet_empirical_extinction_coefficient_mag_per_airmass REAL,
            planet_empirical_extinction_intercept_magnitude REAL,
            planet_empirical_extinction_coefficient_low_95 REAL,
            planet_empirical_extinction_coefficient_high_95 REAL,
            planet_empirical_extinction_reference_airmass REAL NOT NULL,
            PRIMARY KEY (
                generation_id, night, channel, planet, camera_label
            )
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS planet_empirical_extinction_lookup
        ON planet_nightly_empirical_extinction_coefficients (
            night, channel, planet, camera_label, generation_id
        )
        """
    )
    connection.execute(
        """
        CREATE VIEW IF NOT EXISTS
            latest_planet_nightly_empirical_extinction_coefficients AS
        SELECT c.*, g.generated_at_utc, g.producer_version, g.method,
               g.formula, g.manifest_path, g.manifest_sha256, g.output_path
        FROM planet_nightly_empirical_extinction_coefficients AS c
        JOIN planet_empirical_extinction_generations AS g
          ON g.generation_id=c.generation_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM planet_nightly_empirical_extinction_coefficients AS newer_c
            JOIN planet_empirical_extinction_generations AS newer_g
              ON newer_g.generation_id=newer_c.generation_id
            WHERE newer_c.night=c.night
              AND newer_c.channel=c.channel
              AND newer_c.planet=c.planet
              AND newer_c.camera_label=c.camera_label
              AND newer_g.generation_sequence > g.generation_sequence
        )
        """
    )
    connection.execute(
        """
        CREATE VIEW IF NOT EXISTS
            latest_accepted_planet_empirical_extinction_coefficients AS
        SELECT *
        FROM latest_planet_nightly_empirical_extinction_coefficients
        WHERE status='accepted'
          AND planet_empirical_extinction_coefficient_mag_per_airmass IS NOT NULL
        """
    )


def write_planet_empirical_extinction_generation(
    database,
    manifest,
    output,
    fits_by_channel,
    source_audits,
    *,
    producer_version,
):
    """Atomically append one auditable planet-coefficient generation."""
    database = Path(database).resolve(strict=True)
    manifest = Path(manifest).resolve(strict=True)
    generation_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(database, timeout=60) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
            ).fetchone() is None:
                raise ValueError("database is not a wide-field solver run database")
            _create_planet_empirical_extinction_schema(connection)
            connection.execute(
                """
                INSERT INTO planet_empirical_extinction_generations (
                    generation_id,generated_at_utc,producer_version,method,
                    formula,manifest_path,manifest_sha256,output_path,
                    minimum_measurements,minimum_airmass_span,maximum_airmass,
                    reference_airmass,source_audits_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    generation_id,
                    generated_at,
                    str(producer_version),
                    PLANET_EMPIRICAL_EXTINCTION_METHOD,
                    PLANET_EMPIRICAL_EXTINCTION_FORMULA,
                    str(manifest),
                    _file_sha256(manifest),
                    str(Path(output).resolve()),
                    10,
                    0.5,
                    5.0,
                    1.0,
                    json.dumps(source_audits, sort_keys=True),
                ),
            )
            for channel in "RGB":
                for fit in fits_by_channel.get(channel, []):
                    saved_channel = str(fit.get("channel") or channel)
                    if saved_channel != channel:
                        raise ValueError(
                            f"fit channel {saved_channel} is stored under {channel}"
                        )
                    coefficient = _finite(fit.get(
                        "planet_empirical_extinction_coefficient_mag_per_airmass"
                    ))
                    if fit.get("status") == "accepted" and coefficient is None:
                        raise ValueError(
                            "accepted planet empirical extinction fit lacks coefficient"
                        )
                    connection.execute(
                        """
                        INSERT INTO planet_nightly_empirical_extinction_coefficients (
                            generation_id,night,channel,planet,camera_label,status,
                            input_measurement_count,measurement_count,
                            invalid_measurement_count,
                            measurements_above_maximum_airmass,airmass_min,
                            airmass_max,airmass_span,
                            planet_empirical_extinction_coefficient_mag_per_airmass,
                            planet_empirical_extinction_intercept_magnitude,
                            planet_empirical_extinction_coefficient_low_95,
                            planet_empirical_extinction_coefficient_high_95,
                            planet_empirical_extinction_reference_airmass
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            generation_id,
                            str(fit.get("night") or ""),
                            saved_channel,
                            str(fit.get("planet") or ""),
                            str(fit.get("camera_label") or ""),
                            str(fit.get("status") or ""),
                            int(fit.get("input_measurement_count") or 0),
                            int(fit.get("measurement_count") or 0),
                            int(fit.get("invalid_measurement_count") or 0),
                            int(fit.get("measurements_above_maximum_airmass") or 0),
                            _finite(fit.get("airmass_min")),
                            _finite(fit.get("airmass_max")),
                            float(fit.get("airmass_span") or 0.0),
                            coefficient,
                            _finite(fit.get(
                                "planet_empirical_extinction_intercept_magnitude"
                            )),
                            _finite(fit.get(
                                "planet_empirical_extinction_coefficient_low_95"
                            )),
                            _finite(fit.get(
                                "planet_empirical_extinction_coefficient_high_95"
                            )),
                            float(fit.get(
                                "planet_empirical_extinction_reference_airmass"
                            ) or 1.0),
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return generation_id


def fit_planet_only_sequences(
    rows,
    *,
    min_measurements=10,
    min_airmass_span=0.5,
    maximum_airmass=5.0,
    reference_airmass=1.0,
):
    """Fit each planet/night/channel/camera using only that planet's data."""
    groups = defaultdict(list)
    for original in rows:
        row = dict(original)
        groups[(
            row.get("night"),
            row.get("channel"),
            row.get("planet"),
            row.get("camera_label"),
        )].append(row)

    corrected = []
    fits = []
    audited = []
    for (night, channel, planet, camera), group in sorted(groups.items()):
        usable = []
        invalid_count = 0
        above_maximum_count = 0
        for row in group:
            airmass = _finite(row.get("planet_airmass"))
            magnitude = _finite(row.get("distance_corrected_magnitude"))
            if airmass is None or airmass <= 0.0 or magnitude is None:
                row["planet_only_airmass_correction_status"] = "invalid_measurement"
                invalid_count += 1
            elif airmass > maximum_airmass:
                row["planet_only_airmass_correction_status"] = "airmass_above_maximum"
                above_maximum_count += 1
            else:
                row["planet_airmass"] = airmass
                row["distance_corrected_magnitude"] = magnitude
                usable.append(row)

        airmasses = [row["planet_airmass"] for row in usable]
        magnitudes = [row["distance_corrected_magnitude"] for row in usable]
        span = max(airmasses) - min(airmasses) if airmasses else 0.0
        fit = {
            "night": night,
            "channel": channel,
            "planet": planet,
            "camera_label": camera,
            "status": "accepted",
            "input_measurement_count": len(group),
            "measurement_count": len(usable),
            "invalid_measurement_count": invalid_count,
            "measurements_above_maximum_airmass": above_maximum_count,
            "airmass_min": min(airmasses) if airmasses else None,
            "airmass_max": max(airmasses) if airmasses else None,
            "airmass_span": span,
            "planet_empirical_extinction_coefficient_mag_per_airmass": None,
            "planet_empirical_extinction_intercept_magnitude": None,
            "planet_empirical_extinction_coefficient_low_95": None,
            "planet_empirical_extinction_coefficient_high_95": None,
            "planet_empirical_extinction_reference_airmass": reference_airmass,
        }
        if len(usable) < min_measurements:
            fit["status"] = "insufficient_measurements"
        elif span < min_airmass_span:
            fit["status"] = "insufficient_airmass_span"
        else:
            result = theilslopes(magnitudes, airmasses, alpha=0.95)
            fit.update({
                "planet_empirical_extinction_coefficient_mag_per_airmass": float(
                    result.slope
                ),
                "planet_empirical_extinction_intercept_magnitude": float(
                    result.intercept
                ),
                "planet_empirical_extinction_coefficient_low_95": float(
                    result.low_slope
                ),
                "planet_empirical_extinction_coefficient_high_95": float(
                    result.high_slope
                ),
            })
            for row in usable:
                row.update({
                    "planet_empirical_extinction_coefficient_mag_per_airmass": float(
                        result.slope
                    ),
                    "planet_empirical_extinction_reference_airmass": reference_airmass,
                    "planet_empirical_extinction_corrected_distance_magnitude": (
                        row["distance_corrected_magnitude"]
                        - float(result.slope)
                        * (row["planet_airmass"] - reference_airmass)
                    ),
                    "planet_only_airmass_correction_status": "available",
                })
                corrected.append(row)
        for row in usable:
            row.setdefault("planet_only_airmass_correction_status", fit["status"])
        fits.append(fit)
        audited.extend(group)
    return corrected, fits, audited


def _build_before_after_figure(rows, *, channel):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure, axes = plt.subplots(
        1, 2, figsize=(16.0, 7.5), sharex=True, sharey=True,
    )
    figure.subplots_adjust(
        left=0.065, right=0.985, bottom=0.095, top=0.885, wspace=0.03
    )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["night"], row["planet"], row["camera_label"])].append(row)
    camera_markers = _camera_marker_map(rows)
    for (_, planet, camera), points in sorted(groups.items()):
        points.sort(key=lambda row: row["planet_airmass"])
        airmass = [row["planet_airmass"] for row in points]
        before = [row["distance_corrected_magnitude"] for row in points]
        after = [
            row["planet_empirical_extinction_corrected_distance_magnitude"]
            for row in points
        ]
        colour = PLANET_COLOURS.get(planet, "#777777")
        marker = camera_markers[camera]
        for axis, magnitude in zip(axes, (before, after)):
            axis.plot(airmass, magnitude, color=colour, linewidth=1.0, alpha=0.3)
            axis.scatter(
                airmass, magnitude, s=28, color=colour, marker=marker,
                edgecolor="black", linewidth=0.3, alpha=0.8,
            )
    axes[0].set_title("Before: distance-normalized planet magnitude")
    axes[1].set_title("After: each planet's own nightly airmass slope removed")
    axes[0].set_ylabel(f"{channel} instrumental magnitude at 1 AU distances")
    for axis in axes:
        axis.set_xlabel("Planet airmass")
        axis.grid(True, alpha=0.25, linewidth=0.7)
    if rows:
        axes[0].invert_yaxis()
        planets = sorted({row["planet"] for row in rows})
        handles = [
            Line2D(
                [], [], linestyle="none", marker="o", markersize=7,
                markerfacecolor=PLANET_COLOURS.get(planet, "#777777"),
                markeredgecolor="black", label=planet,
            )
            for planet in planets
        ]
        axes[1].legend(handles=handles, title="Planet", loc="best")
    else:
        for axis in axes:
            axis.text(
                0.5, 0.5, "No planet sequences passed the fit gates",
                ha="center", va="center", transform=axis.transAxes,
            )
    figure.suptitle(
        "Nightly empirical airmass correction fitted from planet photometry only",
        y=0.965,
    )
    return figure, axes


def _build_local_noon_figure(rows, *, channel):
    """Plot final planet-only corrected magnitudes by Arizona night phase."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure, axis = plt.subplots(figsize=(15.5, 7.5))
    figure.subplots_adjust(
        left=0.075, right=0.86, bottom=0.105, top=0.90
    )
    groups = defaultdict(list)
    usable = []
    for original in rows:
        row = dict(original)
        hour = _finite(row.get("hours_past_local_noon"))
        magnitude = _finite(
            row.get("planet_empirical_extinction_corrected_distance_magnitude")
        )
        if hour is None or magnitude is None:
            continue
        row["hours_past_local_noon"] = hour
        row["planet_empirical_extinction_corrected_distance_magnitude"] = magnitude
        usable.append(row)
        groups[(row["night"], row["planet"], row["camera_label"])].append(row)
    camera_markers = _camera_marker_map(usable)
    for (_, planet, camera), points in sorted(groups.items()):
        points.sort(key=lambda row: row["hours_past_local_noon"])
        hours = [row["hours_past_local_noon"] for row in points]
        magnitudes = [
            row["planet_empirical_extinction_corrected_distance_magnitude"]
            for row in points
        ]
        colour = PLANET_COLOURS.get(planet, "#777777")
        if len(points) > 1:
            axis.plot(
                hours, magnitudes, color=colour, linewidth=1.0, alpha=0.3
            )
        axis.scatter(
            hours,
            magnitudes,
            s=30,
            color=colour,
            marker=camera_markers[camera],
            edgecolor="black",
            linewidth=0.3,
            alpha=0.8,
        )
    axis.set_title(
        "Planet-only extinction- and distance-corrected magnitude "
        "by nightly local-noon phase"
    )
    axis.set_xlabel(
        "Hours past 12:00 local Arizona time on the observing night"
    )
    axis.set_ylabel(
        f"{channel} planet-only corrected instrumental magnitude "
        "at 1 AU distances"
    )
    axis.grid(True, alpha=0.25, linewidth=0.7)
    if usable:
        axis.invert_yaxis()
        planets = sorted({row["planet"] for row in usable})
        handles = [
            Line2D(
                [], [], linestyle="none", marker="o", markersize=7,
                markerfacecolor=PLANET_COLOURS.get(planet, "#777777"),
                markeredgecolor="black", label=planet,
            )
            for planet in planets
        ]
        axis.legend(
            handles=handles,
            title="Planet",
            loc="upper left",
            bbox_to_anchor=(1.005, 1.0),
            borderaxespad=0.0,
        )
    else:
        axis.text(
            0.5, 0.5, "No planet sequences passed the fit gates",
            ha="center", va="center", transform=axis.transAxes,
        )
    return figure, axis


def write_channel_outputs(rows, output, *, channel, input_audit=None):
    """Write one channel's planet-only fits, corrected rows, audit, and plot."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    corrected, fits, audited = fit_planet_only_sequences(rows)
    for name, records, fields in (
        (
            "planet_nightly_empirical_extinction_coefficients.csv",
            fits,
            FIT_FIELDS,
        ),
        (
            "planet_only_airmass_corrected_measurements.csv",
            corrected,
            MEASUREMENT_FIELDS,
        ),
        ("planet_only_airmass_correction_audit.csv", audited, MEASUREMENT_FIELDS),
    ):
        with (output / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
    if input_audit is not None:
        with (output / "planet_only_airmass_input_audit.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.DictWriter(
                stream, fieldnames=MEASUREMENT_FIELDS, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(input_audit)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "channel": channel,
        "method": (
            "Theil-Sen fit of distance-normalized magnitude versus airmass, "
            "separately for each planet, Arizona observing night, channel, "
            "and camera. No stellar measurement or coefficient enters the fit."
        ),
        "formula": "m_corrected = m_distance - k_planet * (airmass - 1)",
        "gates": {
            "minimum_measurements": 10,
            "minimum_airmass_span": 0.5,
            "maximum_airmass": 5.0,
            "reference_airmass": 1.0,
        },
        "sequence_count": len(fits),
        "accepted_sequence_count": sum(
            row["status"] == "accepted" for row in fits
        ),
        "fit_status_counts": dict(Counter(row["status"] for row in fits)),
        "corrected_measurement_count": len(corrected),
        "input_status_counts": dict(Counter(
            row.get("planet_only_input_status", "unspecified")
            for row in (input_audit or rows)
        )),
    }
    (output / "planet_only_airmass_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    figure, _ = _build_before_after_figure(corrected, channel=channel)
    figure.savefig(output / "planet_only_airmass_before_after.pdf")
    import matplotlib.pyplot as plt
    plt.close(figure)
    local_noon_figure, _ = _build_local_noon_figure(corrected, channel=channel)
    local_noon_figure.savefig(
        output
        / "planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf"
    )
    plt.close(local_noon_figure)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Fit nightly empirical airmass corrections using only each "
            "planet's own measurements."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help=(
            "MMTO downloader manifest; verified image hashes and UTC times "
            "select the input independently of stellar extinction fits"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--store-coefficients",
        action="store_true",
        help=(
            "append an immutable planet empirical extinction generation "
            "to the shared database after all channel outputs succeed"
        ),
    )
    args = parser.parse_args(argv)
    if not args.database.is_file():
        parser.error(f"database does not exist: {args.database}")
    if not args.manifest.is_file():
        parser.error(f"manifest does not exist: {args.manifest}")
    if args.output.exists():
        if not args.output.is_dir():
            parser.error(f"output path is not a directory: {args.output}")
        if any(args.output.iterdir()):
            parser.error(f"output directory is not empty: {args.output}")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_snapshot = args.output / "input_manifest_snapshot.sqlite"
    manifest_snapshot_sha256 = snapshot_sqlite_database(
        args.manifest, manifest_snapshot
    )

    rows_by_channel = {}
    audits_by_channel = {}
    distance_candidates = []
    for channel in "RGB":
        rows, audit = load_mmto_manifest_planet_measurements(
            args.database,
            manifest_snapshot,
            channel,
        )
        rows_by_channel[channel] = rows
        audits_by_channel[channel] = audit
        distance_candidates.extend(
            row for row in rows
            if row.get("identity_status") == "metadata_time_match"
            and row.get("photometry_usable")
        )
    distance_lookup = _horizons_distance_lookup(distance_candidates)

    parent_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "database": str(args.database.resolve()),
        "manifest": str(args.manifest.resolve()),
        "manifest_snapshot": str(manifest_snapshot.resolve()),
        "manifest_snapshot_sha256": manifest_snapshot_sha256,
        "method": "planet-only nightly empirical airmass correction",
        "channels": {},
        "source_audits": audits_by_channel,
    }
    for channel in "RGB":
        rows = rows_by_channel[channel]
        prepared, input_audit = prepare_planet_measurements(
            rows,
            distance_lookup,
            uncertainty_lookup={},
        )
        summary = write_channel_outputs(
            prepared,
            args.output / channel,
            channel=channel,
            input_audit=input_audit,
        )
        parent_summary["channels"][channel] = summary
    if args.store_coefficients:
        fits_by_channel = {}
        for channel in "RGB":
            with (
                args.output
                / channel
                / "planet_nightly_empirical_extinction_coefficients.csv"
            ).open(newline="", encoding="utf-8") as stream:
                fits_by_channel[channel] = list(csv.DictReader(stream))
        parent_summary["database_generation_id"] = (
            write_planet_empirical_extinction_generation(
                args.database,
                manifest_snapshot,
                args.output,
                fits_by_channel,
                audits_by_channel,
                producer_version=PRODUCER_VERSION,
            )
        )
    (args.output / "planet_only_airmass_summary.json").write_text(
        json.dumps(parent_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for channel in "RGB":
        print((args.output / channel / "planet_only_airmass_before_after.pdf").resolve())
        print((
            args.output
            / channel
            / "planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf"
        ).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
