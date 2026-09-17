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
    machine_r_mag: float = math.nan
    machine_g_mag: float = math.nan
    machine_b_mag: float = math.nan
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
            machine_r_mag=r_mag,
            machine_g_mag=g_mag,
            machine_b_mag=b_mag,
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


def select_bright_well_observed(
    rows: list[ColourMeasurement], count: int = 9,
    coverage_fraction: float = 0.6,
) -> list[tuple[str, list[ColourMeasurement]]]:
    """Choose bright stars after requiring substantial repeat coverage."""

    import numpy as np

    if not 0 < coverage_fraction <= 1:
        raise ValueError("coverage_fraction must be in (0, 1]")
    grouped: dict[str, list[ColourMeasurement]] = {}
    for row in rows:
        grouped.setdefault(row.star_id, []).append(row)
    if not grouped:
        return []
    minimum = math.ceil(
        coverage_fraction * max(len(star_rows) for star_rows in grouped.values())
    )
    ranked = []
    for star_id, star_rows in grouped.items():
        if len(star_rows) < minimum:
            continue
        gaia_g = [
            row.machine_g_mag - row.machine_g_minus_gaia_g
            for row in star_rows
            if math.isfinite(row.machine_g_mag)
            and math.isfinite(row.machine_g_minus_gaia_g)
        ]
        if not gaia_g:
            continue
        span = (max(row.airmass for row in star_rows)
                - min(row.airmass for row in star_rows))
        ranked.append(
            (float(np.median(gaia_g)), -len(star_rows), -span,
             star_id, star_rows)
        )
    ranked.sort(key=lambda item: item[:4])
    return [(star_id, star_rows) for *_rank, star_id, star_rows in ranked[:count]]


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

    input_count = len(rows)
    by_star: dict[tuple[str, str], list[ColourMeasurement]] = {}
    for row in rows:
        by_star.setdefault((row.catalogue_sha256, row.star_id), []).append(row)
    preliminary_x = np.asarray(
        [np.median([getattr(row, gaia_field) for row in group])
         for group in by_star.values()]
    )
    preliminary_y = np.asarray(
        [np.median([getattr(row, machine_field) for row in group])
         for group in by_star.values()]
    )
    robust_scatter = math.nan
    if len(preliminary_x) >= 2 and float(np.ptp(preliminary_x)) > 0:
        initial_slope, initial_intercept = np.polyfit(
            preliminary_x, preliminary_y, 1
        )
        residuals = np.asarray(
            [
                getattr(row, machine_field)
                - (initial_intercept + initial_slope * getattr(row, gaia_field))
                for row in rows
            ]
        )
        residual_centre = float(np.median(residuals))
        robust_scatter = 1.4826 * float(
            np.median(np.abs(residuals - residual_centre))
        )
        if robust_scatter > np.finfo(float).eps:
            rows = [
                row for row, residual in zip(rows, residuals)
                if abs(float(residual) - residual_centre) <= 6 * robust_scatter
            ]

    x = np.asarray([getattr(row, gaia_field) for row in rows])
    y = np.asarray([getattr(row, machine_field) for row in rows])
    by_star = {}
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
    excluded_count = input_count - len(rows)

    fig, ax = plt.subplots(figsize=(9, 7))
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
        f"{len(by_star):,} repeated Gaia stars · {len(rows):,} plotted observations"
        f"\nrobust residual filter: {excluded_count:,}/{input_count:,} extreme "
        "observations excluded (6 scaled MADs)"
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
    fig.subplots_adjust(left=.105, right=.985, top=.91, bottom=.16)
    fig.savefig(path, dpi=180)
    audit = {
        "input_observations": input_count,
        "plotted_observations": len(rows),
        "excluded_extreme_residuals": excluded_count,
        "filter": (
            "absolute residual from preliminary per-star-median OLS relation "
            "at most 6 times 1.4826 MAD"
        ),
        "robust_residual_scatter_mag": (
            robust_scatter if math.isfinite(robust_scatter) else None
        ),
        "x_limits": [float(value) for value in ax.get_xlim()],
        "y_limits": [float(value) for value in ax.get_ylim()],
    }
    path.with_suffix(".json").write_text(json.dumps(audit, indent=2) + "\n")
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


def write_nine_star_channel_airmass(
    rows: list[ColourMeasurement], output: Path, *, channel: str = "G"
) -> list[tuple[str, list[ColourMeasurement]]]:
    """Plot one machine-minus-Gaia channel against blind airmass for nine stars."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    channel_specs = {
        "R": ("machine_r_minus_gaia_rp", "R−Gaia RP", "#c62828"),
        "G": ("machine_g_minus_gaia_g", "G−Gaia G", "#2e7d32"),
        "B": ("machine_b_minus_gaia_bp", "B−Gaia BP", "#1565c0"),
    }
    if channel not in channel_specs:
        raise ValueError("channel must be R, G, or B")
    field, residual_label, colour = channel_specs[channel]
    selected = select_well_observed(rows, count=9)
    if len(selected) < 9:
        raise ValueError("fewer than nine repeated stars are available")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = _display_names(
        Path(__file__).resolve().parents[1] / "v7" / "data" / "display_names.json"
    )

    fig, axes = plt.subplots(3, 3, figsize=(15, 12), constrained_layout=True)
    table_rows = []
    for panel, (ax, (star_id, star_rows)) in enumerate(
        zip(axes.flat, selected), 1
    ):
        star_rows = sorted(star_rows, key=lambda row: row.airmass)
        x = np.asarray([row.airmass for row in star_rows])
        y = np.asarray([getattr(row, field) for row in star_rows])
        ax.scatter(x, y, s=24, color=colour, alpha=.78, linewidths=0)
        slope_text = ""
        if len(x) >= 2 and float(np.ptp(x)) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            span = np.linspace(float(x.min()), float(x.max()), 100)
            ax.plot(span, intercept + slope * span, color=colour, linewidth=1.2)
            slope_text = f"  k={slope:+.3f} mag/airmass"
        title = names.get(star_id, star_id)
        ax.set_title(
            f"{panel}. {title}\nN={len(star_rows)}, "
            f"ΔX={float(np.ptp(x)):.2f}{slope_text}",
            fontsize=9,
        )
        ax.set_xlabel("Blind airmass")
        ax.set_ylabel(f"Instrumental {residual_label} [mag]")
        ax.grid(alpha=.2)
        for row in star_rows:
            table_rows.append({"panel": panel, **asdict(row)})

    fig.suptitle(
        f"Nine best-observed Subaru stars: instrumental {residual_label} "
        "versus blind airmass\n"
        "Most usable distinct images, then widest airmass span; "
        "straight lines are per-star OLS diagnostics",
        fontsize=14,
    )
    fig.savefig(
        output / f"subaru_nine_well_observed_stars_{channel}_airmass.png",
        dpi=180,
    )
    plt.close(fig)

    with (output / f"subaru_nine_well_observed_stars_{channel}_airmass.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(table_rows[0]))
        writer.writeheader()
        writer.writerows(table_rows)
    return selected


def write_nine_star_g_airmass_shared_ranges(
    rows: list[ColourMeasurement], output: Path, *, max_airmass: float = 5.0,
    selection_mode: str = "most_observed",
) -> list[tuple[str, list[ColourMeasurement]]]:
    """Plot G−Gaia G with identical 0..X limits and shared residual limits."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if not math.isfinite(max_airmass) or max_airmass <= 0:
        raise ValueError("max_airmass must be positive and finite")
    field = "machine_g_minus_gaia_g"
    eligible = [
        row for row in rows
        if math.isfinite(row.airmass) and row.airmass <= max_airmass
        and math.isfinite(getattr(row, field))
    ]
    grouped_counts: dict[str, int] = {}
    for row in eligible:
        grouped_counts[row.star_id] = grouped_counts.get(row.star_id, 0) + 1
    minimum_observations = None
    if selection_mode == "bright_balanced":
        coverage_fraction = .6
        minimum_observations = math.ceil(
            coverage_fraction * max(grouped_counts.values(), default=0)
        )
        selected = select_bright_well_observed(
            eligible, count=9, coverage_fraction=coverage_fraction
        )
        selection_title = "Nine bright, well-observed Subaru stars"
        selection_description = (
            "Require at least 60 percent of the maximum retained repeat coverage, "
            "then select the brightest Gaia G stars"
        )
        stem = (
            "subaru_nine_bright_well_observed_stars_G_airmass_"
            "shared_ranges_le5"
        )
    elif selection_mode == "most_observed":
        selected = select_well_observed(eligible, count=9)
        selection_title = "Nine best-observed Subaru stars"
        selection_description = (
            "Most usable distinct images at or below the cutoff, then widest "
            "retained airmass span"
        )
        stem = "subaru_nine_well_observed_stars_G_airmass_shared_ranges_le5"
    else:
        raise ValueError("selection_mode must be most_observed or bright_balanced")
    if len(selected) < 9:
        raise ValueError("fewer than nine repeated stars remain below the airmass cutoff")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = _display_names(
        Path(__file__).resolve().parents[1] / "v7" / "data" / "display_names.json"
    )
    selected_values = [
        getattr(row, field)
        for _star_id, star_rows in selected
        for row in star_rows
    ]
    y_low, y_high = min(selected_values), max(selected_values)
    y_padding = ((y_high-y_low)*.04 if y_high > y_low
                 else max(.5, abs(y_low)*.02))
    y_limits = (float(y_low-y_padding), float(y_high+y_padding))

    fig, axes = plt.subplots(
        3, 3, figsize=(15, 12), constrained_layout=True,
        sharex=True, sharey=True,
    )
    table_rows = []
    for panel, (ax, (star_id, star_rows)) in enumerate(
        zip(axes.flat, selected), 1
    ):
        star_rows = sorted(star_rows, key=lambda row: row.airmass)
        x = np.asarray([row.airmass for row in star_rows])
        y = np.asarray([getattr(row, field) for row in star_rows])
        ax.scatter(x, y, s=24, color="#2e7d32", alpha=.78, linewidths=0)
        slope_text = ""
        if len(x) >= 2 and float(np.ptp(x)) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            span = np.linspace(float(x.min()), float(x.max()), 100)
            ax.plot(span, intercept + slope * span, color="#2e7d32",
                    linewidth=1.2)
            slope_text = f"  k={slope:+.3f} mag/airmass"
        title = names.get(star_id, star_id)
        ax.set_title(
            f"{panel}. {title}\nN={len(star_rows)}, "
            f"ΔX={float(np.ptp(x)):.2f}{slope_text}",
            fontsize=9,
        )
        ax.set_xlim(0., max_airmass)
        ax.set_ylim(*y_limits)
        ax.set_xlabel("Blind airmass")
        ax.set_ylabel("Instrumental G−Gaia G [mag]")
        ax.grid(alpha=.2)
        for row in star_rows:
            table_rows.append({"panel": panel, **asdict(row)})

    fig.suptitle(
        f"{selection_title}: instrumental G−Gaia G versus blind airmass\n"
        f"Shared axes; 0 ≤ airmass ≤ {max_airmass:g}; larger airmasses excluded before selection",
        fontsize=14,
    )
    fig.savefig(output / f"{stem}.png", dpi=180)
    plt.close(fig)

    with (output / f"{stem}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(table_rows[0]))
        writer.writeheader()
        writer.writerows(table_rows)
    audit = dict(
        panel_count=9,
        channel="G",
        quantity="instrumental G minus Gaia G magnitude",
        x_limits=[0., float(max_airmass)],
        y_limits=list(y_limits),
        max_airmass=float(max_airmass),
        selection_mode=selection_mode,
        minimum_observations=minimum_observations,
        excluded_above_max_airmass=sum(
            math.isfinite(row.airmass) and row.airmass > max_airmass
            for row in rows
        ),
        selection=selection_description,
    )
    (output / f"{stem}.json").write_text(json.dumps(audit, indent=2)+"\n")
    return selected


def write_four_star_rgb_pairs(
    rows: list[ColourMeasurement], output: Path
) -> list[tuple[str, list[ColourMeasurement]]]:
    """Plot same-exposure RGB magnitudes for four well-observed stars."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    selected = select_well_observed(rows, count=4)
    if len(selected) < 4:
        raise ValueError("fewer than four repeated stars are available")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = _display_names(
        Path(__file__).resolve().parents[1] / "v7" / "data" / "display_names.json"
    )
    pair_specs = (
        ("R vs G", "machine_g_mag", "machine_r_mag", "G magnitude", "R magnitude"),
        ("R vs B", "machine_b_mag", "machine_r_mag", "B magnitude", "R magnitude"),
        ("B vs G", "machine_g_mag", "machine_b_mag", "G magnitude", "B magnitude"),
    )
    all_airmass = np.asarray(
        [row.airmass for _star_id, star_rows in selected for row in star_rows]
    )
    norm = plt.Normalize(float(all_airmass.min()), float(all_airmass.max()))
    fig, axes = plt.subplots(4, 3, figsize=(14, 16), constrained_layout=True,
                             squeeze=False)
    table_rows = []
    colour_points = None
    for panel_row, ((star_id, star_rows), row_axes) in enumerate(
        zip(selected, axes), 1
    ):
        star_rows = sorted(star_rows, key=lambda row: row.airmass)
        for column, (title, x_field, y_field, x_label, y_label) in enumerate(
            pair_specs
        ):
            ax = row_axes[column]
            x = np.asarray([getattr(row, x_field) for row in star_rows])
            y = np.asarray([getattr(row, y_field) for row in star_rows])
            colour_points = ax.scatter(
                x, y, c=[row.airmass for row in star_rows], cmap="viridis",
                norm=norm, s=34, edgecolors="black", linewidths=.25,
            )
            if len(x) >= 2 and float(np.ptp(x)) > 0:
                slope, intercept = np.polyfit(x, y, 1)
                span = np.linspace(float(x.min()), float(x.max()), 100)
                ax.plot(span, intercept + slope * span, color=".25", linewidth=1)
                correlation = float(np.corrcoef(x, y)[0, 1])
                ax.text(
                    .03, .04, f"slope={slope:.3f}  r={correlation:.3f}",
                    transform=ax.transAxes, fontsize=8,
                    bbox=dict(boxstyle="round,pad=.2", facecolor="white",
                              edgecolor=".8", alpha=.85),
                )
            ax.set_title(title, fontsize=11)
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.invert_xaxis()
            ax.invert_yaxis()
            ax.grid(alpha=.2)
        row_name = names.get(star_id, star_id)
        row_axes[0].text(
            -.27, .5, f"{panel_row}. {row_name}\nN={len(star_rows)}",
            transform=row_axes[0].transAxes, rotation=90, ha="center", va="center",
            fontsize=10,
        )
        for row in star_rows:
            table_rows.append({"panel_row": panel_row, **asdict(row)})

    fig.suptitle(
        "Four most-reobserved Subaru stars: same-exposure RGB magnitudes\n"
        "Rows rank usable reobservations, then airmass span; brighter is upper right",
        fontsize=14,
    )
    if colour_points is not None:
        fig.colorbar(colour_points, ax=axes, label="Blind airmass", shrink=.72,
                     pad=.015)
    fig.savefig(
        output / "subaru_four_well_observed_stars_rgb_pairs.png", dpi=180
    )
    plt.close(fig)

    with (output / "subaru_four_well_observed_stars_rgb_pairs.csv").open(
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
    if len({(row.catalogue_sha256, row.star_id) for row in rows}) >= 4:
        write_four_star_rgb_pairs(rows, output)
    if len({(row.catalogue_sha256, row.star_id) for row in rows}) >= 9:
        write_nine_star_airmass(rows, output)
        write_nine_star_channel_airmass(rows, output, channel="G")
        write_nine_star_g_airmass_shared_ranges(
            rows, output, max_airmass=5., selection_mode="bright_balanced"
        )
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
