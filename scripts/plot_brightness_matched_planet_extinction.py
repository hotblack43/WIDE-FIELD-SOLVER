#!/usr/bin/env python3
"""Compare planet airmass slopes with stars of the same measured brightness."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.stats import theilslopes


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.plot_planet_photometry import (  # noqa: E402
    PLANET_COLOURS,
    _camera_marker_map,
)


CHANNELS = "RGB"
PLANET_MEASUREMENT_FILE = "planet_extinction_corrected_distance_measurements.csv"
OUTPUT_STEM = "planet_brightness_matched_stellar_extinction"
OUTPUT_FIELDS = (
    "night", "channel", "planet", "camera_label", "status",
    "minimum_measurements", "maximum_airmass",
    "planet_input_measurement_count", "planet_measurement_count",
    "planet_measurements_above_maximum_airmass", "planet_source_image_count",
    "planet_airmass_min", "planet_airmass_max", "planet_airmass_span",
    "planet_median_count_rate_adu_per_s",
    "planet_raw_slope_mag_per_airmass",
    "adopted_extinction_mag_per_airmass",
    "match_half_width_magnitude", "matched_star_count",
    "matched_star_measurement_count", "matched_star_count_rate_min_adu_per_s",
    "matched_star_count_rate_max_adu_per_s",
    "matched_star_median_slope_mag_per_airmass",
    "matched_star_q25_slope_mag_per_airmass",
    "matched_star_q75_slope_mag_per_airmass", "matched_source_images",
)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_stellar_measurements(path):
    """Load clean stellar aperture measurements, including non-reference stars."""
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if (
                row.get("loader_included") != "True"
                or row.get("saturated") != "False"
                or row.get("measurement_method") != "ordinary_aperture"
            ):
                continue
            airmass = _finite(row.get("airmass"))
            magnitude = _finite(row.get("machine_magnitude"))
            count_rate = _finite(row.get("count_rate_adu_per_s"))
            if (
                airmass is None or airmass <= 0.0
                or magnitude is None
                or count_rate is None or count_rate <= 0.0
                or not row.get("night")
                or not row.get("channel")
                or not row.get("source_sha256")
                or not row.get("star_id")
            ):
                continue
            rows.append({
                "night": row["night"],
                "channel": row["channel"],
                "source_sha256": row["source_sha256"],
                "catalogue_sha256": row.get("catalogue_sha256", ""),
                "star_id": row["star_id"],
                "airmass": airmass,
                "machine_magnitude": magnitude,
                "count_rate_adu_per_s": count_rate,
            })
    return rows


def load_planet_measurements(root):
    """Load valid raw planet measurements from the three corrected sidecars."""
    root = Path(root)
    rows = []
    for channel in CHANNELS:
        path = root / channel / PLANET_MEASUREMENT_FILE
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                airmass = _finite(row.get("planet_airmass"))
                magnitude = _finite(row.get("machine_magnitude"))
                count_rate = _finite(row.get("count_rate_adu_per_s"))
                adopted = _finite(
                    row.get("nightly_extinction_mag_per_airmass")
                )
                if (
                    airmass is None or airmass <= 0.0
                    or magnitude is None
                    or count_rate is None or count_rate <= 0.0
                    or not row.get("nightly_extinction_night")
                    or not row.get("planet")
                    or not row.get("camera_label")
                    or not row.get("source_sha256")
                ):
                    continue
                rows.append({
                    "nightly_extinction_night": row[
                        "nightly_extinction_night"
                    ],
                    "channel": channel,
                    "planet": row["planet"],
                    "camera_label": row["camera_label"],
                    "source_sha256": row["source_sha256"],
                    "planet_airmass": airmass,
                    "machine_magnitude": magnitude,
                    "count_rate_adu_per_s": count_rate,
                    "nightly_extinction_mag_per_airmass": adopted,
                })
    return rows


def _theil_sen_slope(rows, *, airmass_field):
    return float(theilslopes(
        [row["machine_magnitude"] for row in rows],
        [row[airmass_field] for row in rows],
    ).slope)


def measure_brightness_matched_extinction(
    stellar_rows,
    planet_rows,
    *,
    match_half_width_magnitude=0.5,
    min_measurements=10,
    min_airmass_span=0.5,
    maximum_airmass=5.0,
):
    """Measure raw planet and same-frame, brightness-matched stellar slopes."""
    if match_half_width_magnitude <= 0.0:
        raise ValueError("match_half_width_magnitude must be positive")
    if min_measurements < 2:
        raise ValueError("min_measurements must be at least two")
    if min_airmass_span <= 0.0:
        raise ValueError("min_airmass_span must be positive")
    if maximum_airmass <= 0.0:
        raise ValueError("maximum_airmass must be positive")

    stellar_by_night_channel_image = defaultdict(list)
    for row in stellar_rows:
        stellar_by_night_channel_image[
            (row["night"], row["channel"], row["source_sha256"])
        ].append(row)

    planet_groups = defaultdict(list)
    for row in planet_rows:
        planet_groups[
            (
                row["nightly_extinction_night"], row["channel"],
                row["planet"], row["camera_label"],
            )
        ].append(row)

    output = []
    for (night, channel, planet, camera), input_measurements in sorted(
        planet_groups.items()
    ):
        measurements = [
            row for row in input_measurements
            if row["planet_airmass"] <= maximum_airmass
        ]
        measurements = sorted(
            measurements,
            key=lambda row: (row["planet_airmass"], row["source_sha256"]),
        )
        planet_airmasses = np.asarray([
            row["planet_airmass"] for row in measurements
        ])
        planet_rates = np.asarray([
            row["count_rate_adu_per_s"] for row in measurements
        ])
        source_images = {row["source_sha256"] for row in measurements}
        planet_span = float(np.ptp(planet_airmasses)) if len(measurements) else 0.0
        result = {
            "night": night,
            "channel": channel,
            "planet": planet,
            "camera_label": camera,
            "status": "accepted",
            "minimum_measurements": min_measurements,
            "maximum_airmass": maximum_airmass,
            "planet_input_measurement_count": len(input_measurements),
            "planet_measurement_count": len(measurements),
            "planet_measurements_above_maximum_airmass": (
                len(input_measurements) - len(measurements)
            ),
            "planet_source_image_count": len(source_images),
            "planet_airmass_min": (
                float(np.min(planet_airmasses)) if len(measurements) else None
            ),
            "planet_airmass_max": (
                float(np.max(planet_airmasses)) if len(measurements) else None
            ),
            "planet_airmass_span": planet_span,
            "planet_median_count_rate_adu_per_s": (
                float(np.median(planet_rates)) if len(measurements) else None
            ),
            "planet_raw_slope_mag_per_airmass": None,
            "adopted_extinction_mag_per_airmass": None,
            "match_half_width_magnitude": match_half_width_magnitude,
            "matched_star_count": 0,
            "matched_star_measurement_count": 0,
            "matched_star_count_rate_min_adu_per_s": None,
            "matched_star_count_rate_max_adu_per_s": None,
            "matched_star_median_slope_mag_per_airmass": None,
            "matched_star_q25_slope_mag_per_airmass": None,
            "matched_star_q75_slope_mag_per_airmass": None,
            "matched_source_images": "",
        }
        adopted_values = [
            row.get("nightly_extinction_mag_per_airmass")
            for row in measurements
            if row.get("nightly_extinction_mag_per_airmass") is not None
        ]
        if adopted_values:
            result["adopted_extinction_mag_per_airmass"] = float(
                np.median(adopted_values)
            )
        if len(measurements) < min_measurements:
            result["status"] = "insufficient_planet_measurements"
            output.append(result)
            continue
        if planet_span < min_airmass_span:
            result["status"] = "insufficient_planet_airmass_span"
            output.append(result)
            continue

        result["planet_raw_slope_mag_per_airmass"] = _theil_sen_slope(
            measurements, airmass_field="planet_airmass"
        )
        candidates = defaultdict(dict)
        for source_image in source_images:
            for star in stellar_by_night_channel_image.get(
                (night, channel, source_image), ()
            ):
                if star["airmass"] > maximum_airmass:
                    continue
                star_key = (star.get("catalogue_sha256", ""), star["star_id"])
                candidates[star_key].setdefault(source_image, star)

        planet_rate = result["planet_median_count_rate_adu_per_s"]
        matched_slopes = []
        matched_rates = []
        matched_measurements = []
        for star_key in sorted(candidates):
            star_measurements = list(candidates[star_key].values())
            if len(star_measurements) < min_measurements:
                continue
            star_airmasses = [row["airmass"] for row in star_measurements]
            if max(star_airmasses) - min(star_airmasses) < min_airmass_span:
                continue
            median_rate = float(np.median([
                row["count_rate_adu_per_s"] for row in star_measurements
            ]))
            brightness_difference = abs(-2.5 * math.log10(
                median_rate / planet_rate
            ))
            if brightness_difference > match_half_width_magnitude:
                continue
            matched_rates.append(median_rate)
            matched_measurements.extend(star_measurements)
            matched_slopes.append(_theil_sen_slope(
                star_measurements, airmass_field="airmass"
            ))

        result["matched_star_count"] = len(matched_slopes)
        result["matched_star_measurement_count"] = len(matched_measurements)
        if not matched_slopes:
            result["status"] = "no_brightness_matched_stars"
            output.append(result)
            continue
        result.update({
            "matched_star_count_rate_min_adu_per_s": min(matched_rates),
            "matched_star_count_rate_max_adu_per_s": max(matched_rates),
            "matched_star_median_slope_mag_per_airmass": float(
                np.median(matched_slopes)
            ),
            "matched_star_q25_slope_mag_per_airmass": float(
                np.percentile(matched_slopes, 25.0)
            ),
            "matched_star_q75_slope_mag_per_airmass": float(
                np.percentile(matched_slopes, 75.0)
            ),
            "matched_source_images": ";".join(sorted({
                row["source_sha256"] for row in matched_measurements
            })),
        })
        output.append(result)
    return output


def build_figure(rows):
    """Build RGB comparisons of planet, matched-star, and adopted slopes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure, axes = plt.subplots(
        1, 3, figsize=(15.2, 6.2), constrained_layout=True
    )
    accepted = [row for row in rows if row["status"] == "accepted"]
    camera_markers = _camera_marker_map(accepted) if accepted else {}
    for axis, channel in zip(axes, CHANNELS):
        selected = [row for row in accepted if row["channel"] == channel]
        compared_values = []
        for row in selected:
            planet_slope = row["planet_raw_slope_mag_per_airmass"]
            matched_slope = row[
                "matched_star_median_slope_mag_per_airmass"
            ]
            adopted_slope = row["adopted_extinction_mag_per_airmass"]
            colour = PLANET_COLOURS.get(row["planet"], "#555555")
            marker = camera_markers[row["camera_label"]]
            lower = matched_slope - row[
                "matched_star_q25_slope_mag_per_airmass"
            ]
            upper = row[
                "matched_star_q75_slope_mag_per_airmass"
            ] - matched_slope
            axis.plot(
                [planet_slope, planet_slope], [matched_slope, adopted_slope],
                color="0.72", linewidth=0.7, alpha=0.45, zorder=1,
            )
            axis.errorbar(
                [planet_slope], [matched_slope], yerr=[[lower], [upper]],
                fmt=marker, markersize=5.5, color=colour,
                markeredgecolor="black", markeredgewidth=0.35,
                elinewidth=0.8, capsize=1.8, alpha=0.82, zorder=3,
            )
            if adopted_slope is not None:
                axis.scatter(
                    [planet_slope], [adopted_slope], marker="x", s=22,
                    color="0.35", linewidth=0.8, alpha=0.60, zorder=2,
                )
                compared_values.append(adopted_slope)
            compared_values.extend((planet_slope, matched_slope))
        if compared_values:
            low = min(compared_values)
            high = max(compared_values)
            padding = max(0.05, 0.06 * (high - low))
            lower_limit = low - padding
            upper_limit = high + padding
            axis.plot(
                [lower_limit, upper_limit], [lower_limit, upper_limit],
                color="black", linestyle="--", linewidth=1.0,
                label="equal planet and stellar slopes", zorder=0,
            )
            axis.set_xlim(lower_limit, upper_limit)
            axis.set_ylim(lower_limit, upper_limit)
        else:
            axis.text(
                0.5, 0.5, "No accepted matched sequences",
                transform=axis.transAxes, ha="center", va="center",
            )
        axis.axhline(0.0, color="0.55", linewidth=0.6)
        axis.axvline(0.0, color="0.55", linewidth=0.6)
        axis.grid(True, color="0.90", linewidth=0.5)
        axis.set_title(f"{channel}: {len(selected)} planet-night sequences")
        axis.set_xlabel("Raw planet slope [mag per airmass]")
        axis.set_ylabel("Matched stellar slope [mag per airmass]")

    method_handles = [
        Line2D(
            [], [], linestyle="none", marker="o", markersize=6,
            markerfacecolor="0.65", markeredgecolor="black",
            label="same-brightness stellar median (bars: star IQR)",
        ),
        Line2D(
            [], [], linestyle="none", marker="x", markersize=6,
            color="0.35", label="adopted all-reference-star nightly k",
        ),
        Line2D(
            [], [], linestyle="--", color="black",
            label="stellar slope = raw planet slope",
        ),
    ]
    planet_handles = [
        Line2D(
            [], [], linestyle="none", marker="o", markersize=6,
            markerfacecolor=PLANET_COLOURS.get(planet, "#555555"),
            markeredgecolor="black", label=planet,
        )
        for planet in sorted({row["planet"] for row in accepted})
    ]
    axes[0].legend(handles=method_handles, loc="best", fontsize=7.5)
    if planet_handles:
        figure.legend(
            handles=planet_handles, loc="outside lower center", ncol=6,
            title="Planet (colour)", fontsize=8,
        )
    figure.suptitle(
        "Raw planet slopes versus stellar slopes at the same measured brightness\n"
        "Exact shared frames; ±0.5-mag count-rate match; "
        "N ≥ 10 and airmass ≤ 5",
        fontsize=13,
    )
    return figure, axes


def write_outputs(rows, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / f"{OUTPUT_STEM}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=OUTPUT_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    figure, _ = build_figure(rows)
    pdf_path = output / f"{OUTPUT_STEM}.pdf"
    figure.savefig(pdf_path, dpi=180)
    import matplotlib.pyplot as plt
    plt.close(figure)

    accepted = [row for row in rows if row["status"] == "accepted"]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "method": (
            "For each planet/night/channel/camera sequence, select unsaturated "
            "ordinary-aperture stars from the exact same image hashes whose "
            "per-sequence median count rate is within 0.5 magnitude of the "
            "planet median. Retain only airmass <= 5 and require at least 10 "
            "retained measurements plus 0.5 airmass span for both the planet "
            "and each star. Fit each raw magnitude-airmass slope by Theil-Sen "
            "and compare the median stellar slope with the raw planet slope."
        ),
        "sequence_count": len(rows),
        "accepted_sequence_count": len(accepted),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "accepted_by_channel": {
            channel: sum(row["channel"] == channel for row in accepted)
            for channel in CHANNELS
        },
        "outputs": {"csv": str(csv_path), "pdf": str(pdf_path)},
    }
    (output / f"{OUTPUT_STEM}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compare raw planet airmass slopes with same-frame stars of the "
            "same measured count rate."
        )
    )
    parser.add_argument("--stellar-measurements", type=Path, required=True)
    parser.add_argument("--planet-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    stellar_rows = load_stellar_measurements(args.stellar_measurements)
    planet_rows = load_planet_measurements(args.planet_root)
    rows = measure_brightness_matched_extinction(stellar_rows, planet_rows)
    summary = write_outputs(rows, args.output)
    print(
        f"Wrote {summary['accepted_sequence_count']} accepted brightness-matched "
        f"planet/star sequences to {args.output / (OUTPUT_STEM + '.pdf')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
