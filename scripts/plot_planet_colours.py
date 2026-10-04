#!/usr/bin/env python3
"""Plot matched planetary RGB colours after extinction and distance correction."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path


MEASUREMENT_FILE = "planet_extinction_corrected_distance_measurements.csv"
MAGNITUDE_FIELD = "extinction_corrected_distance_magnitude"
JOIN_FIELDS = (
    "run_id",
    "source_sha256",
    "observation_time_utc",
    "camera_label",
    "planet",
    "detection_id",
)
OUTPUT_FIELDS = [
    *JOIN_FIELDS,
    "hours_past_local_noon",
    "r_corrected_distance_magnitude",
    "g_corrected_distance_magnitude",
    "b_corrected_distance_magnitude",
    "b_minus_g",
    "b_minus_r",
]
PLANET_MARKERS = {
    "Mercury": "o",
    "Venus": "s",
    "Mars": "^",
    "Jupiter": "D",
    "Saturn": "v",
    "Uranus": "P",
    "Neptune": "X",
    "Ceres": "<",
    "Vesta": ">",
}
FALLBACK_MARKERS = ("h", "p", "*", "8")


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_key(row):
    return tuple(row.get(field, "") for field in JOIN_FIELDS)


def _load_channel(path, expected_channel):
    rows = {}
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("channel") != expected_channel:
                raise ValueError(
                    f"{path} contains channel {row.get('channel')!r}; "
                    f"expected {expected_channel!r}"
                )
            magnitude = _finite(row.get(MAGNITUDE_FIELD))
            hours = _finite(row.get("hours_past_local_noon"))
            if magnitude is None or hours is None:
                continue
            key = _row_key(row)
            if key in rows:
                raise ValueError(
                    f"duplicate {expected_channel}-channel planet measurement: {key}"
                )
            rows[key] = {**row, MAGNITUDE_FIELD: magnitude, "hours": hours}
    return rows


def load_colour_measurements(channel_paths):
    """Join exact R/G/B planet rows and compute B-G and B-R."""
    channels = {
        channel: _load_channel(channel_paths[channel], channel)
        for channel in "RGB"
    }
    complete_keys = set(channels["R"]) & set(channels["G"]) & set(channels["B"])
    measurements = []
    for key in sorted(complete_keys, key=lambda item: (item[2], item[4], item)):
        matched = {channel: channels[channel][key] for channel in "RGB"}
        hours = [matched[channel]["hours"] for channel in "RGB"]
        if max(hours) - min(hours) > 1e-9:
            raise ValueError(f"RGB rows disagree on hours past local noon: {key}")
        magnitudes = {
            channel: matched[channel][MAGNITUDE_FIELD] for channel in "RGB"
        }
        measurements.append({
            **dict(zip(JOIN_FIELDS, key)),
            "hours_past_local_noon": hours[0],
            "r_corrected_distance_magnitude": magnitudes["R"],
            "g_corrected_distance_magnitude": magnitudes["G"],
            "b_corrected_distance_magnitude": magnitudes["B"],
            "b_minus_g": magnitudes["B"] - magnitudes["G"],
            "b_minus_r": magnitudes["B"] - magnitudes["R"],
        })
    return measurements


def _marker_map(planets):
    marker_map = {}
    fallback_index = 0
    for planet in sorted(planets):
        marker = PLANET_MARKERS.get(planet)
        if marker is None:
            marker = FALLBACK_MARKERS[fallback_index % len(FALLBACK_MARKERS)]
            fallback_index += 1
        marker_map[planet] = marker
    return marker_map


def _padded_limits(values):
    low, high = min(values), max(values)
    span = high - low
    padding = 0.08 * span if span > 0.0 else max(abs(low) * 0.05, 0.05)
    return low - padding, high + padding


def build_figure(rows):
    """Build one data-scaled B-G versus B-R plot for every planet."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.lines import Line2D

    figure, axis = plt.subplots(figsize=(8.3, 7.1), constrained_layout=True)
    axis.set_xlabel("B − G [mag]")
    axis.set_ylabel("B − R [mag]")
    axis.set_title(
        "Planets: extinction- and distance-corrected colour–colour diagram"
    )
    axis.grid(True, color="0.88", linewidth=0.6, zorder=0)
    if not rows:
        axis.text(
            0.5,
            0.5,
            "No planet measurements have complete corrected R, G, and B data",
            transform=axis.transAxes,
            ha="center",
            va="center",
        )
        return figure, axis

    hours = [row["hours_past_local_noon"] for row in rows]
    hour_min, hour_max = min(hours), max(hours)
    if hour_min == hour_max:
        hour_min -= 0.5
        hour_max += 0.5
    norm = Normalize(vmin=hour_min, vmax=hour_max)
    colour_map = plt.get_cmap("viridis")
    markers = _marker_map({row["planet"] for row in rows})
    scatter = None
    for planet, marker in markers.items():
        points = [row for row in rows if row["planet"] == planet]
        scatter = axis.scatter(
            [row["b_minus_g"] for row in points],
            [row["b_minus_r"] for row in points],
            c=[row["hours_past_local_noon"] for row in points],
            cmap=colour_map,
            norm=norm,
            marker=marker,
            s=42,
            edgecolors="black",
            linewidths=0.35,
            alpha=0.82,
            zorder=2,
        )

    assert scatter is not None
    figure.colorbar(
        scatter,
        ax=axis,
        label="Hours past latest local noon (Arizona)",
        pad=0.02,
    )
    legend = [
        Line2D(
            [], [], linestyle="", marker=marker, markersize=7,
            markerfacecolor="0.65", markeredgecolor="black", markeredgewidth=0.5,
            label=f"{planet} (n={sum(row['planet'] == planet for row in rows)})",
        )
        for planet, marker in markers.items()
    ]
    axis.legend(handles=legend, title="Planet (symbol)", loc="best", frameon=True)
    axis.set_xlim(_padded_limits([row["b_minus_g"] for row in rows]))
    axis.set_ylim(_padded_limits([row["b_minus_r"] for row in rows]))
    return figure, axis


def write_outputs(rows, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "planet_colour_colour.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    figure, _ = build_figure(rows)
    figure.savefig(output / "planet_colour_colour.png", dpi=180)
    import matplotlib.pyplot as plt
    plt.close(figure)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "quantity": (
            "B-G versus B-R from extinction- and distance-corrected magnitudes"
        ),
        "magnitude_field": MAGNITUDE_FIELD,
        "measurement_count": len(rows),
        "planets": sorted({row["planet"] for row in rows}),
        "hours_past_local_noon_range": (
            [
                min(row["hours_past_local_noon"] for row in rows),
                max(row["hours_past_local_noon"] for row in rows),
            ]
            if rows else []
        ),
    }
    (output / "planet_colour_colour_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Plot B-G against B-R for planets with matched extinction- and "
            "distance-corrected RGB photometry."
        )
    )
    parser.add_argument(
        "--input-root", type=Path, required=True,
        help="Directory containing R/, G/, and B/ corrected measurement CSVs.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = {
        channel: args.input_root / channel / MEASUREMENT_FILE
        for channel in "RGB"
    }
    rows = load_colour_measurements(paths)
    summary = write_outputs(rows, args.output)
    print(
        f"Wrote {summary['measurement_count']} matched planet RGB points to "
        f"{args.output / 'planet_colour_colour.png'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
