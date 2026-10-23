#!/usr/bin/env python3
"""Map cross-night MMTO transmission differences at matching sidereal time."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path
import sqlite3
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v23.mmto_sidereal_transmission import (
    Exposure, TransmissionMeasurement, apparent_sidereal_hours,
    differential_transmission, select_sidereal_pairs,
)


def _ro(path: Path):
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _write(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)


def generate(database: Path, manifest: Path, calibration: Path, output: Path, *, tolerance_minutes: float, min_common_stars: int):
    output.mkdir(parents=True, exist_ok=False); (output / "maps").mkdir()
    corrected_path = calibration / "corrected_stellar_photometry.csv"
    with corrected_path.open(newline="", encoding="utf-8") as stream:
        corrected = list(csv.DictReader(stream))
    with _ro(manifest) as connection:
        header_times = {str(digest): str(midpoint) for digest, midpoint in connection.execute("SELECT source_sha256,header_midpoint_utc FROM mmto_v23_observations")}
    exposure_data = {}
    run_ids = set()
    for row in corrected:
        digest = row["source_sha256"]; midpoint = row["header_midpoint_utc"]
        if header_times.get(digest) != midpoint:
            raise ValueError(f"calibration/header midpoint mismatch for {digest}")
        exposure_data[digest] = (row["night"], midpoint, row["run_id"]); run_ids.add(row["run_id"])
    exposures = [Exposure(digest, night, midpoint, apparent_sidereal_hours(midpoint)) for digest, (night, midpoint, _) in sorted(exposure_data.items())]
    pairs = select_sidereal_pairs(exposures, tolerance_minutes=tolerance_minutes)
    placeholders = ",".join("?" for _ in run_ids) or "NULL"
    coordinates = {}
    if run_ids:
        with _ro(database) as connection:
            for run_id, star_id, values_json in connection.execute(
                f"SELECT run_id,star_id,values_json FROM measurements WHERE product='star_coordinates.csv' AND run_id IN ({placeholders}) ORDER BY run_id,row_number",
                tuple(sorted(run_ids)),
            ):
                values = json.loads(values_json)
                try: coordinates[(str(run_id), str(star_id))] = (float(values["x_px"]), float(values["y_px"]))
                except (KeyError, TypeError, ValueError): pass
    measurements = defaultdict(list)
    for row in corrected:
        coordinate = coordinates.get((row["run_id"], row["star_id"]))
        if coordinate is None: continue
        measurements[row["source_sha256"]].append(TransmissionMeasurement(
            (row["catalogue_sha256"], row["star_id"]), row["channel"],
            float(row["corrected_magnitude"]), coordinate[0], coordinate[1],
        ))
    paired_sources = {digest for pair in pairs for digest in (pair.first.source_sha256, pair.second.source_sha256)}
    audit_rows = [{
        "source_sha256": item.source_sha256, "night": item.night,
        "header_midpoint_utc": item.midpoint_utc,
        "apparent_sidereal_hours": item.apparent_sidereal_hours,
        "status": "paired" if item.source_sha256 in paired_sources else "unpaired",
    } for item in exposures]
    summary_rows = []; output_rows = []; figure_paths = []
    for pair_number, pair in enumerate(pairs, 1):
        pair_id = f"pair-{pair_number:04d}"
        result = differential_transmission(measurements[pair.first.source_sha256], measurements[pair.second.source_sha256], min_common_stars=min_common_stars)
        for channel in sorted(result.status_by_channel):
            channel_rows = [row for row in result.rows if row.channel == channel]
            summary_rows.append({
                "pair_id": pair_id, "first_source_sha256": pair.first.source_sha256,
                "second_source_sha256": pair.second.source_sha256,
                "first_night": pair.first.night, "second_night": pair.second.night,
                "same_night": pair.first.night == pair.second.night,
                "first_midpoint_utc": pair.first.midpoint_utc, "second_midpoint_utc": pair.second.midpoint_utc,
                "sidereal_separation_minutes": pair.separation_minutes,
                "channel": channel, "common_star_count": result.common_count_by_channel[channel],
                "status": result.status_by_channel[channel], "interpolation_used": False,
            })
            for row in channel_rows:
                output_rows.append({
                    "pair_id": pair_id, "first_source_sha256": pair.first.source_sha256,
                    "second_source_sha256": pair.second.source_sha256,
                    "catalogue_sha256": row.star_key[0], "star_id": row.star_key[1],
                    "channel": row.channel, "x_px": row.x_px, "y_px": row.y_px,
                    "second_x_px": row.second_x_px, "second_y_px": row.second_y_px,
                    "raw_difference_magnitude": row.raw_difference_magnitude,
                    "pair_grey_median_magnitude": row.pair_grey_median_magnitude,
                    "grey_centred_difference_magnitude": row.grey_centred_difference_magnitude,
                    "status": row.status,
                })
            figure, axis = plt.subplots(figsize=(7, 6))
            if channel_rows:
                values = [row.grey_centred_difference_magnitude for row in channel_rows]
                limit = max(max(abs(value) for value in values), 0.01)
                points = axis.scatter([row.x_px for row in channel_rows], [row.y_px for row in channel_rows], c=values, cmap="RdBu_r", vmin=-limit, vmax=limit, s=18)
                figure.colorbar(points, ax=axis, label="Grey-centred second−first magnitude")
            else: axis.text(0.5, 0.5, "No common measured stars", transform=axis.transAxes, ha="center", va="center")
            axis.invert_yaxis(); axis.set_aspect("equal", adjustable="box")
            axis.set(xlabel="First-exposure measured x (px)", ylabel="First-exposure measured y (px)", title=f"{pair_id} {channel}: {result.status_by_channel[channel]}; N={len(channel_rows)}\nMeasured points only; no interpolation")
            figure.tight_layout(); figure_path = output / "maps" / f"{pair_id}_{channel}.png"; figure.savefig(figure_path, dpi=160); plt.close(figure); figure_paths.append(str(figure_path.relative_to(output)))
    _write(output / "sidereal_pair_audit.csv", ("source_sha256", "night", "header_midpoint_utc", "apparent_sidereal_hours", "status"), audit_rows)
    _write(output / "sidereal_pair_summary.csv", ("pair_id", "first_source_sha256", "second_source_sha256", "first_night", "second_night", "same_night", "first_midpoint_utc", "second_midpoint_utc", "sidereal_separation_minutes", "channel", "common_star_count", "status", "interpolation_used"), summary_rows)
    _write(output / "sidereal_transmission_measurements.csv", ("pair_id", "first_source_sha256", "second_source_sha256", "catalogue_sha256", "star_id", "channel", "x_px", "y_px", "second_x_px", "second_y_px", "raw_difference_magnitude", "pair_grey_median_magnitude", "grey_centred_difference_magnitude", "status"), output_rows)
    record = {
        "status": "complete", "solver_version": "0.23.0", "method": "distinct-night one-to-one nearest apparent-sidereal-time pairing",
        "longitude_deg_east_positive": -110.8841666667, "time_source": "validated FITS header midpoint",
        "tolerance_minutes": tolerance_minutes, "minimum_common_stars": min_common_stars,
        "exposure_count": len(exposures), "pair_count": len(pairs), "measurement_count": len(output_rows),
        "interpolation_used": False, "coordinate_policy": "first-exposure measured centroids plotted unchanged",
        "figures": figure_paths,
    }
    (output / "sidereal_transmission_manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--database", type=Path, required=True); parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--nightly-calibration", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--tolerance-minutes", type=float, default=5.0); parser.add_argument("--min-common-stars", type=int, default=20)
    args = parser.parse_args()
    record = generate(
        args.database, args.manifest, args.nightly_calibration, args.output,
        tolerance_minutes=args.tolerance_minutes,
        min_common_stars=args.min_common_stars,
    )
    terminal_summary = {
        key: value for key, value in record.items() if key != "figures"
    }
    terminal_summary["figure_count"] = len(record["figures"])
    print(json.dumps(terminal_summary, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
