#!/usr/bin/env python3
"""Create review-sized tracked evidence from a complete radial study."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil

import numpy as np


def write_rows(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("study", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    study = arguments.study.resolve()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(study / "model_comparison.csv", output / "model_comparison.csv")
    shutil.copyfile(study / "audit.json", output / "summary.json")

    operational_fields = [
        "source_sha256", "source_group", "selected_order", "saved_fit_count",
        "saved_rms_px", "saved_rms_arcmin", "robust_baseline_success",
        "robust_baseline_rms_px", "robust_baseline_rms_arcmin",
        "robust_selected_success", "robust_selected_rms_px",
        "robust_selected_rms_arcmin", "selected_minus_baseline_rms_px",
        "selected_minus_baseline_rms_arcmin", "selected_minus_saved_rms_px",
        "association_gate_arcmin", "association_failure_reason",
        "planet_failure_reason", "robust_selected_radial_coefficients",
    ]
    with (study / "operational_comparison.csv").open(newline="") as stream:
        operational_rows = [
            {field: row.get(field, "") for field in operational_fields}
            for row in csv.DictReader(stream)
        ]
    write_rows(output / "operational_comparison.csv", operational_fields, operational_rows)

    association: dict[tuple[str, str, int, str], Counter[str]] = defaultdict(Counter)
    with (study / "association_yield.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = (
                row["source_sha256"],
                row["source_group"],
                int(row["selected_order"]),
                row["radial_bin"],
            )
            association[key][row["outcome"]] += 1
    association_rows = []
    for (source, group, order, radial_bin), counts in sorted(association.items()):
        baseline_matches = counts["common"] + counts["changed"] + counts["lost"]
        selected_matches = counts["common"] + counts["changed"] + counts["gained"]
        association_rows.append(
            {
                "source_sha256": source,
                "source_group": group,
                "selected_order": order,
                "radial_bin": radial_bin,
                "detections": sum(counts.values()),
                "baseline_matches": baseline_matches,
                "selected_matches": selected_matches,
                "net_gain": selected_matches - baseline_matches,
                "common": counts["common"],
                "changed": counts["changed"],
                "gained": counts["gained"],
                "lost": counts["lost"],
                "unmatched": counts["unmatched"],
            }
        )
    association_fields = [
        "source_sha256", "source_group", "selected_order", "radial_bin",
        "detections", "baseline_matches", "selected_matches", "net_gain",
        "common", "changed", "gained", "lost", "unmatched",
    ]
    write_rows(output / "association_yield.csv", association_fields, association_rows)

    planet_counts: dict[tuple[str, str, int, str, str], Counter[str]] = defaultdict(Counter)
    planet_deltas: dict[tuple[str, str, int, str, str], list[float]] = defaultdict(list)
    with (study / "planet_residual_comparison.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = (
                row["source_sha256"],
                row["source_group"],
                int(row["selected_order"]),
                row["radial_bin"],
                row["identity_type"],
            )
            planet_counts[key][row["classification"]] += 1
            planet_counts[key][row["gate_crossing"]] += 1
            planet_deltas[key].append(
                float(row["selected_separation_arcmin"])
                - float(row["baseline_separation_arcmin"])
            )
    planet_rows = []
    for (source, group, order, radial_bin, identity_type), counts in sorted(planet_counts.items()):
        planet_rows.append(
            {
                "source_sha256": source,
                "source_group": group,
                "selected_order": order,
                "radial_bin": radial_bin,
                "identity_type": identity_type,
                "candidates": counts["improved"] + counts["unchanged"] + counts["worsened"],
                "median_selected_minus_baseline_arcmin": float(np.median(planet_deltas[(source, group, order, radial_bin, identity_type)])),
                "improved": counts["improved"],
                "unchanged": counts["unchanged"],
                "worsened": counts["worsened"],
                "outside_to_inside": counts["outside_to_inside"],
                "inside_to_outside": counts["inside_to_outside"],
                "stayed_inside": counts["stayed_inside"],
                "stayed_outside": counts["stayed_outside"],
            }
        )
    planet_fields = [
        "source_sha256", "source_group", "selected_order", "radial_bin",
        "identity_type", "candidates", "median_selected_minus_baseline_arcmin",
        "improved", "unchanged", "worsened", "outside_to_inside",
        "inside_to_outside", "stayed_inside", "stayed_outside",
    ]
    write_rows(
        output / "planet_residual_comparison.csv", planet_fields, planet_rows
    )

    manifest = {
        "source_study": study.name,
        "model_rows": sum(1 for _ in (output / "model_comparison.csv").open()) - 1,
        "association_summary_rows": len(association_rows),
        "planet_summary_rows": len(planet_rows),
        "operational_rows": len(operational_rows),
        "note": "Association and planet files are per-image/radial-bin aggregates; full row-level evidence remains in the ignored results directory.",
    }
    (output / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
