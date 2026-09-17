#!/usr/bin/env python3
"""Compare repeated Subaru instrumental colours with Gaia BP/G/RP colours."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sqlite3

BLIND_AIRMASS_SOURCES = frozenset(
    ("blind_photometric_zenith", "blind_centred_full_horizon_geometry")
)


@dataclass(frozen=True)
class ColourMeasurement:
    run_id: str
    source_path: str
    source_sha256: str
    catalogue_sha256: str
    star_id: str
    detection_id: str
    airmass: float
    machine_b_minus_g: float
    machine_g_minus_r: float
    machine_b_minus_r: float
    gaia_bp_minus_g: float
    gaia_g_minus_rp: float
    gaia_bp_minus_rp: float
    machine_r_minus_gaia_rp: float = math.nan
    machine_g_minus_gaia_g: float = math.nan
    machine_b_minus_gaia_bp: float = math.nan


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _gaia_colours(path: Path) -> dict[str, tuple[float, float, float]]:
    answer = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            g = _finite(row.get("phot_g_mean_mag"))
            bp = _finite(row.get("phot_bp_mean_mag"))
            rp = _finite(row.get("phot_rp_mean_mag"))
            if None not in (g, bp, rp):
                answer[row["source_id"]] = (g, bp, rp)
    return answer


def load_repeated_colour_rows(
    database: Path, gaia_catalogue: Path
) -> list[ColourMeasurement]:
    """Load finite RGB colours for Gaia stars present in two Subaru images."""

    gaia = _gaia_colours(gaia_catalogue)
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
              AND m.star_id LIKE 'Gaia DR3 %'
            ORDER BY r.recorded_at_utc, r.run_id, m.row_number
            """
        ).fetchall()

    latest: dict[tuple[str, str, str], ColourMeasurement] = {}
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
            values_json,
        ) = row
        try:
            provenance = json.loads(provenance_json)
            values = json.loads(values_json)
        except (TypeError, ValueError):
            continue
        if provenance.get("metadata_used") is not False:
            continue
        if provenance.get("airmass_source") not in BLIND_AIRMASS_SOURCES:
            continue
        if str(values.get("photometry_usable", "")).lower() != "true":
            continue
        if not source_sha256 or not catalogue_sha256:
            continue
        catalogue = gaia.get(star_id.removeprefix("Gaia DR3 "))
        if catalogue is None:
            continue
        r_mag = _finite(values.get("R_mag"))
        g_mag = _finite(values.get("G_mag"))
        b_mag = _finite(values.get("B_mag"))
        airmass = _finite(values.get("airmass"))
        if None in (r_mag, g_mag, b_mag, airmass):
            continue
        gaia_g, gaia_bp, gaia_rp = catalogue
        latest[(star_id, source_sha256, catalogue_sha256)] = ColourMeasurement(
            run_id=run_id,
            source_path=source_path,
            source_sha256=source_sha256,
            catalogue_sha256=catalogue_sha256,
            star_id=star_id,
            detection_id=detection_id or "",
            airmass=airmass,
            machine_b_minus_g=round(b_mag - g_mag, 12),
            machine_g_minus_r=round(g_mag - r_mag, 12),
            machine_b_minus_r=round(b_mag - r_mag, 12),
            gaia_bp_minus_g=round(gaia_bp - gaia_g, 12),
            gaia_g_minus_rp=round(gaia_g - gaia_rp, 12),
            gaia_bp_minus_rp=round(gaia_bp - gaia_rp, 12),
            machine_r_minus_gaia_rp=round(r_mag - gaia_rp, 12),
            machine_g_minus_gaia_g=round(g_mag - gaia_g, 12),
            machine_b_minus_gaia_bp=round(b_mag - gaia_bp, 12),
        )

    counts: dict[tuple[str, str], int] = {}
    for star_id, _source_sha256, catalogue_sha256 in latest:
        key = (star_id, catalogue_sha256)
        counts[key] = counts.get(key, 0) + 1
    return sorted(
        (
            row
            for row in latest.values()
            if counts[(row.star_id, row.catalogue_sha256)] >= 2
        ),
        key=lambda row: (row.catalogue_sha256, row.star_id, row.source_sha256),
    )



def select_well_observed(
    rows: list[ColourMeasurement], count: int = 9
) -> list[tuple[str, list[ColourMeasurement]]]:
    """Rank stars by usable observation count, then by airmass span."""

    grouped: dict[str, list[ColourMeasurement]] = {}
    for row in rows:
        grouped.setdefault(row.star_id, []).append(row)
    ranked = sorted(
        grouped.items(),
        key=lambda item: (
            -len(item[1]),
            -(max(row.airmass for row in item[1]) -
              min(row.airmass for row in item[1])),
            item[0],
        ),
    )
    return ranked[:count]


@dataclass(frozen=True)
class Summary:
    star_count: int
    measurement_count: int


COLOUR_SPECS = (
    (
        "BG",
        "BPG",
        "machine_b_minus_g",
        "gaia_bp_minus_g",
        "Machine B−G (mag)",
        "Gaia BP−G (mag)",
        "#6a3d9a",
    ),
    (
        "GR",
        "GRP",
        "machine_g_minus_r",
        "gaia_g_minus_rp",
        "Machine G−R (mag)",
        "Gaia G−RP (mag)",
        "#d95f02",
    ),
    (
        "BR",
        "BPRP",
        "machine_b_minus_r",
        "gaia_bp_minus_rp",
        "Machine B−R (mag)",
        "Gaia BP−RP (mag)",
        "#1b9e77",
    ),
)


def _plot_colour(
    path: Path,
    rows: list[ColourMeasurement],
    machine_field: str,
    gaia_field: str,
    machine_label: str,
    gaia_label: str,
    colour: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    x = np.asarray([getattr(row, gaia_field) for row in rows])
    y = np.asarray([getattr(row, machine_field) for row in rows])
    by_star: dict[tuple[str, str], list[ColourMeasurement]] = {}
    for row in rows:
        by_star.setdefault((row.catalogue_sha256, row.star_id), []).append(row)
    median_x = np.asarray(
        [np.median([getattr(row, gaia_field) for row in group])
         for group in by_star.values()]
    )
    median_y = np.asarray(
        [np.median([getattr(row, machine_field) for row in group])
         for group in by_star.values()]
    )

    fig, ax = plt.subplots(figsize=(9, 7), constrained_layout=True)
    ax.scatter(
        x, y, s=4, color=colour, alpha=0.12, linewidths=0, rasterized=True,
        label="individual Subaru observations",
    )
    ax.scatter(
        median_x, median_y, s=12, color=colour, alpha=0.5,
        edgecolors="black", linewidths=0.2, rasterized=True,
        label="per-star medians",
    )
    annotation = (
        f"{len(by_star):,} repeated Gaia stars · {len(rows):,} observations"
    )
    if len(median_x) >= 2 and float(np.ptp(median_x)) > 0:
        slope, intercept = np.polyfit(median_x, median_y, 1)
        fitted = intercept + slope * median_x
        rms = float(np.sqrt(np.mean((median_y - fitted) ** 2)))
        span = np.linspace(float(x.min()), float(x.max()), 200)
        ax.plot(
            span, intercept + slope * span, color="black", linewidth=1.3,
            label="OLS on per-star medians",
        )
        annotation += (
            f"\nmedian-star OLS: machine = {intercept:.3f} + "
            f"{slope:.3f} catalogue\nRMS = {rms:.3f} mag"
        )
    ax.text(
        0.01, 0.99, annotation, transform=ax.transAxes, va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=.3", facecolor="white", edgecolor=".75",
                  alpha=.9),
    )
    ax.set_xlabel(gaia_label)
    ax.set_ylabel(machine_label)
    ax.set_title(f"Subaru repeated stars: {machine_label} vs {gaia_label}")
    ax.grid(alpha=0.2)
    ax.legend(loc="lower right", fontsize=8)
    fig.text(
        0.5, 0.01,
        "Each machine colour uses channels from the same image. Camera RGB and "
        "Gaia BP/G/RP are different passbands; equality is not expected.",
        ha="center", fontsize=8.5, color=".3",
    )
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _display_names(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {
        star_id: details["display_name"]
        for star_id, details in payload.items()
        if isinstance(details, dict) and details.get("display_name")
    }


def write_nine_star_airmass(
    rows: list[ColourMeasurement], output: Path
) -> list[tuple[str, list[ColourMeasurement]]]:
    """Plot R/RP, G/G and B/BP residuals for nine well-observed stars."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    selected = select_well_observed(rows, count=9)
    if len(selected) < 9:
        raise ValueError("fewer than nine repeated stars are available")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = _display_names(
        Path(__file__).resolve().parents[1] / "v6" / "data" / "display_names.json"
    )
    channels = (
        ("R−Gaia RP", "machine_r_minus_gaia_rp", "#c62828"),
        ("G−Gaia G", "machine_g_minus_gaia_g", "#2e7d32"),
        ("B−Gaia BP", "machine_b_minus_gaia_bp", "#1565c0"),
    )

    fig, axes = plt.subplots(3, 3, figsize=(15, 12), constrained_layout=True)
    table_rows = []
    for panel, (ax, (star_id, star_rows)) in enumerate(
        zip(axes.flat, selected), 1
    ):
        star_rows = sorted(star_rows, key=lambda row: row.airmass)
        x = np.asarray([row.airmass for row in star_rows])
        for label, field, colour in channels:
            y = np.asarray([getattr(row, field) for row in star_rows])
            ax.scatter(x, y, s=18, color=colour, alpha=.72, linewidths=0)
            slope_text = ""
            if len(x) >= 2 and float(np.ptp(x)) > 0:
                slope, intercept = np.polyfit(x, y, 1)
                span = np.linspace(float(x.min()), float(x.max()), 100)
                ax.plot(span, intercept + slope * span, color=colour, linewidth=1)
                slope_text = f"  k={slope:+.3f}"
            ax.plot([], [], color=colour, marker="o", linestyle="-",
                    label=f"{label}{slope_text}")
        title = names.get(star_id, f"Star {panel}")
        ax.set_title(
            f"{panel}. {title}  (N={len(star_rows)}, "
            f"ΔX={float(np.ptp(x)):.2f})",
            fontsize=10,
        )
        ax.set_xlabel("Airmass")
        ax.set_ylabel("Machine − equivalent Gaia magnitude")
        ax.grid(alpha=.2)
        ax.legend(fontsize=7, loc="best", framealpha=.9)
        for row in star_rows:
            table_rows.append({"panel": panel, **asdict(row)})

    fig.suptitle(
        "Nine best-observed Subaru stars: channel residual versus blind airmass\n"
        "Most usable observations, then widest airmass span; "
        "OLS slopes are diagnostics, not calibrated extinction",
        fontsize=14,
    )
    fig.savefig(
        output / "subaru_nine_well_observed_stars_airmass.png", dpi=180
    )
    plt.close(fig)

    with (output / "subaru_nine_well_observed_stars_airmass.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(table_rows[0]))
        writer.writeheader()
        writer.writerows(table_rows)
    return selected


def write_outputs(rows: list[ColourMeasurement], output: Path) -> Summary:
    """Write the repeated-star colour table and three comparison plots."""

    if not rows:
        raise ValueError("no repeated Subaru stars with finite Gaia colours")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "subaru_repeated_star_colours.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(asdict(rows[0])))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    for machine_code, gaia_code, machine_field, gaia_field, machine_label, gaia_label, colour in COLOUR_SPECS:
        _plot_colour(
            output
            / f"subaru_repeated_stars_machine_{machine_code}_vs_gaia_{gaia_code}.png",
            rows,
            machine_field,
            gaia_field,
            machine_label,
            gaia_label,
            colour,
        )
    if len({(row.catalogue_sha256, row.star_id) for row in rows}) >= 9:
        write_nine_star_airmass(rows, output)
    return Summary(
        star_count=len({(row.catalogue_sha256, row.star_id) for row in rows}),
        measurement_count=len(rows),
    )


def generate(database: Path, gaia_catalogue: Path, output: Path) -> Summary:
    rows = load_repeated_colour_rows(database, gaia_catalogue)
    return write_outputs(rows, output)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare repeated Subaru machine colours with Gaia colours."
    )
    parser.add_argument(
        "--database", type=Path, default=Path("results/stars.sqlite"),
        help="v6 run database (default: %(default)s)",
    )
    parser.add_argument(
        "--gaia-catalogue",
        type=Path,
        default=Path("v6/data/stars_gaia_dr3_g75.gaia-source.csv"),
        help="Gaia source photometry table (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/subaru-repeated-star-colours"),
        help="output directory (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = generate(args.database, args.gaia_catalogue, args.output)
    print(
        f"{summary.star_count:,} repeated Gaia stars; "
        f"{summary.measurement_count:,} Subaru observations"
    )
    print(f"Outputs: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
