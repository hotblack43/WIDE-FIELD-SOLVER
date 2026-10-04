#!/usr/bin/env python3
"""Use natural atmospheric attenuation to test bright-star response."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import lsqr


CHANNELS = "BGR"
OUTPUT_FIELDS = (
    "night", "channel", "source_sha256", "star_id", "airmass",
    "predicted_machine_magnitude", "predicted_count_rate_adu_per_s",
    "observed_machine_magnitude", "residual_magnitude", "sample_role",
)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_measurements(path):
    """Load only unsaturated aperture rows used by the adopted nightly fit."""
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if (
                row.get("included_in_adopted_fit") != "True"
                or row.get("saturated") != "False"
                or row.get("measurement_method") != "ordinary_aperture"
            ):
                continue
            rate = _finite(row.get("count_rate_adu_per_s"))
            magnitude = _finite(row.get("machine_magnitude"))
            airmass = _finite(row.get("airmass"))
            if (
                rate is None or rate <= 0.0 or magnitude is None
                or airmass is None or airmass <= 0.0
            ):
                continue
            rows.append({
                "night": row["night"],
                "channel": row["channel"],
                "source_sha256": row["source_sha256"],
                "star_id": row["star_id"],
                "airmass": airmass,
                "machine_magnitude": magnitude,
                "count_rate_adu_per_s": rate,
            })
    return rows


def _fit_faint_control_model(
    rows,
    *,
    control_max_count_rate,
    min_controls_per_image,
    robust_scale=0.1,
):
    by_star = defaultdict(list)
    for row in rows:
        by_star[row["star_id"]].append(row)
    control_ids = {
        star_id
        for star_id, measurements in by_star.items()
        if max(row["count_rate_adu_per_s"] for row in measurements)
        <= control_max_count_rate
    }
    control_count_by_image = defaultdict(set)
    for row in rows:
        if row["star_id"] in control_ids:
            control_count_by_image[row["source_sha256"]].add(row["star_id"])
    image_ids = sorted(
        source
        for source, stars in control_count_by_image.items()
        if len(stars) >= min_controls_per_image
    )
    image_set = set(image_ids)
    selected = [
        row for row in rows
        if row["star_id"] in control_ids
        and row["source_sha256"] in image_set
    ]
    star_ids = sorted({row["star_id"] for row in selected})
    if len(image_ids) < 2 or len(star_ids) < min_controls_per_image:
        return None

    star_index = {star_id: index for index, star_id in enumerate(star_ids)}
    reference_image = image_ids[0]
    fitted_images = image_ids[1:]
    image_index = {
        source: len(star_ids) + index
        for index, source in enumerate(fitted_images)
    }
    extinction_index = len(star_ids) + len(fitted_images)
    row_indices = []
    column_indices = []
    values = []
    observed = np.asarray([row["machine_magnitude"] for row in selected])
    for index, row in enumerate(selected):
        row_indices.append(index)
        column_indices.append(star_index[row["star_id"]])
        values.append(1.0)
        if row["source_sha256"] != reference_image:
            row_indices.append(index)
            column_indices.append(image_index[row["source_sha256"]])
            values.append(1.0)
        row_indices.append(index)
        column_indices.append(extinction_index)
        values.append(row["airmass"])
    design = csr_matrix(
        (values, (row_indices, column_indices)),
        shape=(len(selected), extinction_index + 1),
    )
    coefficients = lsqr(design, observed, atol=1e-11, btol=1e-11)[0]
    for _ in range(12):
        residual = observed - design @ coefficients
        root_weight = np.power(
            1.0 + np.square(residual / robust_scale), -0.25
        )
        weighted_design = design.multiply(root_weight[:, np.newaxis])
        updated = lsqr(
            weighted_design,
            observed * root_weight,
            atol=1e-11,
            btol=1e-11,
        )[0]
        if np.max(np.abs(updated - coefficients)) < 1e-10:
            coefficients = updated
            break
        coefficients = updated

    residual = observed - design @ coefficients
    offsets = {reference_image: 0.0}
    offsets.update({
        source: float(coefficients[index])
        for source, index in image_index.items()
    })
    return {
        "status": "accepted",
        "extinction_mag_per_airmass": float(coefficients[extinction_index]),
        "image_offsets": offsets,
        "control_star_count": len(star_ids),
        "control_measurement_count": len(selected),
        "image_count": len(image_ids),
        "control_residual_rms_magnitude": float(
            np.sqrt(np.mean(np.square(residual)))
        ),
    }


def run_natural_attenuation_test(
    rows,
    *,
    control_max_count_rate=3000.0,
    min_controls_per_image=20,
    min_observations_per_star=10,
    min_airmass_span=1.0,
):
    """Predict low-airmass bright-star measurements from held-out faint controls."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["night"], row["channel"])].append(row)
    test_rows = []
    fit_rows = []
    for (night, channel), group in sorted(grouped.items()):
        model = _fit_faint_control_model(
            group,
            control_max_count_rate=control_max_count_rate,
            min_controls_per_image=min_controls_per_image,
        )
        if model is None:
            fit_rows.append({
                "night": night, "channel": channel,
                "status": "insufficient_faint_controls",
            })
            continue
        image_offsets = model.pop("image_offsets")
        extinction = model["extinction_mag_per_airmass"]
        tested_stars = 0
        by_star = defaultdict(list)
        for row in group:
            if row["source_sha256"] in image_offsets:
                by_star[row["star_id"]].append(row)
        for star_id, measurements in sorted(by_star.items()):
            if max(row["count_rate_adu_per_s"] for row in measurements) <= control_max_count_rate:
                continue
            if len(measurements) < min_observations_per_star:
                continue
            airmasses = np.asarray([row["airmass"] for row in measurements])
            if float(airmasses.max() - airmasses.min()) < min_airmass_span:
                continue
            lower, upper = np.quantile(airmasses, [1.0 / 3.0, 2.0 / 3.0])
            anchor = [row for row in measurements if row["airmass"] >= upper]
            tests = [row for row in measurements if row["airmass"] <= lower]
            if len(anchor) < 3 or len(tests) < 3:
                continue
            intercept = float(np.median([
                row["machine_magnitude"]
                - image_offsets[row["source_sha256"]]
                - extinction * row["airmass"]
                for row in anchor
            ]))
            tested_stars += 1
            for row in tests:
                predicted = (
                    intercept
                    + image_offsets[row["source_sha256"]]
                    + extinction * row["airmass"]
                )
                test_rows.append({
                    "night": night,
                    "channel": channel,
                    "source_sha256": row["source_sha256"],
                    "star_id": star_id,
                    "airmass": row["airmass"],
                    "predicted_machine_magnitude": predicted,
                    "predicted_count_rate_adu_per_s": 10.0 ** (-0.4 * predicted),
                    "observed_machine_magnitude": row["machine_magnitude"],
                    "residual_magnitude": row["machine_magnitude"] - predicted,
                    "sample_role": "low_airmass_test",
                })
        fit_rows.append({
            "night": night,
            "channel": channel,
            "status": "accepted",
            **model,
            "tested_bright_star_count": tested_stars,
        })
    return test_rows, fit_rows


def _star_night_points(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["night"], row["channel"], row["star_id"])].append(row)
    return [
        {
            "night": key[0], "channel": key[1], "star_id": key[2],
            "predicted_count_rate_adu_per_s": float(np.median([
                row["predicted_count_rate_adu_per_s"] for row in group
            ])),
            "residual_magnitude": float(np.median([
                row["residual_magnitude"] for row in group
            ])),
        }
        for key, group in sorted(grouped.items())
    ]


def _binned_star_medians(points, bin_count=9):
    if not points:
        return [], [], [], []
    rates = np.asarray([row["predicted_count_rate_adu_per_s"] for row in points])
    residuals = np.asarray([row["residual_magnitude"] for row in points])
    edges = np.geomspace(float(rates.min()), float(rates.max()) * 1.000001, bin_count + 1)
    centres, medians, lower, upper = [], [], [], []
    for low, high in zip(edges[:-1], edges[1:]):
        selected = residuals[(rates >= low) & (rates < high)]
        if selected.size == 0:
            continue
        q25, median, q75 = np.percentile(selected, [25.0, 50.0, 75.0])
        centres.append(math.sqrt(low * high))
        medians.append(float(median))
        lower.append(float(median - q25))
        upper.append(float(q75 - median))
    return centres, medians, lower, upper


def build_figure(rows, *, control_max_count_rate=3000.0):
    """Build one shared-scale B/G/R residual-versus-predicted-count figure."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(
        1, 3, figsize=(13.4, 5.2), sharex=True, sharey=True,
        constrained_layout=True,
    )
    star_points = _star_night_points(rows)
    for axis, channel in zip(axes, CHANNELS):
        measurements = [row for row in rows if row["channel"] == channel]
        points = [row for row in star_points if row["channel"] == channel]
        axis.scatter(
            [row["predicted_count_rate_adu_per_s"] for row in measurements],
            [row["residual_magnitude"] for row in measurements],
            s=3, color="0.35", alpha=0.10, edgecolors="none", rasterized=True,
            label="held-out measurements",
        )
        centres, medians, lower, upper = _binned_star_medians(points)
        axis.errorbar(
            centres, medians, yerr=[lower, upper], fmt="o-", markersize=4,
            linewidth=1.4, capsize=2, color="#d55e00",
            label="star-night medians ± IQR",
        )
        axis.axhline(0.0, color="black", linewidth=1.0)
        axis.axvline(
            control_max_count_rate,
            color="#0072b2", linestyle="--", linewidth=1.0,
            label="faint-control ceiling",
        )
        axis.set_xscale("log")
        axis.grid(True, color="0.88", linewidth=0.5)
        axis.set_title(
            f"{channel}: {len(measurements):,} tests; "
            f"{len({(row['night'], row['star_id']) for row in points}):,} star-nights"
        )
        axis.set_xlabel("Predicted count rate [ADU s⁻¹]")
    axes[0].set_ylabel("Observed − predicted machine magnitude [mag]")
    axes[0].legend(loc="best", fontsize=8)
    figure.suptitle(
        "MMTO same-star natural-attenuation test\n"
        "Positive residuals indicate fewer counts than the faint-control model predicts",
        fontsize=13,
    )
    return figure, axes


def write_outputs(rows, fits, output_path, *, control_max_count_rate=3000.0):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.with_suffix(".csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    figure, _ = build_figure(
        rows, control_max_count_rate=control_max_count_rate
    )
    figure.savefig(output_path, dpi=180)
    import matplotlib.pyplot as plt
    plt.close(figure)

    star_points = _star_night_points(rows)
    rng = np.random.default_rng(20261004)
    channel_high_signal = {}
    for channel in CHANNELS:
        residuals = np.asarray([
            row["residual_magnitude"] for row in star_points
            if row["channel"] == channel
            and row["predicted_count_rate_adu_per_s"] >= 5000.0
        ])
        if residuals.size:
            median = float(np.median(residuals))
            bootstrap = np.median(
                rng.choice(
                    residuals,
                    size=(10000, residuals.size),
                    replace=True,
                ),
                axis=1,
            )
            interval = [float(value) for value in np.percentile(
                bootstrap, [2.5, 97.5]
            )]
            ratio = 10.0 ** (-0.4 * median)
        else:
            median = None
            interval = []
            ratio = None
        channel_high_signal[channel] = {
            "minimum_predicted_count_rate_adu_per_s": 5000.0,
            "star_night_count": int(residuals.size),
            "median_residual_magnitude": median,
            "bootstrap_95_percent_interval_magnitude": interval,
            "observed_to_predicted_count_ratio": ratio,
        }
    summary = {
        "method": (
            "faint held-out stars fit per-night extinction and per-image offsets; "
            "the high-airmass third anchors each bright star and the low-airmass "
            "third is tested"
        ),
        "control_max_count_rate_adu_per_s": control_max_count_rate,
        "measurement_count": len(rows),
        "channel_measurements": {
            channel: sum(row["channel"] == channel for row in rows)
            for channel in CHANNELS
        },
        "channel_star_nights": {
            channel: sum(row["channel"] == channel for row in star_points)
            for channel in CHANNELS
        },
        "channel_high_signal": channel_high_signal,
        "channel_median_residual_above_5000_adu_per_s": {
            channel: (
                float(np.median([
                    row["residual_magnitude"] for row in star_points
                    if row["channel"] == channel
                    and row["predicted_count_rate_adu_per_s"] >= 5000.0
                ]))
                if any(
                    row["channel"] == channel
                    and row["predicted_count_rate_adu_per_s"] >= 5000.0
                    for row in star_points
                ) else None
            )
            for channel in CHANNELS
        },
        "night_channel_fits": fits,
    }
    output_path.with_name(f"{output_path.stem}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Test bright-star photometric response using natural attenuation "
            "within the existing MMTO time series."
        )
    )
    parser.add_argument(
        "--measurements", type=Path, required=True,
        help="calibration_star_measurements.csv from nightly calibration",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control-max-count-rate", type=float, default=3000.0)
    args = parser.parse_args(argv)
    rows = load_measurements(args.measurements)
    tests, fits = run_natural_attenuation_test(
        rows, control_max_count_rate=args.control_max_count_rate
    )
    summary = write_outputs(
        tests,
        fits,
        args.output,
        control_max_count_rate=args.control_max_count_rate,
    )
    print(
        f"Wrote {summary['measurement_count']} held-out measurements to "
        f"{args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
