#!/usr/bin/env python3
"""Fit v22 MMTO extinction and per-image grey transparency read-only."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.nightly_extinction import StellarMeasurement
from v22.mmto_nightly_extinction import MODEL, fit_grey_extinction


ARIZONA = ZoneInfo("America/Phoenix")


def _ro(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    database.execute("PRAGMA query_only=ON")
    return database


def _night(value: str) -> str:
    local = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ARIZONA)
    return (local.date() if local.hour >= 12 else (local.date().fromordinal(local.date().toordinal() - 1))).isoformat()


def _boolean(value) -> bool | None:
    text = str(value).lower()
    return True if text == "true" else False if text == "false" else None


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_measurements(database_path: Path, manifest_path: Path):
    with _ro(manifest_path) as manifest:
        observations = {
            str(digest): str(midpoint)
            for digest, midpoint in manifest.execute(
                "SELECT source_sha256,header_midpoint_utc FROM mmto_v22_observations"
            )
        }
    measurements: list[StellarMeasurement] = []
    run_by_source: dict[str, str] = {}
    with _ro(database_path) as database:
        runs = database.execute(
            """SELECT run_id,source_sha256,catalogue_sha256 FROM (
                 SELECT run_id,source_sha256,catalogue_sha256,
                        row_number() OVER (PARTITION BY source_sha256 ORDER BY recorded_at_utc DESC,rowid DESC) rank
                 FROM runs WHERE solver_version='0.22.0' AND exit_code=0
                       AND source_sha256 IS NOT NULL AND catalogue_sha256 IS NOT NULL)
               WHERE rank=1 ORDER BY run_id"""
        ).fetchall()
        for run_id, digest, catalogue in runs:
            digest = str(digest)
            if digest not in observations:
                continue
            run_by_source[digest] = str(run_id)
            for star_id, values_json in database.execute(
                """SELECT star_id,values_json FROM measurements
                   WHERE run_id=? AND product='stellar_photometry.csv'
                   ORDER BY row_number""", (run_id,)
            ):
                try:
                    values = json.loads(values_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                magnitude = _finite(values.get("catalogue_magnitude"))
                airmass = _finite(values.get("airmass"))
                if not star_id or magnitude is None or airmass is None or airmass <= 0:
                    continue
                if _boolean(values.get("saturation_known")) is not True:
                    continue
                for channel in ("R", "G", "B"):
                    rate = _finite(values.get(f"{channel}_count_rate_adu_per_s"))
                    saturated = _boolean(values.get(f"{channel}_saturated"))
                    method = str(values.get(f"{channel}_measurement_method", ""))
                    if rate is None or rate <= 0 or saturated is not False or method != "aperture":
                        continue
                    measurements.append(StellarMeasurement(
                        night=_night(observations[digest]), source_sha256=digest,
                        catalogue_sha256=str(catalogue), star_id=str(star_id), channel=channel,
                        catalogue_magnitude=magnitude, count_rate_adu_per_s=rate,
                        count_rate_uncertainty_adu_per_s=None, airmass=airmass,
                        saturated=False, measurement_method="ordinary_aperture",
                        observed_utc=observations[digest],
                    ))
    measurements.sort(key=lambda row: (row.night, row.channel, row.observed_utc, row.star_key))
    return tuple(measurements), observations, run_by_source


def _write(path: Path, fields, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def calibrate(database: Path, manifest: Path, output: Path, *, min_stars: int, min_images: int, loss_scale_mag: float):
    output.mkdir(parents=True, exist_ok=False)
    measurements, observations, run_by_source = load_measurements(database, manifest)
    groups = defaultdict(list)
    for row in measurements:
        groups[(row.night, row.channel)].append(row)
    night_rows = []; image_rows = []; corrected_rows = []; all_fits = {}
    for (night, channel), rows in sorted(groups.items()):
        fit = fit_grey_extinction(rows, min_stars=min_stars, min_images=min_images, loss_scale_mag=loss_scale_mag)
        all_fits[(night, channel)] = fit
        night_rows.append({
            "night": night, "channel": channel, "model": fit.model, "status": fit.status,
            "extinction_mag_per_airmass": fit.extinction_mag_per_airmass,
            "extinction_uncertainty_magnitude_per_airmass": fit.extinction_uncertainty,
            "sample_count": fit.sample_count, "star_count": fit.star_count,
            "image_count": fit.image_count, "design_rank": fit.design_rank,
            "parameter_count": fit.parameter_count, "airmass_leverage_norm": fit.airmass_leverage_norm,
            "rms_magnitude": fit.rms_magnitude,
        })
        if fit.status != "accepted":
            continue
        baseline = float(sorted(fit.star_intercepts.values())[len(fit.star_intercepts) // 2])
        for digest, offset in sorted(fit.image_offsets.items(), key=lambda item: observations[item[0]]):
            image_rows.append({
                "night": night, "header_midpoint_utc": observations[digest],
                "run_id": run_by_source[digest], "source_sha256": digest,
                "channel": channel, "solver_version": "0.22.0", "model": fit.model,
                "status": fit.status, "grey_offset_magnitude": offset,
                "grey_offset_uncertainty_magnitude": fit.image_offset_uncertainties[digest],
                "night_reference_zero_point_magnitude": baseline,
                "absolute_image_zero_point_magnitude": baseline + offset,
                "extinction_mag_per_airmass": fit.extinction_mag_per_airmass,
            })
        for row, residual in zip(rows, fit.residuals, strict=True):
            machine = row.machine_magnitude
            extinction = float(fit.extinction_mag_per_airmass) * row.airmass
            grey = fit.image_offsets[row.source_sha256]
            corrected_rows.append({
                "night": night, "header_midpoint_utc": row.observed_utc,
                "run_id": run_by_source[row.source_sha256], "source_sha256": row.source_sha256,
                "catalogue_sha256": row.catalogue_sha256, "star_id": row.star_id,
                "channel": channel, "catalogue_magnitude": row.catalogue_magnitude,
                "airmass": row.airmass, "machine_magnitude": machine,
                "extinction_mag_per_airmass": fit.extinction_mag_per_airmass,
                "extinction_correction_magnitude": extinction,
                "grey_correction_magnitude": grey,
                "corrected_magnitude": machine - extinction - grey,
                "fit_residual_magnitude": residual, "status": fit.status,
            })
    _write(output / "nightly_grey_extinction.csv", (
        "night", "channel", "model", "status", "extinction_mag_per_airmass",
        "extinction_uncertainty_magnitude_per_airmass", "sample_count", "star_count",
        "image_count", "design_rank", "parameter_count", "airmass_leverage_norm", "rms_magnitude",
    ), night_rows)
    _write(output / "image_grey_transparency.csv", (
        "night", "header_midpoint_utc", "run_id", "source_sha256", "channel",
        "solver_version", "model", "status", "grey_offset_magnitude",
        "grey_offset_uncertainty_magnitude", "night_reference_zero_point_magnitude",
        "absolute_image_zero_point_magnitude", "extinction_mag_per_airmass",
    ), image_rows)
    _write(output / "corrected_stellar_photometry.csv", (
        "night", "header_midpoint_utc", "run_id", "source_sha256", "catalogue_sha256",
        "star_id", "channel", "catalogue_magnitude", "airmass", "machine_magnitude",
        "extinction_mag_per_airmass", "extinction_correction_magnitude",
        "grey_correction_magnitude", "corrected_magnitude", "fit_residual_magnitude", "status",
    ), corrected_rows)
    fig, axis = plt.subplots(figsize=(9, 5))
    for channel in ("R", "G", "B"):
        selected = [row for row in image_rows if row["channel"] == channel]
        if selected:
            axis.plot([datetime.fromisoformat(str(row["header_midpoint_utc"]).replace("Z", "+00:00")) for row in selected], [row["grey_offset_magnitude"] for row in selected], "o-", label=channel)
    axis.axhline(0, color="black", linewidth=0.8); axis.set(xlabel="FITS-header midpoint (UTC)", ylabel="Grey offset Z_i (mag; nightly mean zero)", title="MMTO v22 per-exposure grey transparency")
    if image_rows: axis.legend()
    else: axis.text(0.5, 0.5, "No accepted nightly grey fits", transform=axis.transAxes, ha="center", va="center")
    fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(output / "grey_transparency.png", dpi=160); plt.close(fig)
    provenance = {
        "status": "complete", "solver_version": "0.22.0", "model": MODEL,
        "formula": "m(s,i) = a_s + k X(s,i) + Z_i; sum_i Z_i = 0",
        "corrected_magnitude_formula": "m_corrected = m_machine - k X - Z_i",
        "sample_membership": "fixed within each night/channel; soft-L1 weighting; no residual clipping",
        "time_source": "mmto_v22_observations.header_midpoint_utc from validated FITS headers",
        "database_open_mode": "read_only", "manifest_open_mode": "read_only",
        "selected_successful_v22_runs": len(run_by_source), "measurement_rows": len(measurements),
        "accepted_night_channel_fits": sum(fit.status == "accepted" for fit in all_fits.values()),
    }
    (output / "calibration_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True); parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-stars", type=int, default=20); parser.add_argument("--min-images", type=int, default=3); parser.add_argument("--loss-scale-mag", type=float, default=0.1)
    args = parser.parse_args()
    if args.min_stars < 2 or args.min_images < 2: parser.error("minimum stars and images must be at least two")
    print(json.dumps(calibrate(args.database, args.manifest, args.output, min_stars=args.min_stars, min_images=args.min_images, loss_scale_mag=args.loss_scale_mag), sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
