#!/usr/bin/env python3
"""Build the frozen, post-fit v22 association with AAVSO VSX."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Sequence
import warnings

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy.time import Time
from erfa import ErfaWarning


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "v22" / "data"
VSX_CATALOGUE = "vizier:B/vsx/vsx"
VSX_CATALOGUE_VERSION = "2026-08-09"
XMATCH_ENDPOINT = "https://cdsxmatch.cds.unistra.fr/xmatch/api/v1/sync"
UTC = timezone.utc
OUTPUT_FIELDS = (
    "catalogue_filename",
    "catalogue_sha256",
    "star_id",
    "local_ra_j2000_deg",
    "local_dec_j2000_deg",
    "vsx_oid",
    "vsx_name",
    "vsx_flag",
    "vsx_type",
    "period_days",
    "vsx_ra_j2000_deg",
    "vsx_dec_j2000_deg",
    "match_distance_arcsec",
    "candidate_oid_count",
    "selection_status",
)


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def period_is_positive_finite(value: object) -> bool:
    period = _finite_float(value)
    return period is not None and period > 0.0


def propagate_to_j2000(
    *,
    ra_deg: float,
    dec_deg: float,
    reference_epoch_jyear: float,
    pm_ra_cosdec_mas_per_year: object,
    pm_dec_mas_per_year: object,
) -> tuple[float, float]:
    """Propagate one catalogue position to J2000 using angular proper motion."""

    coordinate = SkyCoord(
        ra=float(ra_deg) * u.deg,
        dec=float(dec_deg) * u.deg,
        pm_ra_cosdec=(_finite_float(pm_ra_cosdec_mas_per_year) or 0.0) * u.mas / u.yr,
        pm_dec=(_finite_float(pm_dec_mas_per_year) or 0.0) * u.mas / u.yr,
        obstime=Time(float(reference_epoch_jyear), format="jyear"),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ErfaWarning)
        propagated = coordinate.apply_space_motion(
            new_obstime=Time(2000.0, format="jyear")
        )
    return float(propagated.ra.deg), float(propagated.dec.deg)


def classify_candidate_rows(
    candidates: Sequence[dict[str, object]],
    *,
    match_radius_arcsec: float = 1.0,
) -> list[dict[str, object]]:
    """Return candidate rows with an explicit deterministic selection status."""

    rows = [dict(row) for row in candidates]
    inside_oids: set[str] = set()
    for row in rows:
        oid = str(row.get("vsx_oid", "")).strip()
        distance = _finite_float(row.get("match_distance_arcsec"))
        if oid and distance is not None and distance <= match_radius_arcsec:
            inside_oids.add(oid)
    oid_count = len(inside_oids)
    for row in rows:
        row["candidate_oid_count"] = oid_count
        distance = _finite_float(row.get("match_distance_arcsec"))
        flag = str(row.get("vsx_flag", "")).strip()
        period_text = str(row.get("period_days", "")).strip()
        if distance is None or distance > match_radius_arcsec:
            status = "outside_match_radius"
        elif oid_count > 1:
            status = "ambiguous_vsx_oid"
        elif flag != "0":
            status = "vsx_flag_not_confirmed_variable"
        elif not period_text:
            status = "missing_period"
        elif not period_is_positive_finite(period_text):
            status = "invalid_period"
        else:
            status = "eligible_catalogue_variable"
        row["selection_status"] = status
    return rows


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(getattr(value, "mask", False)):
            return ""
    except ValueError:
        pass
    text = str(value).strip()
    return "" if text in {"--", "nan", "None"} else text


def _column(row: object, names: Iterable[str]) -> str:
    columns = set(getattr(row, "colnames", ()))
    for name in names:
        if name in columns:
            return _text(row[name])
    return ""


def _load_upload(catalogue_paths: Sequence[Path]) -> tuple[Table, dict[str, dict[str, str]], dict[str, str]]:
    upload_rows: list[dict[str, object]] = []
    local_by_key: dict[str, dict[str, str]] = {}
    input_hashes: dict[str, str] = {}
    key = 0
    for path_value in catalogue_paths:
        path = Path(path_value)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        input_hashes[path.name] = digest
        with path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                key += 1
                ra, dec = propagate_to_j2000(
                    ra_deg=float(row["ra_deg"]),
                    dec_deg=float(row["dec_deg"]),
                    reference_epoch_jyear=float(row["reference_epoch_jyear"]),
                    pm_ra_cosdec_mas_per_year=row["pm_ra_cosdec_mas_per_year"],
                    pm_dec_mas_per_year=row["pm_dec_mas_per_year"],
                )
                local_key = str(key)
                local = {
                    "catalogue_filename": path.name,
                    "catalogue_sha256": digest,
                    "star_id": row["star_id"],
                    "local_ra_j2000_deg": f"{ra:.10f}",
                    "local_dec_j2000_deg": f"{dec:.10f}",
                }
                local_by_key[local_key] = local
                upload_rows.append(
                    {"local_key": local_key, "ra_j2000_deg": ra, "dec_j2000_deg": dec}
                )
    return Table(rows=upload_rows), local_by_key, input_hashes


def _query_candidates(upload: Table, match_radius_arcsec: float) -> Table:
    from astroquery.xmatch import XMatch

    return XMatch.query(
        cat1=upload,
        cat2=VSX_CATALOGUE,
        max_distance=float(match_radius_arcsec) * u.arcsec,
        colRA1="ra_j2000_deg",
        colDec1="dec_j2000_deg",
    )


def build_crossmatch(
    catalogue_paths: Sequence[Path],
    output_csv: Path,
    provenance_json: Path,
    match_radius_arcsec: float = 1.0,
) -> dict[str, object]:
    """Query VSX once and write deterministic offline runtime products."""

    if not math.isfinite(match_radius_arcsec) or match_radius_arcsec <= 0.0:
        raise ValueError("match radius must be positive and finite")
    upload, local_by_key, input_hashes = _load_upload(catalogue_paths)
    matches = _query_candidates(upload, match_radius_arcsec)
    grouped: dict[str, list[dict[str, object]]] = {}
    for match in matches:
        local_key = _column(match, ("local_key",))
        local = local_by_key.get(local_key)
        if local is None:
            raise ValueError(f"CDS XMatch returned unknown local_key {local_key!r}")
        candidate: dict[str, object] = {
            **local,
            "vsx_oid": _column(match, ("OID", "oid")),
            "vsx_name": _column(match, ("Name", "name")),
            "vsx_flag": _column(match, ("V", "VarFlag", "flag")),
            "vsx_type": _column(match, ("Type", "type")),
            "period_days": _column(match, ("Period", "period")),
            "vsx_ra_j2000_deg": _column(match, ("RAJ2000", "_RAJ2000", "RAdeg")),
            "vsx_dec_j2000_deg": _column(match, ("DEJ2000", "_DEJ2000", "DEdeg")),
            "match_distance_arcsec": _column(match, ("angDist", "angdist")),
        }
        grouped.setdefault(local_key, []).append(candidate)

    output_rows: list[dict[str, object]] = []
    for local_key in sorted(grouped, key=int):
        output_rows.extend(
            classify_candidate_rows(
                grouped[local_key], match_radius_arcsec=match_radius_arcsec
            )
        )
    output_rows.sort(
        key=lambda row: (
            str(row["catalogue_filename"]),
            str(row["star_id"]),
            _finite_float(row["match_distance_arcsec"]) or math.inf,
            str(row["vsx_oid"]),
        )
    )

    output_csv = Path(output_csv)
    provenance_json = Path(provenance_json)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(output_rows)
    csv_sha256 = hashlib.sha256(output_csv.read_bytes()).hexdigest()
    status_counts: dict[str, int] = {}
    for row in output_rows:
        status = str(row["selection_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    provenance: dict[str, object] = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "catalogue": "AAVSO International Variable Star Index (VSX)",
        "vizier_catalogue": VSX_CATALOGUE.removeprefix("vizier:"),
        "catalogue_version": VSX_CATALOGUE_VERSION,
        "xmatch_endpoint": XMATCH_ENDPOINT,
        "match_radius_arcsec": match_radius_arcsec,
        "position_epoch": "J2000.0",
        "input_catalogue_sha256": input_hashes,
        "input_star_count": len(local_by_key),
        "matched_candidate_rows": len(output_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "output_csv": output_csv.name,
        "output_csv_sha256": csv_sha256,
    }
    provenance_json.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue",
        type=Path,
        action="append",
        dest="catalogues",
        help="local stellar catalogue; repeat for multiple catalogues",
    )
    parser.add_argument("--output-csv", type=Path, default=DATA / "vsx_crossmatch.csv")
    parser.add_argument(
        "--provenance-json",
        type=Path,
        default=DATA / "vsx_crossmatch.provenance.json",
    )
    parser.add_argument("--match-radius-arcsec", type=float, default=1.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalogues = args.catalogues or [
        DATA / "stars_tycho2_mag75.csv",
        DATA / "stars_gaia_dr3_g75.csv",
    ]
    summary = build_crossmatch(
        catalogues,
        args.output_csv,
        args.provenance_json,
        args.match_radius_arcsec,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
