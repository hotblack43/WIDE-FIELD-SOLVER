#!/usr/bin/env python3
"""Extract and plot repeated monochrome APICAM FITS photometry."""

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
class APICAMMeasurement:
    run_id: str
    source_path: str
    source_sha256: str
    catalogue_sha256: str
    star_id: str
    detection_id: str
    airmass: float
    machine_l_mag: float
    gaia_g_mag: float
    gaia_bp_mag: float
    gaia_rp_mag: float
    gaia_bp_minus_rp: float
    machine_l_minus_gaia_g: float
    display_name: str = ""


@dataclass(frozen=True)
class Summary:
    star_count: int
    measurement_count: int


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _gaia_photometry(path: Path) -> dict[str, tuple[float, float, float]]:
    answer = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            g = _finite(row.get("phot_g_mean_mag"))
            bp = _finite(row.get("phot_bp_mean_mag"))
            rp = _finite(row.get("phot_rp_mean_mag"))
            if None not in (g, bp, rp):
                answer[row["source_id"]] = (g, bp, rp)
    return answer


def load_repeated_apicam_rows(
    database: Path, gaia_catalogue: Path
) -> list[APICAMMeasurement]:
    """Load repeated stars solely from single-plane APICAM FITS runs."""

    gaia = _gaia_photometry(gaia_catalogue)
    database = Path(database).resolve()
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        run_rows = db.execute(
            """
            SELECT r.run_id, r.recorded_at_utc, r.source_path, r.source_sha256,
                   r.catalogue_sha256, p.content, i.content, n.content
            FROM runs r
            JOIN products p ON p.run_id=r.run_id
                           AND p.product='photometry_summary.json'
            JOIN products i ON i.run_id=r.run_id
                           AND i.product='dots/input_image.json'
            LEFT JOIN products n ON n.run_id=r.run_id
                                AND n.product='display_names.json'
            WHERE r.exit_code=0
              AND lower(r.source_path) LIKE '%/apicam.%'
            ORDER BY r.recorded_at_utc, r.run_id
            """
        ).fetchall()

        valid_runs = {}
        for run in run_rows:
            (run_id, recorded, source_path, source_sha256, catalogue_sha256,
             provenance_json, input_json, names_json) = run
            try:
                provenance = json.loads(provenance_json)
                input_record = json.loads(input_json)
            except (TypeError, ValueError):
                continue
            if provenance.get("metadata_used") is not False:
                continue
            if provenance.get("airmass_source") not in BLIND_AIRMASS_SOURCES:
                continue
            if input_record.get("format") != "fits":
                continue
            if input_record.get("plane_names") != ["L"]:
                continue
            if not source_sha256 or not catalogue_sha256:
                continue
            try:
                saved_names = json.loads(names_json) if names_json else {}
            except (TypeError, ValueError):
                saved_names = {}
            display_names = {}
            for saved_star_id, details in saved_names.items():
                if not isinstance(details, dict):
                    continue
                name = str(details.get("display_name", "")).strip()
                if name and name != saved_star_id and not name.startswith("Gaia DR3 "):
                    display_names[saved_star_id] = name
            valid_runs[run_id] = (
                recorded, source_path, source_sha256, catalogue_sha256,
                display_names,
            )

        if not valid_runs:
            raw_rows = []
        else:
            placeholders = ",".join("?" for _ in valid_runs)
            raw_rows = db.execute(
                f"""
                SELECT run_id, row_number, star_id, detection_id,
                       json_extract(values_json, '$.R_mag'),
                       json_extract(values_json, '$.G_mag'),
                       json_extract(values_json, '$.B_mag'),
                       json_extract(values_json, '$.G_count_rate_adu_per_s'),
                       json_extract(values_json, '$.exposure_status'),
                       json_extract(values_json, '$.airmass')
                FROM measurements
                WHERE product='stellar_photometry.csv'
                  AND star_id LIKE 'Gaia DR3 %'
                  AND lower(CAST(json_extract(
                      values_json, '$.photometry_usable') AS TEXT))='true'
                  AND run_id IN ({placeholders})
                ORDER BY run_id, row_number
                """,
                tuple(valid_runs),
            ).fetchall()

    latest: dict[tuple[str, str, str], tuple[str, APICAMMeasurement]] = {}
    for raw in raw_rows:
        (run_id, _row_number, star_id, detection_id,
         raw_r_mag, raw_g_mag, raw_b_mag, raw_g_rate, raw_exposure_status,
         raw_airmass) = raw
        (recorded, source_path, source_sha256, catalogue_sha256,
         display_names) = valid_runs[run_id]
        catalogue = gaia.get(star_id.removeprefix("Gaia DR3 "))
        if catalogue is None:
            continue
        g_rate = _finite(raw_g_rate)
        exposure_status = str(raw_exposure_status or '').strip().lower()
        airmass = _finite(raw_airmass)
        if g_rate is None or g_rate <= 0 or exposure_status != 'available' or airmass is None:
            continue
        g_mag = -2.5 * math.log10(g_rate)
        gaia_g, gaia_bp, gaia_rp = catalogue
        measurement = APICAMMeasurement(
            run_id=run_id,
            source_path=source_path,
            source_sha256=source_sha256,
            catalogue_sha256=catalogue_sha256,
            star_id=star_id,
            detection_id=detection_id or "",
            airmass=airmass,
            machine_l_mag=g_mag,
            gaia_g_mag=gaia_g,
            gaia_bp_mag=gaia_bp,
            gaia_rp_mag=gaia_rp,
            gaia_bp_minus_rp=round(gaia_bp-gaia_rp, 12),
            machine_l_minus_gaia_g=round(g_mag-gaia_g, 12),
            display_name=display_names.get(star_id, ""),
        )
        key = (star_id, source_sha256, catalogue_sha256)
        if key not in latest or recorded >= latest[key][0]:
            latest[key] = (recorded, measurement)

    counts: dict[tuple[str, str], int] = {}
    for star_id, _source_sha256, catalogue_sha256 in latest:
        key = (star_id, catalogue_sha256)
        counts[key] = counts.get(key, 0) + 1
    return sorted(
        (
            row for _recorded, row in latest.values()
            if counts[(row.star_id, row.catalogue_sha256)] >= 2
        ),
        key=lambda row: (row.catalogue_sha256, row.star_id, row.source_sha256),
    )


def _group(rows: list[APICAMMeasurement]):
    grouped: dict[tuple[str, str], list[APICAMMeasurement]] = {}
    for row in rows:
        grouped.setdefault((row.catalogue_sha256, row.star_id), []).append(row)
    return grouped


def _well_observed(rows: list[APICAMMeasurement], count: int):
    grouped = _group(rows)
    ranked = sorted(
        grouped.items(),
        key=lambda item: (
            -len(item[1]),
            -(max(row.airmass for row in item[1])
              - min(row.airmass for row in item[1])),
            item[0],
        ),
    )
    return [(key[1], star_rows) for key, star_rows in ranked[:count]]


def _bright_well_observed(
    rows: list[APICAMMeasurement], count: int, coverage_fraction: float = .6
):
    grouped = _group(rows)
    if not grouped:
        return []
    minimum = math.ceil(coverage_fraction * max(map(len, grouped.values())))
    ranked = [
        (star_rows[0].gaia_g_mag, -len(star_rows), key, star_rows)
        for key, star_rows in grouped.items() if len(star_rows) >= minimum
    ]
    ranked.sort(key=lambda item: item[:3])
    return [(key[1], star_rows) for _mag, _count, key, star_rows in ranked[:count]]


def _display_names(rows: list[APICAMMeasurement]) -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "v7" / "data" / "display_names.json"
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        payload = {}
    names = {
        star_id: details["display_name"]
        for star_id, details in payload.items()
        if isinstance(details, dict) and details.get("display_name")
    }
    names.update(
        (row.star_id, row.display_name) for row in rows if row.display_name
    )
    return names


def _display_label(names: dict[str, str], star_id: str) -> str:
    """Use an ordinary name when available without printing a long Gaia ID."""

    return names.get(star_id, "unlabelled Gaia source")


def robust_airmass_line(x, y) -> tuple[float, float]:
    """Return a Theil-Sen slope and joint-median intercept."""

    import numpy as np
    from scipy.stats import theilslopes

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    if len(x) < 2 or float(np.ptp(x)) <= 0:
        raise ValueError("robust airmass line needs two distinct finite x values")
    result = theilslopes(y, x, method="joint")
    return float(result.slope), float(result.intercept)


def _plot_global_colour_term(rows: list[APICAMMeasurement], output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    grouped = _group(rows)
    median_x = np.asarray([
        np.median([row.gaia_bp_minus_rp for row in star_rows])
        for star_rows in grouped.values()
    ])
    median_y = np.asarray([
        np.median([row.machine_l_minus_gaia_g for row in star_rows])
        for star_rows in grouped.values()
    ])
    slope, intercept = (0., float(np.median(median_y)))
    robust_scatter = math.nan
    retained = rows
    if len(median_x) >= 2 and float(np.ptp(median_x)) > 0:
        slope, intercept = np.polyfit(median_x, median_y, 1)
        residuals = np.asarray([
            row.machine_l_minus_gaia_g
            - (intercept+slope*row.gaia_bp_minus_rp) for row in rows
        ])
        centre = float(np.median(residuals))
        robust_scatter = 1.4826*float(np.median(np.abs(residuals-centre)))
        if robust_scatter > np.finfo(float).eps:
            retained = [
                row for row, residual in zip(rows, residuals)
                if abs(float(residual)-centre) <= 6*robust_scatter
            ]
    grouped = _group(retained)
    x = np.asarray([row.gaia_bp_minus_rp for row in retained])
    y = np.asarray([row.machine_l_minus_gaia_g for row in retained])
    median_x = np.asarray([
        np.median([row.gaia_bp_minus_rp for row in star_rows])
        for star_rows in grouped.values()
    ])
    median_y = np.asarray([
        np.median([row.machine_l_minus_gaia_g for row in star_rows])
        for star_rows in grouped.values()
    ])

    fig, ax = plt.subplots(figsize=(9, 7))
    ax.scatter(x, y, s=3, color="#315a9a", alpha=.08, linewidths=0,
               rasterized=True, label="individual APICAM observations")
    ax.scatter(median_x, median_y, s=12, color="#315a9a", alpha=.55,
               edgecolors="black", linewidths=.2, rasterized=True,
               label="per-star medians")
    annotation = (
        f"{len(grouped):,} repeated Gaia stars · {len(retained):,} plotted observations"
        f"\nrobust residual filter: {len(rows)-len(retained):,}/{len(rows):,} "
        "extreme observations excluded (6 scaled MADs)"
    )
    if len(median_x) >= 2 and float(np.ptp(median_x)) > 0:
        slope, intercept = np.polyfit(median_x, median_y, 1)
        fitted = intercept+slope*median_x
        rms = float(np.sqrt(np.mean((median_y-fitted)**2)))
        span = np.linspace(float(x.min()), float(x.max()), 200)
        ax.plot(span, intercept+slope*span, color="black", linewidth=1.3,
                label="OLS on per-star medians")
        annotation += (f"\nmedian-star OLS: L−G = {intercept:.3f} + "
                       f"{slope:.3f}(BP−RP)\nRMS = {rms:.3f} mag")
    ax.text(.01, .99, annotation, transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=.3", facecolor="white",
                      edgecolor=".75", alpha=.9))
    ax.set_xlabel("Gaia BP−RP [mag]")
    ax.set_ylabel("APICAM instrumental L−Gaia G [mag]")
    ax.set_title("APICAM repeated stars: luminance colour term")
    ax.grid(alpha=.2)
    ax.legend(loc="lower right", fontsize=8)
    fig.text(.5, .01,
             "APICAM is a single-plane 16-bit luminance camera; no RGB colour "
             "measurement is implied.", ha="center", fontsize=8.5, color=".3")
    fig.subplots_adjust(left=.105, right=.985, top=.91, bottom=.16)
    path = output / "apicam_repeated_stars_L_minus_gaia_G_vs_gaia_BPRP.png"
    fig.savefig(path, dpi=180)
    audit = dict(
        input_observations=len(rows), plotted_observations=len(retained),
        excluded_extreme_residuals=len(rows)-len(retained),
        filter=("absolute residual from preliminary per-star-median OLS relation "
                "at most 6 times 1.4826 MAD"),
        robust_residual_scatter_mag=(robust_scatter
                                     if math.isfinite(robust_scatter) else None),
        x_limits=list(map(float, ax.get_xlim())),
        y_limits=list(map(float, ax.get_ylim())),
        channel="APICAM FITS luminance L",
    )
    path.with_suffix(".json").write_text(json.dumps(audit, indent=2)+"\n")
    plt.close(fig)


def _plot_four_star_airmass(rows: list[APICAMMeasurement], output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    selected = _well_observed(rows, 4)
    if len(selected) < 4:
        raise ValueError("fewer than four repeated APICAM stars are available")
    names = _display_names(rows)
    specs = (
        ("L−Gaia RP", lambda row: row.machine_l_mag-row.gaia_rp_mag),
        ("L−Gaia G", lambda row: row.machine_l_minus_gaia_g),
        ("L−Gaia BP", lambda row: row.machine_l_mag-row.gaia_bp_mag),
    )
    fig, axes = plt.subplots(4, 3, figsize=(14, 16), constrained_layout=True,
                             squeeze=False, sharex=True)
    table = []
    for panel_row, ((star_id, star_rows), row_axes) in enumerate(zip(selected, axes), 1):
        star_rows = sorted(star_rows, key=lambda row: row.airmass)
        x = np.asarray([row.airmass for row in star_rows])
        for ax, (title, value) in zip(row_axes, specs):
            y = np.asarray([value(row) for row in star_rows])
            ax.scatter(x, y, s=30, color="#315a9a", alpha=.78, linewidths=0)
            if len(x) >= 2 and float(np.ptp(x)) > 0:
                slope, intercept = robust_airmass_line(x, y)
                span = np.linspace(float(x.min()), float(x.max()), 100)
                ax.plot(span, intercept+slope*span, color="black", linewidth=1)
                ax.text(.03, .04, f"Theil–Sen k={slope:+.3f} mag/airmass",
                        transform=ax.transAxes, fontsize=8,
                        bbox=dict(boxstyle="round,pad=.2", facecolor="white",
                                  edgecolor=".8", alpha=.85))
            ax.set_title(title)
            ax.set_xlabel("Blind airmass")
            ax.set_ylabel("Magnitude difference [mag]")
            ax.grid(alpha=.2)
        row_axes[0].text(
            -.27, .5, f"{panel_row}. {_display_label(names, star_id)}\n"
            f"N={len(star_rows)}",
            transform=row_axes[0].transAxes, rotation=90, ha="center", va="center",
            fontsize=10,
        )
        table.extend({"panel_row": panel_row, **asdict(row)} for row in star_rows)
    fig.suptitle(
        "Four most-reobserved APICAM stars: luminance residuals versus blind airmass\n"
        "One measured L channel compared with three Gaia passbands; robust Theil–Sen lines",
        fontsize=14,
    )
    stem = "apicam_four_well_observed_stars_L_airmass"
    fig.savefig(output / f"{stem}.png", dpi=180)
    plt.close(fig)
    with (output / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(table[0]))
        writer.writeheader(); writer.writerows(table)


def _plot_nine_star_airmass(
    rows: list[APICAMMeasurement], output: Path, *, shared: bool
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if shared:
        eligible = [row for row in rows if math.isfinite(row.airmass) and row.airmass <= 5]
        selected = _bright_well_observed(eligible, 9)
        stem = "apicam_nine_bright_well_observed_stars_L_airmass_shared_ranges_le5"
        title = "Nine bright, well-observed APICAM stars"
    else:
        eligible = rows
        selected = _well_observed(eligible, 9)
        stem = "apicam_nine_well_observed_stars_L_airmass"
        title = "Nine most-reobserved APICAM stars"
    if len(selected) < 9:
        raise ValueError("fewer than nine repeated APICAM stars are available")
    names = _display_names(rows)
    values = [row.machine_l_minus_gaia_g for _, group in selected for row in group]
    low, high = min(values), max(values)
    pad = .04*(high-low) if high > low else .5
    fig, axes = plt.subplots(3, 3, figsize=(15, 12), constrained_layout=True,
                             sharex=shared, sharey=shared)
    table = []
    for panel, (ax, (star_id, star_rows)) in enumerate(zip(axes.flat, selected), 1):
        star_rows = sorted(star_rows, key=lambda row: row.airmass)
        x = np.asarray([row.airmass for row in star_rows])
        y = np.asarray([row.machine_l_minus_gaia_g for row in star_rows])
        ax.scatter(x, y, s=24, color="#315a9a", alpha=.78, linewidths=0)
        slope_text = ""
        if len(x) >= 2 and float(np.ptp(x)) > 0:
            slope, intercept = robust_airmass_line(x, y)
            span = np.linspace(float(x.min()), float(x.max()), 100)
            ax.plot(span, intercept+slope*span, color="black", linewidth=1)
            slope_text = f"  k_TS={slope:+.3f}"
        ax.set_title(f"{panel}. {_display_label(names, star_id)}\n"
                     f"N={len(star_rows)}, ΔX={float(np.ptp(x)):.2f}{slope_text}",
                     fontsize=9)
        ax.set_xlabel("Blind airmass")
        ax.set_ylabel("APICAM L−Gaia G [mag]")
        ax.grid(alpha=.2)
        if shared:
            ax.set_xlim(0, 5); ax.set_ylim(low-pad, high+pad)
        table.extend({"panel": panel, **asdict(row)} for row in star_rows)
    subtitle = ("Shared axes; 0 ≤ airmass ≤ 5; larger airmasses excluded; "
                "lines are robust Theil–Sen fits"
                if shared else
                "Most usable distinct images; lines are robust Theil–Sen fits")
    fig.suptitle(f"{title}: APICAM L−Gaia G versus blind airmass\n{subtitle}",
                 fontsize=14)
    fig.savefig(output / f"{stem}.png", dpi=180)
    plt.close(fig)
    with (output / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(table[0]))
        writer.writeheader(); writer.writerows(table)
    audit = dict(
        panel_count=9, channel="APICAM FITS luminance L",
        comparison_band="Gaia G", shared_axes=shared,
        x_limits=([0., 5.] if shared else None),
        max_airmass=(5. if shared else None),
        regression_method="Theil-Sen",
        regression_intercept="joint median of residuals",
        excluded_above_max_airmass=(sum(row.airmass > 5 for row in rows)
                                    if shared else 0),
    )
    (output / f"{stem}.json").write_text(json.dumps(audit, indent=2)+"\n")


def write_outputs(rows: list[APICAMMeasurement], output: Path) -> Summary:
    if not rows:
        raise ValueError("no repeated APICAM luminance measurements")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "apicam_repeated_star_photometry.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(asdict(rows[0])))
        writer.writeheader(); writer.writerows(asdict(row) for row in rows)
    provenance = dict(
        dataset="ESO Paranal APICAM",
        input_requirement="FITS files named APICAM.* with exactly one L plane",
        measured_channel="Luminance",
        independent_rgb_channels=False,
        note=("The generic per-run photometry stores identical R/G/B copies for "
              "single-plane inputs; this extractor verifies equality and records one L value."),
        source_images=len({row.source_sha256 for row in rows}),
        repeated_stars=len({(row.catalogue_sha256, row.star_id) for row in rows}),
        measurements=len(rows),
    )
    (output / "apicam_photometry_provenance.json").write_text(
        json.dumps(provenance, indent=2)+"\n"
    )
    _plot_global_colour_term(rows, output)
    if len(_group(rows)) >= 4:
        _plot_four_star_airmass(rows, output)
    if len(_group(rows)) >= 9:
        _plot_nine_star_airmass(rows, output, shared=False)
        _plot_nine_star_airmass(rows, output, shared=True)
    return Summary(
        star_count=len(_group(rows)), measurement_count=len(rows)
    )


def generate(database: Path, gaia_catalogue: Path, output: Path) -> Summary:
    rows = load_repeated_apicam_rows(database, gaia_catalogue)
    return write_outputs(rows, output)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot repeated monochrome ESO Paranal APICAM FITS photometry."
    )
    parser.add_argument("--database", type=Path, default=Path("results/stars.sqlite"))
    parser.add_argument(
        "--gaia-catalogue", type=Path,
        default=Path("v7/data/stars_gaia_dr3_g75.gaia-source.csv"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("results/apicam-repeated-star-photometry"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = generate(args.database, args.gaia_catalogue, args.output)
    print(f"{summary.star_count:,} repeated Gaia stars; "
          f"{summary.measurement_count:,} APICAM observations")
    print(f"Outputs: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
