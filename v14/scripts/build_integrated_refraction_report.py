#!/usr/bin/env python3
"""Build a readable four-page PDF from the integrated-refraction evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch
import numpy as np


INK = "#15202b"
MUTED = "#52606d"
BLUE = "#1769aa"
PALE_BLUE = "#e8f1f8"
GREEN = "#237a57"
PALE_GREEN = "#e7f4ed"
RED = "#b33a3a"
PALE_RED = "#f8eaea"
GOLD = "#b77700"


def _add_header(figure: plt.Figure, title: str, page: int) -> None:
    figure.text(.065, .955, title, fontsize=18, fontweight="bold", color=INK,
                ha="left", va="top")
    figure.text(.935, .955, f"v13  |  page {page}/4", fontsize=8.5, color=MUTED,
                ha="right", va="top")
    figure.lines.append(plt.Line2D([.065, .935], [.925, .925], transform=figure.transFigure,
                                   color=BLUE, linewidth=1.2))


def _metric(figure: plt.Figure, x: float, value: str, label: str) -> None:
    figure.text(x, .645, value, fontsize=22, fontweight="bold", color=BLUE,
                ha="center", va="center")
    figure.text(x, .605, label, fontsize=9, color=MUTED, ha="center", va="center")


def _safe_float(row: dict[str, object], key: str) -> float | None:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _load_image(path: Path) -> np.ndarray:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return mpimg.imread(path)


def _cover_page(summary: dict[str, object]) -> plt.Figure:
    rows = list(summary.get("rows", []))
    fisheye = [row for row in rows if row.get("status") != "rejected_small_field"]
    fitted = sum(int(row.get("fitted_count", 0) or 0) for row in fisheye)
    coverage = [_safe_float(row, "angular_diameter_deg") for row in fisheye]
    coverage = [value for value in coverage if value is not None]
    adopted = sum(row.get("status") == "adopted" for row in fisheye)

    figure = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    _add_header(figure, "Integrated refraction in the Barghini fit", 1)
    figure.text(.065, .875, "Decision report", fontsize=11, color=BLUE,
                fontweight="bold", ha="left")
    figure.text(.065, .835,
                "What happened when atmospheric refraction was fitted\n"
                "inside the robust wide-field camera model?",
                fontsize=16, color=INK, ha="left", va="top", linespacing=1.35)

    banner = FancyBboxPatch((.065, .69), .87, .055, transform=figure.transFigure,
                            boxstyle="round,pad=0.012,rounding_size=0.012",
                            facecolor=PALE_GREEN, edgecolor=GREEN, linewidth=1.2)
    figure.patches.append(banner)
    figure.text(.09, .718, "SAFE RESULT", fontsize=9, color=GREEN,
                fontweight="bold", va="center")
    figure.text(.22, .718, "Keep exact zero refraction for these archived solutions.",
                fontsize=12.5, color=INK, fontweight="bold", va="center")

    _metric(figure, .18, str(len(fisheye)), "full-fisheye solutions")
    _metric(figure, .39, f"{fitted:,}", "fitted associations")
    _metric(figure, .62, f"{min(coverage):.0f}-{max(coverage):.0f} deg" if coverage else "n/a",
            "angular diameter")
    _metric(figure, .84, str(adopted), "refraction models adopted")

    figure.text(.065, .54, "Meaning", fontsize=13, fontweight="bold", color=INK)
    meaning = (
        "The coupled model can recover refraction in controlled synthetic tests. In the "
        "eight archived fisheye solutions, however, candidate refraction terms either ran "
        "to a physical boundary or failed blocked spatial validation. The conservative "
        "model selector therefore retained zero refraction in every case."
    )
    figure.text(.065, .505, textwrap.fill(meaning, 88), fontsize=10.5, color=INK,
                ha="left", va="top", linespacing=1.45)

    figure.text(.065, .37, "How the decision is protected", fontsize=13,
                fontweight="bold", color=INK)
    stages = [
        ("1", "Fit jointly", "Barghini lens + zenith + refraction"),
        ("2", "Check physics", "Interior coefficients and valid horizon"),
        ("3", "Validate spatially", "Deterministic angular blocks"),
        ("4", "Fall back safely", "Exact zero if evidence is insufficient"),
    ]
    for index, (number, title, body) in enumerate(stages):
        x = .065 + index * .222
        box = FancyBboxPatch((x, .205), .195, .12, transform=figure.transFigure,
                             boxstyle="round,pad=0.01,rounding_size=0.008",
                             facecolor=PALE_BLUE, edgecolor="#aac7db", linewidth=.8)
        figure.patches.append(box)
        figure.text(x + .018, .292, number, fontsize=10, color=BLUE, fontweight="bold")
        figure.text(x + .018, .262, title, fontsize=10, color=INK, fontweight="bold")
        figure.text(x + .018, .232, textwrap.fill(body, 25), fontsize=7.8, color=MUTED,
                    va="top", linespacing=1.25)

    figure.text(.065, .15, "Numerical method", fontsize=10, fontweight="bold", color=INK)
    figure.text(.065, .12,
                "Radial soft-L1 robust least squares per star. Ordinary least squares is not used.",
                fontsize=9.5, color=MUTED)
    figure.text(.065, .065,
                "The saved coordinates, residuals and overlays all use the selected physical model.",
                fontsize=8.5, color=MUTED)
    return figure


def _comparison_page(comparison: np.ndarray) -> plt.Figure:
    figure = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    _add_header(figure, "Archived fisheye comparison", 2)
    axis = figure.add_axes([.06, .25, .88, .62])
    axis.imshow(comparison)
    axis.set_axis_off()
    figure.text(.065, .205, "How to read this", fontsize=11, fontweight="bold", color=INK)
    note = (
        "Left: selected astrometric RMS remains equal to the zero-refraction baseline. "
        "Right: red crosses mark candidates rejected by physical checks before the blocked "
        "validation folds; the dashed line is the minimum gain required for adoption."
    )
    figure.text(.065, .17, textwrap.fill(note, 104), fontsize=9.5, color=MUTED,
                ha="left", va="top", linespacing=1.35)
    figure.text(.065, .085,
                "Result: none of the eight full-fisheye archives supplied defensible evidence for a non-zero term.",
                fontsize=9.5, color=RED, fontweight="bold")
    return figure


def _diagnostic_page(overlay: np.ndarray, residuals: np.ndarray) -> plt.Figure:
    figure = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    _add_header(figure, "What the solver diagnostics look like", 3)
    top = figure.add_axes([.06, .52, .88, .34])
    bottom = figure.add_axes([.06, .25, .88, .22])
    for axis, image in ((top, overlay), (bottom, residuals)):
        axis.imshow(image)
        axis.set_axis_off()
    top.set_title("Measured centroids and model predictions", fontsize=9,
                  color=INK, fontweight="bold", pad=6)
    bottom.set_title("Faithful astrometric residual vectors", fontsize=9,
                     color=INK, fontweight="bold", pad=6)
    figure.text(.065, .195,
                "Representative fresh v13 demo diagnostics", fontsize=11,
                color=INK, fontweight="bold")
    note = (
        "These panels illustrate the output used to inspect a solution. Symbols are not "
        "shifted cosmetically: centroids, predictions and numerical residuals all derive "
        "from the same selected Barghini model. Residual magnification, where present, is labelled."
    )
    figure.text(.065, .16, textwrap.fill(note, 105), fontsize=9.5, color=MUTED,
                ha="left", va="top", linespacing=1.35)
    figure.text(.065, .06,
                "These diagnostic images demonstrate the v13 reporting style; they are not additional replay inputs.",
                fontsize=8.5, color=MUTED)
    return figure


def _evidence_page(summary: dict[str, object]) -> plt.Figure:
    rows = [row for row in summary.get("rows", [])
            if row.get("status") in {"adopted", "rejected_zero"}]
    figure = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    _add_header(figure, "Evidence and next experiment", 4)

    axis = figure.add_axes([.1, .58, .8, .27])
    baseline = np.asarray([_safe_float(row, "baseline_rms_arcmin") for row in rows], dtype=float)
    candidate = np.asarray([_safe_float(row, "candidate_rms_arcmin") for row in rows], dtype=float)
    families = [str(row.get("family", "unknown")) for row in rows]
    colours = {"MMTO": BLUE, "APICAM": GREEN, "Subaru": GOLD, "historical": RED}
    for family in dict.fromkeys(families):
        mask = np.array([item == family for item in families])
        axis.scatter(baseline[mask], candidate[mask], s=55, alpha=.85,
                     color=colours.get(family, MUTED), label=family)
    low = float(np.nanmin(np.r_[baseline, candidate])) if rows else 0.0
    high = float(np.nanmax(np.r_[baseline, candidate])) if rows else 1.0
    margin = max((high - low) * .08, .1)
    axis.plot([low - margin, high + margin], [low - margin, high + margin],
              color=MUTED, linestyle="--", linewidth=1, label="equal RMS")
    axis.set_xlim(low - margin, high + margin)
    axis.set_ylim(low - margin, high + margin)
    axis.set_xlabel("Zero-refraction baseline RMS (arcmin)")
    axis.set_ylabel("Candidate refraction RMS (arcmin)")
    axis.grid(alpha=.18)
    axis.legend(fontsize=7.5, ncol=3)

    table_axis = figure.add_axes([.065, .31, .87, .20])
    table_axis.set_axis_off()
    table_rows = []
    for row in rows:
        table_rows.append([
            str(row.get("family", "")),
            f"{int(row.get('fitted_count', 0) or 0):,}",
            f"{_safe_float(row, 'angular_diameter_deg'):.1f}",
            f"{_safe_float(row, 'baseline_rms_arcmin'):.3f}",
            f"{_safe_float(row, 'candidate_rms_arcmin'):.3f}",
            str(row.get("status", "")).replace("_", " "),
        ])
    table = table_axis.table(
        cellText=table_rows,
        colLabels=["Family", "Stars", "Span (deg)", "Zero RMS", "Candidate RMS", "Decision"],
        cellLoc="center", colLoc="center", loc="center",
        colWidths=[.15, .13, .14, .15, .17, .2],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.4)
    table.scale(1, 1.28)
    for (row_index, _), cell in table.get_celld().items():
        cell.set_edgecolor("#d5dde3")
        if row_index == 0:
            cell.set_facecolor(PALE_BLUE)
            cell.set_text_props(weight="bold", color=INK)

    next_box = FancyBboxPatch((.065, .105), .87, .12, transform=figure.transFigure,
                              boxstyle="round,pad=0.012,rounding_size=0.01",
                              facecolor=PALE_GREEN, edgecolor=GREEN, linewidth=1.0)
    figure.patches.append(next_box)
    figure.text(.09, .192, "RECOMMENDED NEXT EXPERIMENT", fontsize=9, color=GREEN,
                fontweight="bold")
    next_step = (
        "Fit several exposures jointly: hold one lens model common to all frames while "
        "allowing refraction to vary by exposure. Repeated geometry can then separate "
        "stable lens distortion from changing atmospheric refraction."
    )
    figure.text(.09, .16, textwrap.fill(next_step, 92), fontsize=9.4, color=INK,
                va="top", linespacing=1.3)
    figure.text(.065, .065,
                "Until that experiment succeeds, exact zero remains the scientifically defensible saved model.",
                fontsize=8.5, color=MUTED)
    return figure


def write_report(summary_path: Path, comparison_figure: Path, sky_overlay: Path,
                 residuals_figure: Path, output: Path) -> Path:
    """Write one new report and refuse to replace an existing file."""
    summary_path = Path(summary_path)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing report: {output}")
    summary = json.loads(summary_path.read_text())
    if summary.get("ordinary_least_squares_used") is not False:
        raise ValueError("Report requires verified robust-only evidence")
    images = [_load_image(path) for path in
              (comparison_figure, sky_overlay, residuals_figure)]
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Title": "Integrated refraction inside the robust Barghini fit",
        "Subject": "v13 full-fisheye validation report",
        "Keywords": "fisheye, astrometry, Barghini, robust least squares, refraction",
    }
    with PdfPages(output, metadata=metadata) as pdf:
        figures = [
            _cover_page(summary),
            _comparison_page(images[0]),
            _diagnostic_page(images[1], images[2]),
            _evidence_page(summary),
        ]
        for figure in figures:
            pdf.savefig(figure, facecolor="white")
            plt.close(figure)
    return output


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--summary", required=True, type=Path)
    command.add_argument("--comparison-figure", required=True, type=Path)
    command.add_argument("--sky-overlay", required=True, type=Path)
    command.add_argument("--residuals-figure", required=True, type=Path)
    command.add_argument("--output", required=True, type=Path)
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    output = write_report(
        arguments.summary,
        arguments.comparison_figure,
        arguments.sky_overlay,
        arguments.residuals_figure,
        arguments.output,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
