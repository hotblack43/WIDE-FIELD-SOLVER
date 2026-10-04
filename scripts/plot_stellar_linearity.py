#!/usr/bin/env python3
"""Test stellar count-rate linearity after atmospheric-extinction correction."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


AUDIT_FILE = "calibration_star_measurements.csv"
CORRECTED_FILE = "corrected_stellar_photometry.csv"
CHANNELS = "BGR"
CATALOGUE_FIELDS = {
    "B": ("phot_bp_mean_mag", "Gaia BP"),
    "G": ("phot_g_mean_mag", "Gaia G"),
    "R": ("phot_rp_mean_mag", "Gaia RP"),
}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _key(row):
    return (
        row.get("night", ""),
        row.get("channel", ""),
        row.get("source_sha256", ""),
        row.get("catalogue_sha256", ""),
        row.get("star_id", ""),
    )


def _load_gaia_magnitudes(catalogue_path):
    magnitudes = {}
    with Path(catalogue_path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            source_id = row.get("source_id", "")
            if not source_id:
                continue
            values = {
                channel: _finite(row.get(field))
                for channel, (field, _) in CATALOGUE_FIELDS.items()
            }
            magnitudes[source_id] = values
    return magnitudes


def load_linearity_measurements(audit_path, corrected_path, catalogue_path):
    """Return clean fit measurements expressed as normalized corrected counts."""
    included = set()
    with Path(audit_path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if (
                row.get("included_in_adopted_fit") == "True"
                and row.get("saturated") == "False"
                and row.get("measurement_method") == "ordinary_aperture"
            ):
                included.add(_key(row))

    gaia_magnitudes = _load_gaia_magnitudes(catalogue_path)
    output = []
    with Path(corrected_path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if _key(row) not in included or row.get("status") != "accepted":
                continue
            star_id = row.get("star_id", "")
            if not star_id.startswith("Gaia DR3 "):
                continue
            source_id = star_id.removeprefix("Gaia DR3 ")
            channel = row.get("channel", "")
            catalogue_magnitude = gaia_magnitudes.get(source_id, {}).get(channel)
            count_rate = _finite(row.get("count_rate_adu_per_s"))
            airmass = _finite(row.get("airmass"))
            extinction = _finite(row.get("extinction_mag_per_airmass"))
            zero_point = _finite(row.get("zero_point_magnitude"))
            if (
                catalogue_magnitude is None
                or count_rate is None
                or count_rate <= 0.0
                or airmass is None
                or extinction is None
                or zero_point is None
            ):
                continue
            corrected_log_count = math.log10(count_rate) + 0.4 * extinction * airmass
            normalized_log_count = corrected_log_count + 0.4 * zero_point
            output.append({
                "night": row["night"],
                "channel": channel,
                "source_sha256": row["source_sha256"],
                "star_id": star_id,
                "catalogue_magnitude": catalogue_magnitude,
                "catalogue_passband": CATALOGUE_FIELDS[channel][1],
                "count_rate_adu_per_s": count_rate,
                "airmass": airmass,
                "extinction_mag_per_airmass": extinction,
                "zero_point_magnitude": zero_point,
                "extinction_corrected_log10_count_rate": corrected_log_count,
                "normalized_extinction_corrected_log10_count_rate": (
                    normalized_log_count
                ),
                "extinction_corrected_machine_magnitude": (
                    -2.5 * normalized_log_count
                ),
                "calibrated_residual_magnitude": (
                    -2.5 * normalized_log_count - catalogue_magnitude
                ),
            })
    return output


def _binned_medians(magnitudes, residuals, width=0.25):
    if len(magnitudes) == 0:
        return [], [], [], []
    magnitudes = np.asarray(magnitudes)
    residuals = np.asarray(residuals)
    first = math.floor(float(magnitudes.min()) / width) * width
    last = math.ceil(float(magnitudes.max()) / width) * width + width
    edges = np.arange(first, last + width / 2.0, width)
    centres, medians, lower, upper = [], [], [], []
    for low, high in zip(edges[:-1], edges[1:]):
        selected = residuals[(magnitudes >= low) & (magnitudes < high)]
        if selected.size == 0:
            continue
        centre = float(np.median(magnitudes[(magnitudes >= low) & (magnitudes < high)]))
        q25, median, q75 = np.percentile(selected, [25.0, 50.0, 75.0])
        centres.append(centre)
        medians.append(float(median))
        lower.append(float(median - q25))
        upper.append(float(q75 - median))
    return centres, medians, lower, upper


def build_figure(rows):
    """Build B/G/R count-rate relations with residual panels underneath."""
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(13.2, 8.4), constrained_layout=True)
    grid = figure.add_gridspec(2, 3, height_ratios=(2.25, 1.0))
    count_axes = []
    residual_axes = []
    for index, channel in enumerate(CHANNELS):
        count_axis = figure.add_subplot(grid[0, index])
        residual_axis = figure.add_subplot(grid[1, index], sharex=count_axis)
        count_axes.append(count_axis)
        residual_axes.append(residual_axis)
        selected = [row for row in rows if row["channel"] == channel]
        x = np.asarray([row["catalogue_magnitude"] for row in selected])
        log_count = np.asarray([
            row["normalized_extinction_corrected_log10_count_rate"]
            for row in selected
        ])
        machine_magnitude = -2.5 * log_count
        residual = np.asarray([
            row["calibrated_residual_magnitude"] for row in selected
        ])
        if selected:
            fixed_slope_intercept = float(np.median(machine_magnitude - x))
            reference_magnitude = fixed_slope_intercept + x
            residual = machine_magnitude - reference_magnitude
            count_axis.hexbin(
                x, machine_magnitude, gridsize=75, mincnt=1, bins="log",
                cmap="viridis",
                linewidths=0.0, rasterized=True,
            )
            line_x = np.asarray([float(x.min()), float(x.max())])
            count_axis.plot(
                line_x, fixed_slope_intercept + line_x,
                color="black", linewidth=1.4,
                label=r"linear detector: slope $+1$",
            )
            residual_axis.scatter(
                x, residual, s=1.4, color="0.35", alpha=0.08,
                edgecolors="none", rasterized=True,
            )
            centres, medians, lower, upper = _binned_medians(x, residual)
            residual_axis.errorbar(
                centres, medians, yerr=[lower, upper], fmt="o-", markersize=3.2,
                linewidth=1.2, color="#d55e00", capsize=2,
                label="0.25-mag-bin median ± IQR",
            )
        else:
            count_axis.text(
                0.5, 0.5, "No accepted measurements", transform=count_axis.transAxes,
                ha="center", va="center",
            )
        count_axis.set_title(
            f"{channel} machine mag vs {CATALOGUE_FIELDS[channel][1]}  "
            f"(n={len(selected):,})"
        )
        count_axis.grid(True, color="0.88", linewidth=0.5)
        residual_axis.grid(True, color="0.88", linewidth=0.5)
        residual_axis.axhline(0.0, color="black", linewidth=1.0)
        residual_axis.set_xlabel(
            f"{CATALOGUE_FIELDS[channel][1]} catalogue magnitude [mag]"
        )
        if index == 0:
            count_axis.set_ylabel(
                "Extinction-corrected machine magnitude\n"
                "(zero-point normalized)"
            )
            residual_axis.set_ylabel("Residual from fixed +1 slope [mag]")
        count_axis.tick_params(labelbottom=False)
        count_axis.legend(loc="lower left", fontsize=8)
        residual_axis.legend(loc="best", fontsize=8)

    figure.suptitle(
        "Unsaturated calibration stars used in the adopted extinction fits\n"
        "Nightly zero points align observing nights",
        fontsize=13,
    )
    return figure, {"count": count_axes, "residual": residual_axes}


def write_plot(rows, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, _ = build_figure(rows)
    figure.savefig(output_path, dpi=180)
    import matplotlib.pyplot as plt
    plt.close(figure)

    channel_counts = {
        channel: sum(row["channel"] == channel for row in rows)
        for channel in CHANNELS
    }
    summary = {
        "measurement_count": len(rows),
        "channels": channel_counts,
        "selection": (
            "Gaia stars with BP/G/RP photometry; unsaturated ordinary-aperture "
            "measurements included in the adopted nightly extinction fit"
        ),
        "relation": (
            "-2.5*log10(count_rate) - k*airmass - zero_point versus Gaia "
            "BP/G/RP catalogue magnitude for B/G/R respectively; "
            "linear-detector expectation has fixed slope +1"
        ),
    }
    summary_path = output_path.with_name(f"{output_path.stem}_summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Plot extinction-corrected stellar count rate against catalogue "
            "magnitude to diagnose detector nonlinearity."
        )
    )
    parser.add_argument(
        "--input-root", type=Path, required=True,
        help="Directory containing nightly-extinction calibration CSV files.",
    )
    parser.add_argument(
        "--catalogue", type=Path, required=True,
        help="Full Gaia source CSV containing G, BP, and RP magnitudes.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = load_linearity_measurements(
        args.input_root / AUDIT_FILE,
        args.input_root / CORRECTED_FILE,
        args.catalogue,
    )
    summary = write_plot(rows, args.output)
    print(
        f"Wrote {summary['measurement_count']} stellar measurements to "
        f"{args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
