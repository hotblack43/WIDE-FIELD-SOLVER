#!/usr/bin/env python3
"""Independently audit a published v12 radial-model study from its CSV evidence."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import re

import numpy as np


def optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def truth(value: str | None) -> bool:
    return str(value).lower() == "true"


def quantiles(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [float(value) for value in np.quantile(values, [0.25, 0.5, 0.75])]


def audit(directory: Path) -> dict[str, object]:
    models: dict[str, dict[int, dict[str, str]]] = defaultdict(dict)
    classifications: dict[int, Counter[str]] = defaultdict(Counter)
    failure_reasons: dict[int, Counter[str]] = defaultdict(Counter)
    aic_errors: list[float] = []
    aicc_errors: list[float] = []
    bic_errors: list[float] = []
    parameter_count_errors = 0
    with (directory / "model_comparison.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            source = row["source_sha256"]
            order = int(row["order"])
            models[source][order] = row
            classifications[order][row["classification"]] += 1
            if not truth(row["fit_valid"]):
                failure_reasons[order][row["failure_reason"] or "unspecified"] += 1
            rss = optional_float(row["rss_arcmin2"])
            n = int(row["n"]) if row["n"] else None
            k = int(row["k"]) if row["k"] else None
            camera_k = int(row["camera_parameter_count"]) if row.get("camera_parameter_count") else None
            information_k = int(row["information_parameter_count"]) if row.get("information_parameter_count") else None
            if camera_k is not None and (information_k != camera_k + 1 or k != information_k):
                parameter_count_errors += 1
            if rss is not None and rss > 0.0 and n and k is not None and n > k + 1:
                expected_aic = n * math.log(rss / n) + 2 * k
                expected_aicc = expected_aic + 2 * k * (k + 1) / (n - k - 1)
                expected_bic = n * math.log(rss / n) + k * math.log(n)
                for key, expected, errors in (
                    ("aic", expected_aic, aic_errors),
                    ("aicc", expected_aicc, aicc_errors),
                    ("bic", expected_bic, bic_errors),
                ):
                    actual = optional_float(row[key])
                    if actual is not None:
                        errors.append(abs(actual - expected))

    selected_counts: Counter[int] = Counter()
    fitted_delta_px: list[float] = []
    fitted_relative_percent: list[float] = []
    validation_delta_arcmin: list[float] = []
    selected_delta_aicc: list[float] = []
    extension_fitted_delta_px: list[float] = []
    extension_fitted_relative_percent: list[float] = []
    extension_validation_delta_arcmin: list[float] = []
    extension_delta_aicc: list[float] = []
    extension_validation_by_group: dict[str, list[float]] = defaultdict(list)
    selected_extension_rule_violations = 0
    group_selected_orders: dict[str, Counter[int]] = defaultdict(Counter)
    group_extension_validation: dict[str, list[float]] = defaultdict(list)
    group_extension_relative_percent: dict[str, list[float]] = defaultdict(list)
    examples: list[tuple[float, str, int, float, float]] = []
    weight_errors: list[float] = []
    malformed_model_sets: list[str] = []
    for source, rows in models.items():
        if set(rows) != set(range(6)):
            malformed_model_sets.append(source)
            continue
        selected_values = {int(row["selected_order"]) for row in rows.values()}
        if len(selected_values) != 1:
            malformed_model_sets.append(source)
            continue
        selected = selected_values.pop()
        selected_counts[selected] += 1
        baseline = rows[0]
        chosen = rows[selected]
        source_group = chosen["source_group"]
        group_selected_orders[source_group][selected] += 1
        base_px = optional_float(baseline["rms_px"])
        chosen_px = optional_float(chosen["rms_px"])
        if base_px is not None and chosen_px is not None:
            delta = chosen_px - base_px
            fitted_delta_px.append(delta)
            if base_px > 0.0:
                fitted_relative_percent.append(100.0 * delta / base_px)
            examples.append((delta, source, selected, base_px, chosen_px))
            if selected > 0:
                extension_fitted_delta_px.append(delta)
                if base_px > 0.0:
                    relative = 100.0 * delta / base_px
                    extension_fitted_relative_percent.append(relative)
                    group_extension_relative_percent[source_group].append(relative)
        validation = optional_float(chosen["validation_delta_rms_arcmin"])
        if validation is not None:
            validation_delta_arcmin.append(validation)
            if selected > 0:
                extension_validation_delta_arcmin.append(validation)
                extension_validation_by_group[chosen["source_group"]].append(validation)
                group_extension_validation[source_group].append(validation)
        delta_aicc = optional_float(chosen["delta_aicc"])
        if delta_aicc is not None:
            selected_delta_aicc.append(delta_aicc)
            if selected > 0:
                extension_delta_aicc.append(delta_aicc)
        if selected > 0 and (
            chosen["classification"] != "supported"
            or validation is None
            or validation >= 0.0
            or (optional_float(chosen["validation_delta_ci_high"]) or 0.0) >= 0.0
        ):
            selected_extension_rule_violations += 1
        weights = [optional_float(row["akaike_weight"]) for row in rows.values()]
        finite_weights = [value for value in weights if value is not None]
        if finite_weights:
            weight_errors.append(abs(sum(finite_weights) - 1.0))

    fold_counts: Counter[tuple[str, int]] = Counter()
    fold_holdout_counts: Counter[tuple[str, int]] = Counter()
    fold_failures: Counter[str] = Counter()
    invalid_hashes = 0
    with (directory / "validation_folds.csv").open(newline="") as stream:
        fold_row_count = 0
        for row in csv.DictReader(stream):
            fold_row_count += 1
            key = (row["source_sha256"], int(row["order"]))
            fold_counts[key] += 1
            fold_holdout_counts[key] += int(row["holdout_count"])
            if row["failure_reason"]:
                fold_failures[row["failure_reason"]] += 1
            if not re.fullmatch(r"[0-9a-f]{64}", row["training_index_sha256"] or ""):
                invalid_hashes += 1
            if not re.fullmatch(r"[0-9a-f]{64}", row["holdout_index_sha256"] or ""):
                invalid_hashes += 1
    fold_count_errors = sum(count != 8 for count in fold_counts.values())
    holdout_count_errors = 0
    for (source, order), count in fold_holdout_counts.items():
        expected = int(models[source][order]["n"]) // 2
        holdout_count_errors += count != expected

    association_outcomes: Counter[str] = Counter()
    association_by_radius: dict[str, Counter[str]] = defaultdict(Counter)
    association_by_order: dict[int, Counter[str]] = defaultdict(Counter)
    association_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    association_order_by_source: dict[str, int] = {}
    common_deltas: list[float] = []
    edge_common_deltas: list[float] = []
    gained_selected_residuals: list[float] = []
    edge_gains = edge_losses = 0
    extension_association_outcomes: Counter[str] = Counter()
    extension_association_by_radius: dict[str, Counter[str]] = defaultdict(Counter)
    extension_common_deltas: list[float] = []
    extension_outer_common_deltas: list[float] = []
    with (directory / "association_yield.csv").open(newline="") as stream:
        association_row_count = 0
        for row in csv.DictReader(stream):
            association_row_count += 1
            outcome = row["outcome"]
            radius = float(row["normalised_radius"])
            selected = int(row["selected_order"])
            source = row["source_sha256"]
            association_outcomes[outcome] += 1
            association_by_radius[row["radial_bin"]][outcome] += 1
            association_by_order[selected][outcome] += 1
            association_by_source[source][outcome] += 1
            association_order_by_source[source] = selected
            if selected > 0:
                extension_association_outcomes[outcome] += 1
                extension_association_by_radius[row["radial_bin"]][outcome] += 1
            baseline_residual = optional_float(row["baseline_residual_arcmin"])
            selected_residual = optional_float(row["selected_residual_arcmin"])
            if outcome in {"common", "changed"} and baseline_residual is not None and selected_residual is not None:
                delta = selected_residual - baseline_residual
                common_deltas.append(delta)
                if radius >= 0.75:
                    edge_common_deltas.append(delta)
                if selected > 0:
                    extension_common_deltas.append(delta)
                    if radius >= 0.5:
                        extension_outer_common_deltas.append(delta)
            if outcome == "gained" and selected_residual is not None:
                gained_selected_residuals.append(selected_residual)
            if radius >= 0.75:
                edge_gains += outcome == "gained"
                edge_losses += outcome == "lost"
    image_net = {
        source: counts["gained"] - counts["lost"]
        for source, counts in association_by_source.items()
    }
    net_counts = Counter(
        "positive" if value > 0 else "negative" if value < 0 else "zero"
        for value in image_net.values()
    )
    extension_image_net = {
        source: value
        for source, value in image_net.items()
        if association_order_by_source[source] > 0
    }
    extension_net_counts = Counter(
        "positive" if value > 0 else "negative" if value < 0 else "zero"
        for value in extension_image_net.values()
    )

    selected_group_interval = None
    if extension_validation_by_group:
        groups = sorted(extension_validation_by_group)
        rng = np.random.default_rng(120924)
        medians = []
        for _ in range(10_000):
            selected_groups = rng.choice(groups, size=len(groups), replace=True)
            values = [
                value
                for group in selected_groups
                for value in extension_validation_by_group[group]
            ]
            medians.append(float(np.median(values)))
        selected_group_interval = [
            float(value) for value in np.quantile(medians, [0.025, 0.975])
        ]

    planet_classifications: Counter[str] = Counter()
    planet_crossings: Counter[str] = Counter()
    planet_crossings_edge: Counter[str] = Counter()
    planet_crossings_by_radius: dict[str, Counter[str]] = defaultdict(Counter)
    planet_classifications_by_radius: dict[str, Counter[str]] = defaultdict(Counter)
    planet_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    planet_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    planet_order_by_source: dict[str, int] = {}
    planet_deltas: list[float] = []
    edge_planet_deltas: list[float] = []
    extension_planet_classifications: Counter[str] = Counter()
    extension_planet_crossings: Counter[str] = Counter()
    extension_planet_deltas: list[float] = []
    extension_outer_planet_deltas: list[float] = []
    with (directory / "planet_residual_comparison.csv").open(newline="") as stream:
        planet_row_count = 0
        for row in csv.DictReader(stream):
            planet_row_count += 1
            classification = row["classification"]
            crossing = row["gate_crossing"]
            radius = float(row["normalised_radius"])
            planet_classifications[classification] += 1
            planet_crossings[crossing] += 1
            planet_crossings_by_radius[row["radial_bin"]][crossing] += 1
            planet_classifications_by_radius[row["radial_bin"]][classification] += 1
            planet_by_type[row["identity_type"]][crossing] += 1
            planet_by_source[row["source_sha256"]][crossing] += 1
            planet_order_by_source[row["source_sha256"]] = int(row["selected_order"])
            selected_order = int(row["selected_order"])
            if selected_order > 0:
                extension_planet_classifications[classification] += 1
                extension_planet_crossings[crossing] += 1
            baseline = optional_float(row["baseline_separation_arcmin"])
            selected = optional_float(row["selected_separation_arcmin"])
            if baseline is not None and selected is not None:
                delta = selected - baseline
                planet_deltas.append(delta)
                if radius >= 0.75:
                    edge_planet_deltas.append(delta)
                if selected_order > 0:
                    extension_planet_deltas.append(delta)
                    if radius >= 0.5:
                        extension_outer_planet_deltas.append(delta)
            if radius >= 0.75:
                planet_crossings_edge[crossing] += 1
    planet_image_net = {
        source: counts["outside_to_inside"] - counts["inside_to_outside"]
        for source, counts in planet_by_source.items()
        if planet_order_by_source[source] > 0
    }
    planet_image_net_counts = Counter(
        "positive" if value > 0 else "negative" if value < 0 else "zero"
        for value in planet_image_net.values()
    )

    inventory_reasons: Counter[str] = Counter()
    selected_inventory = 0
    analysis_failures = 0
    with (directory / "solution_inventory.csv").open(newline="") as stream:
        inventory_count = 0
        for row in csv.DictReader(stream):
            inventory_count += 1
            inventory_reasons[row["reason"]] += 1
            selected_inventory += truth(row["selected"])
            analysis_failures += bool(row.get("analysis_failure"))

    operational_rows = 0
    association_gate_missing = 0
    planet_gate_missing = 0
    camera_decode_errors = 0
    selected_coefficient_errors = 0
    robust_selected_delta_px: list[float] = []
    extension_robust_selected_delta_px: list[float] = []
    extension_robust_selected_delta_arcmin: list[float] = []
    operational_failure_reasons: Counter[str] = Counter()
    association_gate_by_source: dict[str, float | None] = {}
    with (directory / "operational_comparison.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            operational_rows += 1
            association_gate_missing += not bool(row.get("association_gate_arcmin"))
            association_gate_by_source[row["source_sha256"]] = optional_float(
                row.get("association_gate_arcmin")
            )
            planet_gate_missing += row.get("planet_failure_reason") == "saved_planet_gate_unavailable"
            if row.get("association_failure_reason"):
                operational_failure_reasons[f"association:{row['association_failure_reason']}"] += 1
            if row.get("planet_failure_reason"):
                operational_failure_reasons[f"planet:{row['planet_failure_reason']}"] += 1
            try:
                camera = json.loads(row["robust_selected_camera"])
                coefficients = json.loads(row["robust_selected_radial_coefficients"])
            except (KeyError, TypeError, json.JSONDecodeError):
                camera_decode_errors += 1
                continue
            selected_coefficient_errors += len(coefficients) != int(row["selected_order"])
            saved_coefficients = camera.get("radial_extension", {}).get("coefficients_rad")
            selected_coefficient_errors += saved_coefficients != coefficients
            delta = optional_float(row.get("selected_minus_baseline_rms_px"))
            selected_success = truth(row.get("robust_selected_success"))
            if delta is not None and selected_success:
                robust_selected_delta_px.append(delta)
                if int(row["selected_order"]) > 0:
                    extension_robust_selected_delta_px.append(delta)
            angular_delta = optional_float(row.get("selected_minus_baseline_rms_arcmin"))
            if angular_delta is not None and selected_success and int(row["selected_order"]) > 0:
                extension_robust_selected_delta_arcmin.append(angular_delta)

    association_gate_mismatches = 0
    with (directory / "association_yield.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            expected = association_gate_by_source.get(row["source_sha256"])
            actual = optional_float(row.get("gate_arcmin"))
            association_gate_mismatches += expected is None or actual != expected

    examples.sort()
    return {
        "inventory": {
            "rows": inventory_count,
            "selected": selected_inventory,
            "analysis_failures": analysis_failures,
            "reasons": dict(sorted(inventory_reasons.items())),
        },
        "models": {
            "images": len(models),
            "rows": sum(len(rows) for rows in models.values()),
            "malformed_model_sets": malformed_model_sets,
            "selected_order_counts": dict(sorted(selected_counts.items())),
            "classification_counts_by_order": {
                str(order): dict(sorted(counts.items()))
                for order, counts in sorted(classifications.items())
            },
            "failure_reasons_by_order": {
                str(order): dict(sorted(counts.items()))
                for order, counts in sorted(failure_reasons.items())
            },
            "selected_fitted_delta_px_quartiles": quantiles(fitted_delta_px),
            "selected_fitted_relative_percent_quartiles": quantiles(fitted_relative_percent),
            "selected_validation_delta_arcmin_quartiles": quantiles(validation_delta_arcmin),
            "selected_delta_aicc_quartiles": quantiles(selected_delta_aicc),
            "extension_fitted_delta_px_quartiles": quantiles(extension_fitted_delta_px),
            "extension_fitted_relative_percent_quartiles": quantiles(extension_fitted_relative_percent),
            "extension_validation_delta_arcmin_quartiles": quantiles(extension_validation_delta_arcmin),
            "extension_delta_aicc_quartiles": quantiles(extension_delta_aicc),
            "extension_validation_cluster_bootstrap_median_95_interval_arcmin": selected_group_interval,
            "selected_extension_rule_violations": selected_extension_rule_violations,
            "by_source_group": {
                group: {
                    "images": sum(group_selected_orders[group].values()),
                    "selected_order_counts": dict(sorted(group_selected_orders[group].items())),
                    "extension_validation_delta_arcmin_quartiles": quantiles(group_extension_validation[group]),
                    "extension_fitted_relative_percent_quartiles": quantiles(group_extension_relative_percent[group]),
                }
                for group in sorted(group_selected_orders)
            },
            "largest_fitted_improvements": [
                {"delta_px": delta, "source_sha256": source, "order": order, "baseline_px": base, "selected_px": selected}
                for delta, source, order, base, selected in examples[:5]
            ],
            "largest_fitted_worsenings": [
                {"delta_px": delta, "source_sha256": source, "order": order, "baseline_px": base, "selected_px": selected}
                for delta, source, order, base, selected in examples[-5:]
            ],
            "max_abs_aic_error": max(aic_errors, default=None),
            "max_abs_aicc_error": max(aicc_errors, default=None),
            "max_abs_bic_error": max(bic_errors, default=None),
            "max_abs_akaike_weight_sum_error": max(weight_errors, default=None),
            "information_parameter_count_errors": parameter_count_errors,
        },
        "folds": {
            "rows": fold_row_count,
            "fold_count_errors": fold_count_errors,
            "holdout_total_errors": holdout_count_errors,
            "invalid_membership_hashes": invalid_hashes,
            "failure_reasons": dict(sorted(fold_failures.items())),
        },
        "associations": {
            "rows": association_row_count,
            "images": len(association_by_source),
            "outcomes": dict(sorted(association_outcomes.items())),
            "by_radial_bin": {key: dict(sorted(value.items())) for key, value in sorted(association_by_radius.items())},
            "by_selected_order": {str(key): dict(sorted(value.items())) for key, value in sorted(association_by_order.items())},
            "image_net_counts": dict(sorted(net_counts.items())),
            "extension_images": len(extension_image_net),
            "extension_image_net_counts": dict(sorted(extension_net_counts.items())),
            "extension_outcomes": dict(sorted(extension_association_outcomes.items())),
            "extension_by_radial_bin": {
                key: dict(sorted(value.items()))
                for key, value in sorted(extension_association_by_radius.items())
            },
            "extension_net_gain_quartiles": quantiles(list(extension_image_net.values())),
            "net_gain_total": sum(image_net.values()),
            "net_gain_quartiles": quantiles(list(image_net.values())),
            "edge_net_gain_radius_ge_0_75": edge_gains - edge_losses,
            "edge_gained": edge_gains,
            "edge_lost": edge_losses,
            "common_delta_arcmin_quartiles": quantiles(common_deltas),
            "edge_common_delta_arcmin_quartiles": quantiles(edge_common_deltas),
            "gained_selected_residual_arcmin_quartiles": quantiles(gained_selected_residuals),
            "extension_common_delta_arcmin_quartiles": quantiles(extension_common_deltas),
            "extension_outer_common_delta_arcmin_quartiles": quantiles(extension_outer_common_deltas),
        },
        "planets": {
            "rows": planet_row_count,
            "images": len(planet_by_source),
            "classifications": dict(sorted(planet_classifications.items())),
            "gate_crossings": dict(sorted(planet_crossings.items())),
            "edge_gate_crossings_radius_ge_0_75": dict(sorted(planet_crossings_edge.items())),
            "gate_crossings_by_radial_bin": {
                key: dict(sorted(value.items()))
                for key, value in sorted(planet_crossings_by_radius.items())
            },
            "classifications_by_radial_bin": {
                key: dict(sorted(value.items()))
                for key, value in sorted(planet_classifications_by_radius.items())
            },
            "gate_crossings_by_identity_type": {
                key: dict(sorted(value.items())) for key, value in sorted(planet_by_type.items())
            },
            "extension_images": len(planet_image_net),
            "extension_classifications": dict(sorted(extension_planet_classifications.items())),
            "extension_gate_crossings": dict(sorted(extension_planet_crossings.items())),
            "extension_image_net_gate_crossing_counts": dict(sorted(planet_image_net_counts.items())),
            "extension_image_net_gate_crossing_quartiles": quantiles(list(planet_image_net.values())),
            "separation_delta_arcmin_quartiles": quantiles(planet_deltas),
            "edge_separation_delta_arcmin_quartiles": quantiles(edge_planet_deltas),
            "extension_separation_delta_arcmin_quartiles": quantiles(extension_planet_deltas),
            "extension_outer_separation_delta_arcmin_quartiles": quantiles(extension_outer_planet_deltas),
        },
        "operational": {
            "rows": operational_rows,
            "association_gate_missing": association_gate_missing,
            "planet_gate_missing": planet_gate_missing,
            "camera_decode_errors": camera_decode_errors,
            "selected_coefficient_errors": selected_coefficient_errors,
            "association_gate_mismatches": association_gate_mismatches,
            "failure_reasons": dict(sorted(operational_failure_reasons.items())),
            "selected_minus_baseline_rms_px_quartiles": quantiles(robust_selected_delta_px),
            "extension_selected_minus_baseline_rms_px_quartiles": quantiles(extension_robust_selected_delta_px),
            "extension_selected_minus_baseline_rms_arcmin_quartiles": quantiles(extension_robust_selected_delta_arcmin),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = audit(arguments.directory.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
