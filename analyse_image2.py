#!/usr/bin/env python3
"""Compare independent wide-field solver v2 fits at modest catalogue depths."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from point_star_barghini2 import (
    SUPPORTED_LIMITS2,
    prepare_output,
    run2,
)


ROOT = Path(__file__).resolve().parent


def validate_limits2(values):
    """Return supported, strictly increasing, unique candidate limits."""
    limits = tuple(float(value) for value in values)
    if not limits:
        raise ValueError("At least one limiting magnitude is required")
    if any(value not in SUPPORTED_LIMITS2 for value in limits):
        raise ValueError(f"Supported limiting magnitudes are {SUPPORTED_LIMITS2}")
    if tuple(sorted(set(limits))) != limits:
        raise ValueError("Limiting magnitudes must be unique and increasing")
    return limits


def association_stability2(previous_rows, current_rows):
    """Summarise catalogue identities and detector assignments across two fits."""
    previous_pairs = {
        (str(row["detection_id"]), str(row["star_id"])) for row in previous_rows
    }
    current_pairs = {
        (str(row["detection_id"]), str(row["star_id"])) for row in current_rows
    }
    previous_stars = {star_id for _, star_id in previous_pairs}
    current_stars = {star_id for _, star_id in current_pairs}
    previous_by_detection = dict(previous_pairs)
    current_by_detection = dict(current_pairs)
    shared_detections = previous_by_detection.keys() & current_by_detection.keys()
    retained = sorted(previous_stars & current_stars)
    gained = sorted(current_stars - previous_stars)
    lost = sorted(previous_stars - current_stars)
    return {
        "previous_associations": len(previous_pairs),
        "current_associations": len(current_pairs),
        "retained_star_ids": len(retained),
        "gained_star_ids": len(gained),
        "lost_star_ids": len(lost),
        "stable_detector_star_pairs": len(previous_pairs & current_pairs),
        "reassigned_detections": sum(
            previous_by_detection[detection] != current_by_detection[detection]
            for detection in shared_detections
        ),
        "retained_star_id_values": retained,
        "gained_star_id_values": gained,
        "lost_star_id_values": lost,
    }


def _limit_label2(limit):
    return f"vlim_{limit:.1f}".replace(".", "p")


def _read_associations2(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run_comparison2(image, output, catalog, *, limits=SUPPORTED_LIMITS2, labels=40,
                    names_cache=None, offline=False, observation_time=None,
                    latitude=None, longitude=None, elevation_m=0.0):
    """Run every requested depth independently and write comparison-only evidence."""
    limits = validate_limits2(limits)
    output = prepare_output(output)
    candidates = []
    successful_rows = {}
    for limit in limits:
        candidate_output = output / _limit_label2(limit)
        try:
            result = run2(
                image,
                candidate_output,
                catalog,
                magnitude_limit=limit,
                label_count=labels,
                names_cache=names_cache,
                offline=offline,
                observation_time=observation_time,
                latitude=latitude,
                longitude=longitude,
                elevation_m=elevation_m,
            )
            rows = _read_associations2(candidate_output / "star_coordinates.csv")
            successful_rows[limit] = rows
            candidates.append({
                "magnitude_limit": limit,
                "status": result["status"],
                "output_directory": candidate_output.name,
                "catalogue_rows_at_limit": result["catalogue_rows_at_limit"],
                "associations": result["fit"]["count"],
                "rms_px": result["fit"]["rms_px"],
                "median_px": result["fit"]["median_px"],
                "p90_px": result["fit"]["p90_px"],
                "unmatched_dots": result["unmatched_dots"],
                "camera": result["camera"],
                "stages": result["stages"],
            })
        except Exception as error:
            candidates.append({
                "magnitude_limit": limit,
                "status": "candidate_failed",
                "output_directory": candidate_output.name,
                "error": f"{type(error).__name__}: {error}",
            })

    transitions = []
    for previous, current in zip(limits, limits[1:]):
        if previous in successful_rows and current in successful_rows:
            transition = association_stability2(
                successful_rows[previous], successful_rows[current]
            )
            transition.update(from_magnitude_limit=previous,
                              to_magnitude_limit=current,
                              status="compared")
        else:
            transition = {
                "from_magnitude_limit": previous,
                "to_magnitude_limit": current,
                "status": "unavailable_due_to_failed_candidate",
            }
        transitions.append(transition)

    comparison = {
        "solver_version": 2,
        "candidate_limits": list(limits),
        "selection": "none_exploratory_comparison_only",
        "candidates": candidates,
        "transitions": transitions,
        "limitation": (
            "All associated stars are fitted. Residuals are fit diagnostics, not "
            "independent validation; no limiting-magnitude winner is selected."
        ),
    }
    comparison_path = output / "limiting_magnitude_comparison2.json"
    comparison_path.write_text(json.dumps(comparison, indent=2) + "\n")
    return comparison


def parser2():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="JPEG, PNG or TIFF all-sky image")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "data/stars_tycho2_mag85_v2.csv",
    )
    parser.add_argument(
        "--magnitude-limits",
        nargs="+",
        type=float,
        default=list(SUPPORTED_LIMITS2),
        metavar="VLIM",
    )
    parser.add_argument("--labels", type=int, default=40)
    parser.add_argument("--names-cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--observation-time")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--elevation-m", type=float, default=0.0)
    return parser


def main():
    parser = parser2()
    args = parser.parse_args()
    try:
        limits = validate_limits2(args.magnitude_limits)
    except ValueError as error:
        parser.error(str(error))
    if (args.latitude is None) != (args.longitude is None):
        parser.error("--latitude and --longitude must be supplied together")
    comparison = run_comparison2(
        args.image,
        args.output,
        args.catalog,
        limits=limits,
        labels=args.labels,
        names_cache=args.names_cache,
        offline=args.offline,
        observation_time=args.observation_time,
        latitude=args.latitude,
        longitude=args.longitude,
        elevation_m=args.elevation_m,
    )
    failures = [candidate for candidate in comparison["candidates"]
                if candidate["status"] != "point_star_fit_converged"]
    print(json.dumps(comparison, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
