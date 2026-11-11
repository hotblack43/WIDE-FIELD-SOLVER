#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
from astroquery.vizier import Vizier
from scipy.spatial import cKDTree


TYCHO2_CATALOGUE = "I/259/tyc2"
HIPPARCOS_CATALOGUE = "I/239/hip_main"
HIPPARCOS_REFERENCE_EPOCH = 1991.25
DEDUPLICATION_RADIUS_ARCSEC = 60.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download a magnitude-limited Tycho-2 catalogue and supplement stars "
            "missing from it with Hipparcos ICRS positions and proper motions."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/stars_tycho2_mag75.csv"),
    )
    parser.add_argument("--magnitude-limit", type=float, default=7.5)
    parser.add_argument(
        "--hipparcos-supplement-limit",type=float,default=2.0,
        help="Only supplement exceptionally bright Hipparcos stars (default: V<=2).")
    return parser


def find_column(table: object, *candidates: str) -> str:
    names = list(table.colnames)
    for candidate in candidates:
        if candidate in names:
            return candidate
    folded = {name.casefold(): name for name in names}
    for candidate in candidates:
        if candidate.casefold() in folded:
            return folded[candidate.casefold()]
    raise RuntimeError(
        f"None of the requested columns {candidates!r} occurred in {names!r}."
    )


def finite_float(value: object) -> float | None:
    if np.ma.is_masked(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def unit_vector(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra,dec=np.deg2rad([ra_deg,dec_deg])
    return np.array([math.cos(dec)*math.cos(ra),
                     math.cos(dec)*math.sin(ra),math.sin(dec)])


def propagate_position(ra_deg: float, dec_deg: float, pm_ra_cosdec: float | None,
                       pm_dec: float | None, years: float) -> tuple[float,float]:
    if pm_ra_cosdec is None or pm_dec is None:
        return ra_deg,dec_deg
    dec=dec_deg+pm_dec*years/3.6e6
    cosine=max(abs(math.cos(math.radians(dec_deg))),1.0e-12)
    ra=ra_deg+pm_ra_cosdec*years/(3.6e6*cosine)
    return ra%360.0,dec

def tycho_identifier(tyc1: object, tyc2: object, tyc3: object) -> str:
    return f"TYC {int(tyc1):04d}-{int(tyc2):05d}-{int(tyc3)}"


def main() -> None:
    args = build_parser().parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Vizier.ROW_LIMIT = -1
    query = Vizier(
        columns=[
            "TYC1",
            "TYC2",
            "TYC3",
            "RA(ICRS)",
            "DE(ICRS)",
            "pmRA",
            "pmDE",
            "VTmag",
        ],
        row_limit=-1,
    )
    print(
        f"Querying Tycho-2 for stars with VTmag <= {args.magnitude_limit:g} ..."
    )
    result = query.query_constraints(
        catalog=TYCHO2_CATALOGUE,
        VTmag=f"<={args.magnitude_limit:g}",
    )
    if not result:
        raise RuntimeError("VizieR returned no Tycho-2 table.")
    table = result[0]
    print(f"Retrieved {len(table)} rows; columns: {', '.join(table.colnames)}")

    ra_name = find_column(table, "RA(ICRS)", "_RA.icrs", "RAJ2000", "_RAJ2000")
    dec_name = find_column(table, "DE(ICRS)", "_DE.icrs", "DEJ2000", "_DEJ2000")
    pm_ra_name = find_column(table, "pmRA")
    pm_dec_name = find_column(table, "pmDE")
    magnitude_name = find_column(table, "VTmag")
    tyc1_name = find_column(table, "TYC1")
    tyc2_name = find_column(table, "TYC2")
    tyc3_name = find_column(table, "TYC3")
    hip_query=Vizier(
        columns=["HIP","RAICRS","DEICRS","pmRA","pmDE","Vmag"],
        row_limit=-1)
    supplement_limit=min(args.magnitude_limit,args.hipparcos_supplement_limit)
    print(f"Querying Hipparcos bright supplement for Vmag <= {supplement_limit:g} ...")
    hip_result=hip_query.query_constraints(
        catalog=HIPPARCOS_CATALOGUE,Vmag=f"<={supplement_limit:g}")
    if not hip_result:
        raise RuntimeError("VizieR returned no Hipparcos table.")
    hip_table=hip_result[0]
    hip_id_name=find_column(hip_table,"HIP")
    hip_ra_name=find_column(hip_table,"RAICRS","_RA.icrs","RA(ICRS)")
    hip_dec_name=find_column(hip_table,"DEICRS","_DE.icrs","DE(ICRS)")
    hip_pm_ra_name=find_column(hip_table,"pmRA")
    hip_pm_dec_name=find_column(hip_table,"pmDE")
    hip_magnitude_name=find_column(hip_table,"Vmag")
    print(f"Retrieved {len(hip_table)} Hipparcos rows.")

    fieldnames = (
        "star_id",
        "ra_deg",
        "dec_deg",
        "mag",
        "reference_epoch_jyear",
        "pm_ra_cosdec_mas_per_year",
        "pm_dec_mas_per_year",
    )
    written = 0
    hip_written = 0
    proper_motion_rows = 0
    tycho_vectors=[]
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in table:
            ra = finite_float(row[ra_name])
            dec = finite_float(row[dec_name])
            magnitude = finite_float(row[magnitude_name])
            if ra is None or dec is None or magnitude is None:
                continue
            pm_ra = finite_float(row[pm_ra_name])
            pm_dec = finite_float(row[pm_dec_name])
            if pm_ra is not None and pm_dec is not None:
                proper_motion_rows += 1
            writer.writerow(
                {
                    "star_id": tycho_identifier(
                        row[tyc1_name],
                        row[tyc2_name],
                        row[tyc3_name],
                    ),
                    "ra_deg": f"{ra:.8f}",
                    "dec_deg": f"{dec:.8f}",
                    "mag": f"{magnitude:.3f}",
                    "reference_epoch_jyear": "2000.0",
                    "pm_ra_cosdec_mas_per_year": (
                        "" if pm_ra is None else f"{pm_ra:.3f}"
                    ),
                    "pm_dec_mas_per_year": (
                        "" if pm_dec is None else f"{pm_dec:.3f}"
                    ),
                }
            )
            written += 1
            tycho_vectors.append(unit_vector(ra,dec))
        tycho_tree=cKDTree(np.asarray(tycho_vectors))
        deduplication_chord=2*math.sin(
            math.radians(DEDUPLICATION_RADIUS_ARCSEC/3600)/2)
        for row in hip_table:
            ra=finite_float(row[hip_ra_name])
            dec=finite_float(row[hip_dec_name])
            magnitude=finite_float(row[hip_magnitude_name])
            hip_id=finite_float(row[hip_id_name])
            if ra is None or dec is None or magnitude is None or hip_id is None:
                continue
            pm_ra=finite_float(row[hip_pm_ra_name])
            pm_dec=finite_float(row[hip_pm_dec_name])
            match_ra,match_dec=propagate_position(
                ra,dec,pm_ra,pm_dec,2000.0-HIPPARCOS_REFERENCE_EPOCH)
            if tycho_tree.query(unit_vector(match_ra,match_dec))[0]<=deduplication_chord:
                continue
            if pm_ra is not None and pm_dec is not None:
                proper_motion_rows += 1
            writer.writerow({
                "star_id":f"HIP {int(hip_id):06d}",
                "ra_deg":f"{ra:.8f}","dec_deg":f"{dec:.8f}",
                "mag":f"{magnitude:.3f}",
                "reference_epoch_jyear":f"{HIPPARCOS_REFERENCE_EPOCH:.2f}",
                "pm_ra_cosdec_mas_per_year":(
                    "" if pm_ra is None else f"{pm_ra:.3f}"),
                "pm_dec_mas_per_year":(
                    "" if pm_dec is None else f"{pm_dec:.3f}")})
            written += 1
            hip_written += 1

    print(
        f"Wrote {written} stars to {args.output}, including "
        f"{hip_written} Hipparcos supplements; "
        f"{proper_motion_rows} have both proper-motion components."
    )


if __name__ == "__main__":
    main()
