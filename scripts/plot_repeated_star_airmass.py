#!/usr/bin/env python3
"""Plot repeated Subaru stellar photometry stored by the v6 run database."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile


CHANNELS = ("R", "G", "B")
BLIND_AIRMASS_SOURCES = frozenset(
    ("blind_photometric_zenith", "blind_centred_full_horizon_geometry")
)
CSV_FIELDS = (
    "run_id",
    "source_path",
    "source_sha256",
    "catalogue_sha256",
    "catalogue_label",
    "airmass_source",
    "metadata_used",
    "star_id",
    "detection_id",
    "channel",
    "airmass",
    "machine_magnitude",
    "catalogue_magnitude",
    "machine_minus_catalogue_mag",
    "altitude_deg",
    "source_class",
    "photometry_usable",
)


@dataclass(frozen=True)
class Measurement:
    """One finite channel measurement from one distinct source image."""

    run_id: str
    source_path: str
    source_sha256: str
    catalogue_sha256: str
    catalogue_label: str
    airmass_source: str
    metadata_used: bool
    star_id: str
    detection_id: str
    channel: str
    airmass: float
    machine_magnitude: float
    catalogue_magnitude: float
    machine_minus_catalogue_mag: float
    altitude_deg: float
    source_class: str
    photometry_usable: str


@dataclass(frozen=True)
class Summary:
    """Counts written by :func:`generate`, keyed by camera channel."""

    star_counts: dict[str, int]
    measurement_counts: dict[str, int]


def _finite(values: dict[str, str], key: str) -> float | None:
    try:
        value = float(values[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


@lru_cache(maxsize=None)
def catalogue_label(checksum: str) -> str:
    """Identify a solver catalogue by matching its saved content checksum."""

    data = Path(__file__).resolve().parents[1] / "v6" / "data"
    references = (
        (
            "stars_gaia_dr3_g75.csv",
            "Gaia DR3 G + bright Tycho-2 VT/Hipparcos V supplement",
        ),
        (
            "stars_tycho2_mag75.csv",
            "Tycho-2 VT + bright Hipparcos V supplement",
        ),
    )
    for filename, label in references:
        path = data / filename
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
            return label
    return "Unrecognized catalogue (see catalogue_sha256)"


def dense_limits(values: Sequence[float]) -> tuple[float, float]:
    """Return finite one- and ninety-nine-percent limits for a dense view."""

    import numpy as np

    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if not finite.size:
        raise ValueError("cannot determine limits without finite values")
    lower, upper = (float(value) for value in np.quantile(finite, (0.01, 0.99)))
    if lower == upper:
        padding = max(0.5, abs(lower) * 0.02)
        return lower - padding, upper + padding
    return lower, upper


def full_limits(values: Sequence[float]) -> tuple[float, float]:
    """Return the complete finite range, expanding a degenerate range."""

    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        raise ValueError("cannot determine limits without finite values")
    lower, upper = min(finite), max(finite)
    if lower == upper:
        padding = max(0.5, abs(lower) * 0.02)
        return lower - padding, upper + padding
    return lower, upper


def load_repeated_channel_rows(database: Path, channel: str) -> list[Measurement]:
    """Return finite rows for stars measured in at least two blind Subaru images."""

    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    database = Path(database).resolve()
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        raw_rows = db.execute(
            """
            SELECT r.run_id, r.recorded_at_utc, r.source_path, r.source_sha256,
                   r.catalogue_sha256, p.content, m.star_id, m.detection_id,
                   m.values_json
            FROM runs r
            JOIN products p ON p.run_id=r.run_id
                           AND p.product='photometry_summary.json'
            JOIN measurements m USING(run_id)
            WHERE r.exit_code=0
              AND lower(r.source_path) LIKE '%subaru%'
              AND m.product='stellar_photometry.csv'
              AND m.star_id IS NOT NULL
            ORDER BY r.recorded_at_utc, r.run_id, m.row_number
            """
        ).fetchall()

    latest_by_star_image: dict[tuple[str, str, str], Measurement] = {}
    for row in raw_rows:
        (
            run_id,
            _recorded,
            source_path,
            source_sha256,
            catalogue_sha256,
            provenance_json,
            star_id,
            detection_id,
            payload,
        ) = row
        try:
            provenance = json.loads(provenance_json)
            values = json.loads(payload)
        except (TypeError, ValueError):
            continue
        metadata_used = provenance.get("metadata_used")
        airmass_source = provenance.get("airmass_source")
        if metadata_used is not False or airmass_source not in BLIND_AIRMASS_SOURCES:
            continue
        if not source_sha256 or not catalogue_sha256:
            continue
        airmass = _finite(values, "airmass")
        machine_mag = _finite(values, f"{channel}_mag")
        catalogue_mag = _finite(values, "catalogue_magnitude")
        difference = _finite(values, f"{channel}_minus_catalogue_mag")
        altitude = _finite(values, "altitude_deg")
        if None in (airmass, machine_mag, catalogue_mag, difference, altitude):
            continue
        if airmass <= 0:
            continue
        latest_by_star_image[(star_id, source_sha256, catalogue_sha256)] = Measurement(
            run_id=run_id,
            source_path=source_path,
            source_sha256=source_sha256,
            catalogue_sha256=catalogue_sha256,
            catalogue_label=catalogue_label(catalogue_sha256),
            airmass_source=airmass_source,
            metadata_used=metadata_used,
            star_id=star_id,
            detection_id=detection_id or "",
            channel=channel,
            airmass=airmass,
            machine_magnitude=machine_mag,
            catalogue_magnitude=catalogue_mag,
            machine_minus_catalogue_mag=difference,
            altitude_deg=altitude,
            source_class=values.get("source_class", ""),
            photometry_usable=values.get("photometry_usable", ""),
        )

    image_count: dict[tuple[str, str], int] = {}
    for star_id, _source_sha256, catalogue_sha256 in latest_by_star_image:
        key = (star_id, catalogue_sha256)
        image_count[key] = image_count.get(key, 0) + 1
    return sorted(
        (
            measurement
            for measurement in latest_by_star_image.values()
            if image_count[(measurement.star_id, measurement.catalogue_sha256)] >= 2
        ),
        key=lambda item: (
            item.catalogue_sha256,
            item.star_id,
            item.airmass,
            item.source_sha256,
        ),
    )


def _write_table(path: Path, rows_by_channel: dict[str, list[Measurement]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for channel in CHANNELS:
            for row in rows_by_channel[channel]:
                writer.writerow({field: getattr(row, field) for field in CSV_FIELDS})


def _padded_limits(values: Sequence[float]) -> tuple[float, float]:
    lower, upper = dense_limits(values)
    padding = (upper - lower) * 0.03
    return lower - padding, upper + padding


def _plot_channel(path: Path, channel: str, rows: list[Measurement]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    import numpy as np

    if not rows:
        raise ValueError(f"no repeated finite {channel}-channel Subaru measurements")

    colours = {"R": "#c62828", "G": "#2e7d32", "B": "#1565c0"}
    colour = colours[channel]
    airmass = np.asarray([row.airmass for row in rows])
    difference = np.asarray([row.machine_minus_catalogue_mag for row in rows])
    by_star: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for row in rows:
        by_star.setdefault((row.catalogue_sha256, row.star_id), []).append(
            (row.airmass, row.machine_minus_catalogue_mag)
        )
    segments = [
        np.asarray(sorted(points))
        for points in by_star.values()
        if len(points) >= 2
    ]
    catalogues = sorted({row.catalogue_label for row in rows})
    catalogue_text = "; ".join(catalogues)

    fig, ax = plt.subplots(figsize=(10, 7), constrained_layout=True)
    ax.add_collection(
        LineCollection(segments, colors=colour, linewidths=0.25, alpha=0.045)
    )
    ax.scatter(
        airmass,
        difference,
        s=4,
        color=colour,
        alpha=0.18,
        linewidths=0,
        rasterized=True,
    )
    ax.set_xlim(*_padded_limits(airmass))
    ax.set_ylim(*_padded_limits(difference))
    ax.set_xlabel("Airmass from saved blind zenith solution")
    ax.set_ylabel(
        f"Uncalibrated {channel} machine magnitude − solver catalogue magnitude (mag)"
    )
    ax.set_title(f"Subaru repeated stars: {channel} channel")
    ax.text(
        0.01,
        0.99,
        f"{len(by_star):,} stars · {len(rows):,} measurements\n"
        f"Catalogue: {catalogue_text}\n"
        "Instrumental RGB is uncalibrated; passband mismatch, colour and "
        "vignetting add scatter.\n"
        "Faint lines join measurements of the same catalogue star.",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=8.5,
    )
    ax.grid(alpha=0.2)

    inset = ax.inset_axes([0.64, 0.08, 0.33, 0.28])
    inset.scatter(
        airmass,
        difference,
        s=2,
        color=colour,
        alpha=0.13,
        linewidths=0,
        rasterized=True,
    )
    inset.set_xlim(*full_limits(airmass))
    inset.set_ylim(*full_limits(difference))
    inset.set_title("Full data range", fontsize=8)
    inset.tick_params(labelsize=7)
    inset.grid(alpha=0.15)

    fig.savefig(path, dpi=180)
    plt.close(fig)


def generate(database: Path, output: Path) -> Summary:
    """Write a provenance table and separate R/G/B repeated-star plots."""

    output = Path(output)
    rows_by_channel = {
        channel: load_repeated_channel_rows(database, channel)
        for channel in CHANNELS
    }
    for channel, rows in rows_by_channel.items():
        if not rows:
            raise ValueError(
                f"no repeated finite {channel}-channel Subaru measurements"
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix=f".{output.name}."
    ) as temporary:
        staged = Path(temporary)
        _write_table(staged / "subaru_repeated_star_airmass.csv", rows_by_channel)
        for channel, rows in rows_by_channel.items():
            _plot_channel(
                staged / f"subaru_repeated_stars_{channel}_vs_airmass.png",
                channel,
                rows,
            )
        output.mkdir(parents=True, exist_ok=True)
        for product in staged.iterdir():
            os.replace(product, output / product.name)

    return Summary(
        star_counts={
            channel: len(
                {(row.catalogue_sha256, row.star_id) for row in rows}
            )
            for channel, rows in rows_by_channel.items()
        },
        measurement_counts={
            channel: len(rows) for channel, rows in rows_by_channel.items()
        },
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plot repeated Subaru machine-minus-catalogue magnitudes against "
            "saved blind airmass."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("results/stars.sqlite"),
        help="v6 run database (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/subaru-repeated-star-airmass"),
        help="output directory (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = generate(args.database, args.output)
    for channel in CHANNELS:
        print(
            f"{channel}: {summary.star_counts[channel]:,} repeated stars, "
            f"{summary.measurement_counts[channel]:,} measurements"
        )
    print(f"Outputs: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
