#!/usr/bin/env python3
"""Write read-only post-blind MMTO site, time, airmass and planet checks."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v23.mmto_validation import (
    known_airmass,
    planet_epoch_comparison,
    stellar_epoch_comparison,
    validate_blind_zenith,
)


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _successful_v23_runs(database: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (str(run_id), str(digest))
        for run_id, digest in database.execute(
            """
            WITH ranked AS (
              SELECT run_id, source_sha256,
                     row_number() OVER (PARTITION BY source_sha256 ORDER BY rowid DESC) AS rank
              FROM runs
              WHERE solver_version='0.23.0' AND exit_code=0 AND source_sha256 IS NOT NULL
            )
            SELECT run_id, source_sha256 FROM ranked WHERE rank=1 ORDER BY run_id
            """
        )
    ]


def _products(database: sqlite3.Connection, run_id: str) -> dict[str, str]:
    wanted = (
        "photometric_zenith.json", "science_summary.json", "planet_epoch.json",
        "star_coordinates.csv", "stellar_photometry.csv",
    )
    placeholders = ",".join("?" for _ in wanted)
    return {
        str(name): _text(content)
        for name, content in database.execute(
            f"SELECT product,content FROM products WHERE run_id=? AND product IN ({placeholders})",
            (run_id, *wanted),
        )
    }


def _observation(manifest: sqlite3.Connection, digest: str) -> dict[str, Any] | None:
    row = manifest.execute(
        """SELECT remote_url,header_start_utc,header_midpoint_utc,exposure_seconds,
                  header_schema,provenance,instrument
           FROM mmto_v23_observations WHERE source_sha256=?""",
        (digest,),
    ).fetchone()
    if row is None:
        return None
    keys = ("remote_url", "header_start_utc", "header_midpoint_utc", "exposure_seconds", "header_schema", "provenance", "instrument")
    return dict(zip(keys, row))


def _rows(text: str | None) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text or "")))


def write_validation(database_path: Path, manifest_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    site_rows: list[dict[str, Any]] = []
    airmass_rows: list[dict[str, Any]] = []
    planet_rows: list[dict[str, Any]] = []
    with _read_only(database_path) as database, _read_only(manifest_path) as manifest:
        runs = _successful_v23_runs(database)
        for run_id, digest in runs:
            observation = _observation(manifest, digest)
            if observation is None:
                continue
            midpoint = str(observation["header_midpoint_utc"])
            products = _products(database, run_id)
            zenith = json.loads(products.get("photometric_zenith.json", "{}"))
            vector = zenith.get("zenith_unit_vector")
            site = validate_blind_zenith(vector, midpoint) if vector is not None else {
                "used_in_fit": False, "validation_stage": "post_blind_fit",
                "derived_latitude_deg": None, "latitude_minus_known_deg": None,
                "zenith_separation_deg": None,
            }
            science = json.loads(products.get("science_summary.json", "{}"))
            stellar = science.get("stellar_epoch") or {}
            fitted_epoch = stellar.get("epoch_jyear")
            if fitted_epoch is None:
                fitted_epoch = stellar.get("best_epoch_jyear")
            epoch = stellar_epoch_comparison(fitted_epoch, midpoint)
            site_rows.append({
                "run_id": run_id, "source_sha256": digest,
                "header_midpoint_utc": midpoint,
                "header_start_utc": observation["header_start_utc"],
                "exposure_seconds": observation["exposure_seconds"],
                "header_schema": observation["header_schema"],
                "header_provenance": observation["provenance"],
                "blind_zenith_status": zenith.get("status"),
                "blind_zenith_metadata_used": zenith.get("metadata_used"),
                "stellar_epoch_status": stellar.get("status"),
                **site, **epoch,
            })

            blind_airmass = {row.get("detection_id"): row for row in _rows(products.get("stellar_photometry.csv"))}
            for coordinate in _rows(products.get("star_coordinates.csv")):
                try:
                    ra = float(coordinate["measured_ra_deg"])
                    dec = float(coordinate["measured_dec_deg"])
                except (KeyError, TypeError, ValueError):
                    continue
                known = known_airmass(ra, dec, midpoint)
                prior = blind_airmass.get(coordinate.get("detection_id"), {})
                try:
                    blind_value = float(prior["airmass"])
                except (KeyError, TypeError, ValueError):
                    blind_value = None
                airmass_rows.append({
                    "run_id": run_id, "source_sha256": digest,
                    "detection_id": coordinate.get("detection_id"),
                    "measured_ra_deg": ra, "measured_dec_deg": dec,
                    "blind_airmass": blind_value,
                    "known_site_airmass": known["airmass"],
                    "known_site_altitude_deg": known["altitude_deg"],
                    "parallactic_angle_deg": known["parallactic_angle_deg"],
                    "refraction_toward_zenith_position_angle_deg": known["refraction_toward_zenith_position_angle_deg"],
                    "known_minus_blind_airmass": (
                        float(known["airmass"]) - blind_value
                        if known["airmass"] is not None and blind_value is not None else None
                    ),
                    "used_in_fit": False,
                    "validation_stage": "post_blind_fit",
                })

            planets = json.loads(products.get("planet_epoch.json", "{}"))
            for row in planet_epoch_comparison(planets, midpoint):
                planet_rows.append({"run_id": run_id, "source_sha256": digest, "header_midpoint_utc": midpoint, **row})

    site_fields = (
        "run_id", "source_sha256", "header_start_utc", "header_midpoint_utc",
        "exposure_seconds", "header_schema", "header_provenance",
        "blind_zenith_status", "blind_zenith_metadata_used", "stellar_epoch_status",
        "derived_latitude_deg", "known_latitude_deg", "latitude_minus_known_deg",
        "known_longitude_deg", "known_elevation_m", "zenith_separation_deg",
        "stellar_epoch_jyear", "stellar_minus_header_years", "absolute_difference_days",
        "used_in_fit", "validation_stage",
    )
    airmass_fields = (
        "run_id", "source_sha256", "detection_id", "measured_ra_deg", "measured_dec_deg",
        "blind_airmass", "known_site_airmass", "known_site_altitude_deg",
        "known_minus_blind_airmass", "parallactic_angle_deg",
        "refraction_toward_zenith_position_angle_deg", "used_in_fit", "validation_stage",
    )
    planet_fields = (
        "run_id", "source_sha256", "header_midpoint_utc", "candidate_rank",
        "blind_status", "blind_metadata_used", "candidate_epoch_tdb", "candidate_jd_tdb",
        "planet_minus_header_seconds", "absolute_difference_seconds", "match_count",
        "rms_arcmin", "used_in_fit", "selection_changed", "validation_stage",
    )
    _write_csv(output / "mmto_site_time_validation.csv", site_rows, site_fields)
    _write_csv(output / "mmto_airmass_validation.csv", airmass_rows, airmass_fields)
    _write_csv(output / "mmto_planet_epoch_validation.csv", planet_rows, planet_fields)

    figure, axis = plt.subplots(figsize=(8, 4.5))
    plotted = [(row["header_midpoint_utc"], row.get("zenith_separation_deg")) for row in site_rows if row.get("zenith_separation_deg") is not None]
    if plotted:
        axis.plot([datetime.fromisoformat(x.replace("Z", "+00:00")) for x, _ in plotted], [y for _, y in plotted], "o")
    else:
        axis.text(0.5, 0.5, "No successful v23 zenith validations", ha="center", va="center", transform=axis.transAxes)
    axis.set(xlabel="FITS-header midpoint (UTC)", ylabel="Blind–known zenith separation (deg)", title="MMTO post-blind known-site/time validation")
    figure.autofmt_xdate(); figure.tight_layout(); figure.savefig(output / "mmto_site_time_validation.png", dpi=160); plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 4.5))
    offsets = [float(row["planet_minus_header_seconds"]) / 86400.0 for row in planet_rows if row.get("planet_minus_header_seconds") is not None]
    if offsets:
        axis.hist(offsets, bins=min(40, max(5, len(offsets))))
    else:
        axis.text(0.5, 0.5, "No blind planet-epoch candidates", ha="center", va="center", transform=axis.transAxes)
    axis.set(xlabel="Blind planet candidate minus header midpoint (days)", ylabel="Candidate count", title="Secondary planet-epoch inspection (no reranking)")
    figure.tight_layout(); figure.savefig(output / "mmto_planet_epoch_validation.png", dpi=160); plt.close(figure)

    summary = {
        "status": "complete", "solver_version": "0.23.0",
        "stage": "post_blind_fit_validation", "used_in_fit": False,
        "database_open_mode": "read_only", "manifest_open_mode": "read_only",
        "successful_v23_runs": len(site_rows), "airmass_rows": len(airmass_rows),
        "planet_candidate_rows": len(planet_rows),
        "planet_policy": "Saved blind candidates are compared with the header midpoint without changing selection, rank, associations, or fit.",
    }
    (output / "mmto_validation_provenance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = write_validation(args.database, args.manifest, args.output)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
