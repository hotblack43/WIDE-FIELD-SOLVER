#!/usr/bin/env python3
"""Plot offline-catalogued MMTO variables using nightly-corrected magnitudes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "v22" / "data"
UTC = timezone.utc
DEFAULT_START_UTC = datetime(2026, 6, 30, tzinfo=UTC)
DEFAULT_MIN_PERIOD_DAYS = 5.0
DEFAULT_MAX_PERIOD_DAYS = 30.0
DEFAULT_MAX_CATALOGUE_MAGNITUDE = 5.0
CHANNEL_COLOURS = {"R": "#d62728", "G": "#2ca02c", "B": "#1f77b4"}
CROSSMATCH_REQUIRED = {
    "catalogue_sha256", "star_id", "vsx_oid", "vsx_name", "vsx_flag",
    "vsx_type", "period_days", "selection_status",
}
CORRECTED_REQUIRED = {
    "night", "channel", "observed_utc", "source_sha256", "catalogue_sha256",
    "star_id", "catalogue_magnitude", "machine_magnitude", "airmass",
    "extinction_mag_per_airmass", "corrected_magnitude", "status",
}
MEASUREMENT_FIELDS = (
    "vsx_oid", "vsx_name", "vsx_type", "period_days", "night",
    "observed_utc", "channel", "flux_averaged_corrected_magnitude",
    "contributing_measurement_count", "catalogue_magnitudes", "source_sha256s",
    "catalogue_sha256s", "star_ids",
)
MEASUREMENT_AUDIT_FIELDS = (
    "observed_utc", "source_sha256", "catalogue_sha256", "star_id", "channel",
    "catalogue_magnitude", "corrected_magnitude", "vsx_oid", "plot_status",
    "exclusion_reason",
)
SELECTION_AUDIT_FIELDS = (
    "catalogue_sha256", "star_id", "vsx_oid", "vsx_name", "vsx_flag",
    "vsx_type", "period_days", "catalogue_selection_status",
    "plot_selection_status", "plotted_measurement_count",
)
SINE_FIT_FIELDS = (
    "vsx_oid", "vsx_name", "vsx_type", "period_days", "channel",
    "nightly_point_count", "reference_utc", "phase_offset_cycles_brightest",
    "phase_offset_days_brightest", "brightest_epoch_utc",
    "mean_corrected_magnitude", "semi_amplitude_magnitude", "rms_magnitude",
    "status",
)


@dataclass(frozen=True, slots=True)
class PlotPoint:
    observed_utc: datetime
    channel: str
    corrected_magnitude: float
    source_sha256: str
    catalogue_sha256: str
    star_id: str


@dataclass(frozen=True, slots=True)
class StarSeries:
    vsx_oid: str
    vsx_name: str
    vsx_type: str
    period_days: float
    points: tuple[PlotPoint, ...]


@dataclass(frozen=True, slots=True)
class SineFit:
    channel: str
    nightly_point_count: int
    reference_utc: datetime
    phase_offset_cycles_brightest: float | None
    mean_corrected_magnitude: float | None
    semi_amplitude_magnitude: float | None
    rms_magnitude: float | None
    status: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finite_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid observation time: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"observation time must include a timezone: {value!r}")
    return parsed.astimezone(UTC)


def _median_utc(values: Sequence[datetime]) -> datetime:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2


def _flux_averaged_magnitude(values: Sequence[float]) -> float:
    brightest = min(values)
    relative_mean_flux = math.fsum(
        10.0 ** (-0.4 * (value - brightest)) for value in values
    ) / len(values)
    return brightest - 2.5 * math.log10(relative_mean_flux)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def fit_fixed_period_sine(
    points: Sequence[PlotPoint],
    period_days: float,
    reference_utc: datetime,
) -> SineFit:
    """Fit magnitude = mean - amplitude*cos(phase-phase_brightest)."""

    channel = points[0].channel
    count = len(points)
    if count < 3:
        return SineFit(channel, count, reference_utc, None, None, None, None,
                       "insufficient_nightly_points")
    elapsed_days = np.asarray([
        (point.observed_utc - reference_utc).total_seconds() / 86400.0
        for point in points
    ])
    angles = 2.0 * np.pi * elapsed_days / period_days
    design = np.column_stack((np.ones(count), np.cos(angles), np.sin(angles)))
    if np.linalg.matrix_rank(design) < 3:
        return SineFit(channel, count, reference_utc, None, None, None, None,
                       "insufficient_independent_phases")
    values = np.asarray([point.corrected_magnitude for point in points])
    coefficients, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    mean_magnitude, cosine_coefficient, sine_coefficient = coefficients
    amplitude = math.hypot(cosine_coefficient, sine_coefficient)
    if amplitude <= 1e-12 * max(1.0, abs(float(mean_magnitude))):
        return SineFit(channel, count, reference_utc, None, float(mean_magnitude),
                       0.0, 0.0, "zero_amplitude")
    phase = (
        math.atan2(-float(sine_coefficient), -float(cosine_coefficient))
        / (2.0 * math.pi)
    ) % 1.0
    residuals = values - design @ coefficients
    rms = math.sqrt(float(np.mean(np.square(residuals))))
    return SineFit(
        channel, count, reference_utc, phase, float(mean_magnitude), amplitude,
        rms, "fitted",
    )


def _sine_fit_row(star: StarSeries, fit: SineFit) -> dict[str, object]:
    phase = fit.phase_offset_cycles_brightest
    offset_days = None if phase is None else phase * star.period_days
    brightest = (
        None if offset_days is None
        else fit.reference_utc + timedelta(days=offset_days)
    )
    return {
        "vsx_oid": star.vsx_oid,
        "vsx_name": star.vsx_name,
        "vsx_type": star.vsx_type,
        "period_days": format(star.period_days, ".17g"),
        "channel": fit.channel,
        "nightly_point_count": fit.nightly_point_count,
        "reference_utc": _utc_text(fit.reference_utc),
        "phase_offset_cycles_brightest": "" if phase is None else format(phase, ".17g"),
        "phase_offset_days_brightest": "" if offset_days is None else format(offset_days, ".17g"),
        "brightest_epoch_utc": "" if brightest is None else _utc_text(brightest),
        "mean_corrected_magnitude": (
            "" if fit.mean_corrected_magnitude is None
            else format(fit.mean_corrected_magnitude, ".17g")
        ),
        "semi_amplitude_magnitude": (
            "" if fit.semi_amplitude_magnitude is None
            else format(fit.semi_amplitude_magnitude, ".17g")
        ),
        "rms_magnitude": (
            "" if fit.rms_magnitude is None else format(fit.rms_magnitude, ".17g")
        ),
        "status": fit.status,
    }


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
        return list(reader)


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def make_time_series_page(
    series: Sequence[StarSeries], *, page_number: int = 1, page_count: int = 1,
    min_period_days: float = DEFAULT_MIN_PERIOD_DAYS,
    max_period_days: float = DEFAULT_MAX_PERIOD_DAYS,
    max_catalogue_magnitude: float = DEFAULT_MAX_CATALOGUE_MAGNITUDE,
) -> plt.Figure:
    """Return one 4-by-3 chronological corrected-magnitude figure page."""

    figure, axes_grid = plt.subplots(4, 3, figsize=(11.7, 13.2), squeeze=False)
    axes = list(axes_grid.flat)
    for axis, star in zip(axes, series, strict=False):
        reference_utc = min(point.observed_utc for point in star.points)
        phase_labels: list[str] = []
        for channel in ("R", "G", "B"):
            points = sorted(
                (point for point in star.points if point.channel == channel),
                key=lambda point: point.observed_utc,
            )
            if points:
                axis.scatter(
                    [point.observed_utc for point in points],
                    [point.corrected_magnitude for point in points],
                    s=8,
                    alpha=0.75,
                    color=CHANNEL_COLOURS[channel],
                    linewidths=0,
                    zorder=2,
                )
                fit = fit_fixed_period_sine(points, star.period_days, reference_utc)
                if fit.status == "fitted":
                    assert fit.phase_offset_cycles_brightest is not None
                    assert fit.mean_corrected_magnitude is not None
                    assert fit.semi_amplitude_magnitude is not None
                    span_seconds = (
                        points[-1].observed_utc - points[0].observed_utc
                    ).total_seconds()
                    curve_times = [
                        points[0].observed_utc
                        + timedelta(seconds=span_seconds * index / 399.0)
                        for index in range(400)
                    ]
                    curve_magnitudes = [
                        fit.mean_corrected_magnitude
                        - fit.semi_amplitude_magnitude * math.cos(
                            2.0 * math.pi * (
                                (value - reference_utc).total_seconds()
                                / 86400.0 / star.period_days
                                - fit.phase_offset_cycles_brightest
                            )
                        )
                        for value in curve_times
                    ]
                    axis.plot(
                        curve_times,
                        curve_magnitudes,
                        color=CHANNEL_COLOURS[channel],
                        linewidth=0.8,
                        alpha=0.8,
                        zorder=1,
                    )
                    phase_labels.append(
                        f"{channel}={fit.phase_offset_cycles_brightest:.3f}"
                    )
        if phase_labels:
            axis.text(
                0.02,
                0.03,
                "bright phase: " + "  ".join(phase_labels),
                transform=axis.transAxes,
                fontsize=6,
                ha="left",
                va="bottom",
                bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none"},
                zorder=3,
            )
        axis.invert_yaxis()
        unique_times = sorted({point.observed_utc for point in star.points})
        if len(unique_times) == 1:
            axis.set_xlim(
                unique_times[0] - timedelta(days=1),
                unique_times[0] + timedelta(days=1),
            )
        axis.grid(alpha=0.2, linewidth=0.4)
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d", tz=UTC))
        axis.tick_params(axis="x", labelrotation=25, labelsize=7)
        axis.tick_params(axis="y", labelsize=7)
        axis.set_title(
            f"{star.vsx_name or star.vsx_oid} · {star.vsx_type or 'type ?'} · "
            f"P={star.period_days:g} d · N={len(star.points)}",
            fontsize=8,
        )
        axis.set_xlabel("Observation time (UTC)", fontsize=7)
        axis.set_ylabel("Extinction-corrected machine magnitude", fontsize=7)
    for axis in axes[len(series):]:
        axis.set_visible(False)
    handles = [
        Line2D([], [], linestyle="none", marker="o", markersize=4,
               color=CHANNEL_COLOURS[channel], label=channel)
        for channel in ("R", "G", "B")
    ]
    figure.legend(handles=handles, loc="upper center", ncol=3, frameon=False)
    figure.suptitle(
        "MMTO variable stars: nightly flux-averaged extinction-corrected machine magnitudes\n"
        f"Page {page_number} of {page_count} · "
        f"{min_period_days:g} < P < {max_period_days:g} d · "
        f"catalogue mag < {max_catalogue_magnitude:g} · "
        "no distance correction · no phase folding\n"
        "solid curves: fixed-period sine fits; phase is brightest light after each star's reference UTC",
        fontsize=11,
    )
    figure.tight_layout(rect=(0.02, 0.02, 0.98, 0.93))
    return figure


def _write_pdf(
    path: Path,
    stars: Sequence[StarSeries],
    min_period_days: float,
    max_period_days: float,
    max_catalogue_magnitude: float,
) -> int:
    page_count = max(1, math.ceil(len(stars) / 12))
    with PdfPages(path) as pdf:
        if not stars:
            figure, axis = plt.subplots(figsize=(11.7, 8.3))
            axis.axis("off")
            axis.text(
                0.5, 0.5,
                "No confirmed VSX variable has a qualifying extinction-corrected\n"
                "MMTO measurement for the requested period and UTC limits.",
                ha="center", va="center", fontsize=14,
            )
            pdf.savefig(figure)
            plt.close(figure)
        else:
            for page_index, start in enumerate(range(0, len(stars), 12), 1):
                figure = make_time_series_page(
                    stars[start:start + 12],
                    page_number=page_index,
                    page_count=page_count,
                    min_period_days=min_period_days,
                    max_period_days=max_period_days,
                    max_catalogue_magnitude=max_catalogue_magnitude,
                )
                pdf.savefig(figure)
                plt.close(figure)
    return page_count


def _prepare_output(output: Path) -> tuple[Path, bool]:
    output = Path(output)
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise FileExistsError(f"refusing to overwrite nonempty output directory: {output}")
        empty_existing = True
    else:
        empty_existing = False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".tmp-", dir=output.parent))
    return temporary, empty_existing


def generate_products(
    corrected_csv: Path,
    crossmatch_csv: Path,
    provenance_json: Path,
    output: Path,
    max_period_days: float = DEFAULT_MAX_PERIOD_DAYS,
    start_utc: datetime = DEFAULT_START_UTC,
    min_period_days: float = DEFAULT_MIN_PERIOD_DAYS,
    max_catalogue_magnitude: float = DEFAULT_MAX_CATALOGUE_MAGNITUDE,
) -> dict[str, object]:
    """Write the complete immutable variable-star product set."""

    if not math.isfinite(min_period_days) or min_period_days < 0.0:
        raise ValueError("minimum period must be nonnegative and finite")
    if not math.isfinite(max_period_days) or max_period_days <= min_period_days:
        raise ValueError("maximum period must be finite and greater than minimum period")
    if not math.isfinite(max_catalogue_magnitude):
        raise ValueError("maximum catalogue magnitude must be finite")
    if start_utc.tzinfo is None or start_utc.utcoffset() is None:
        raise ValueError("start UTC must include a timezone")
    start_utc = start_utc.astimezone(UTC)
    corrected_csv = Path(corrected_csv)
    crossmatch_csv = Path(crossmatch_csv)
    provenance_json = Path(provenance_json)
    output = Path(output)
    provenance = json.loads(provenance_json.read_text(encoding="utf-8"))
    expected_crossmatch_hash = str(provenance.get("output_csv_sha256", ""))
    actual_crossmatch_hash = _sha256(crossmatch_csv)
    if expected_crossmatch_hash != actual_crossmatch_hash:
        raise ValueError("VSX cross-match hash does not match its provenance")

    crossmatch_rows = _read_csv(crossmatch_csv, CROSSMATCH_REQUIRED)
    corrected_rows = _read_csv(corrected_csv, CORRECTED_REQUIRED)
    all_matches_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    eligible_by_key: dict[tuple[str, str], dict[str, str]] = {}
    eligible_oid_metadata: dict[str, tuple[str, str, float]] = {}
    for row in crossmatch_rows:
        key = (row["catalogue_sha256"], row["star_id"])
        all_matches_by_key[key].append(row)
        period = _finite_float(row["period_days"])
        if (
            row["selection_status"] == "eligible_catalogue_variable"
            and row["vsx_flag"] == "0"
            and period is not None
            and min_period_days < period < max_period_days
        ):
            if key in eligible_by_key:
                raise ValueError(f"multiple eligible VSX rows for local source {key}")
            eligible_by_key[key] = row
            metadata = (row["vsx_name"], row["vsx_type"], period)
            previous = eligible_oid_metadata.get(row["vsx_oid"])
            if previous is not None and previous != metadata:
                raise ValueError(f"conflicting metadata for VSX OID {row['vsx_oid']}")
            eligible_oid_metadata[row["vsx_oid"]] = metadata

    plotted_rows: list[dict[str, object]] = []
    measurement_audit: list[dict[str, object]] = []
    points_by_oid: dict[str, list[PlotPoint]] = defaultdict(list)
    plotted_count_by_key: Counter[tuple[str, str]] = Counter()
    exclusion_counts: Counter[str] = Counter()
    accepted_by_group: dict[
        tuple[str, str, str],
        list[tuple[dict[str, str], datetime, float, dict[str, str]]],
    ] = defaultdict(list)
    for row in corrected_rows:
        observed = parse_utc(row["observed_utc"])
        key = (row["catalogue_sha256"], row["star_id"])
        match = eligible_by_key.get(key)
        reason = ""
        if match is None:
            candidates = all_matches_by_key.get(key, [])
            if not candidates:
                reason = "no_vsx_match"
            elif any(
                candidate["selection_status"] == "eligible_catalogue_variable"
                for candidate in candidates
            ):
                reason = "period_outside_open_interval"
            else:
                reason = "catalogue_" + candidates[0]["selection_status"]
        elif observed < start_utc:
            reason = "before_start_utc"
        elif row["status"] != "accepted":
            reason = "corrected_status_not_accepted"
        elif row["channel"] not in CHANNEL_COLOURS:
            reason = "unsupported_channel"
        catalogue_magnitude = _finite_float(row["catalogue_magnitude"])
        if not reason and (
            catalogue_magnitude is None
            or catalogue_magnitude >= max_catalogue_magnitude
        ):
            reason = "catalogue_magnitude_not_brighter_than_limit"
        corrected = _finite_float(row["corrected_magnitude"])
        if not reason and corrected is None:
            reason = "invalid_corrected_magnitude"

        oid = "" if match is None else match["vsx_oid"]
        if reason:
            exclusion_counts[reason] += 1
            plot_status = "excluded"
        else:
            assert match is not None and corrected is not None
            plot_status = "plotted"
            plotted_count_by_key[key] += 1
            accepted_by_group[(oid, row["night"], row["channel"])].append(
                (row, observed, corrected, match)
            )
        measurement_audit.append({
            "observed_utc": row["observed_utc"],
            "source_sha256": row["source_sha256"],
            "catalogue_sha256": row["catalogue_sha256"],
            "star_id": row["star_id"],
            "channel": row["channel"],
            "catalogue_magnitude": row["catalogue_magnitude"],
            "corrected_magnitude": row["corrected_magnitude"],
            "vsx_oid": oid,
            "plot_status": plot_status,
            "exclusion_reason": reason,
        })

    for (oid, night, channel), measurements in accepted_by_group.items():
        rows = [measurement[0] for measurement in measurements]
        observed = _median_utc([measurement[1] for measurement in measurements])
        corrected = _flux_averaged_magnitude(
            [measurement[2] for measurement in measurements]
        )
        match = measurements[0][3]
        source_sha256s = ";".join(sorted({row["source_sha256"] for row in rows}))
        catalogue_sha256s = ";".join(
            sorted({row["catalogue_sha256"] for row in rows})
        )
        star_ids = ";".join(sorted({row["star_id"] for row in rows}))
        catalogue_magnitudes = ";".join(
            sorted({row["catalogue_magnitude"] for row in rows})
        )
        points_by_oid[oid].append(PlotPoint(
            observed_utc=observed,
            channel=channel,
            corrected_magnitude=corrected,
            source_sha256=source_sha256s,
            catalogue_sha256=catalogue_sha256s,
            star_id=star_ids,
        ))
        plotted_rows.append({
            "vsx_oid": oid,
            "vsx_name": match["vsx_name"],
            "vsx_type": match["vsx_type"],
            "period_days": match["period_days"],
            "night": night,
            "observed_utc": observed.isoformat().replace("+00:00", "Z"),
            "channel": channel,
            "flux_averaged_corrected_magnitude": format(corrected, ".17g"),
            "contributing_measurement_count": len(measurements),
            "catalogue_magnitudes": catalogue_magnitudes,
            "source_sha256s": source_sha256s,
            "catalogue_sha256s": catalogue_sha256s,
            "star_ids": star_ids,
        })

    plotted_rows.sort(
        key=lambda row: (
            parse_utc(str(row["observed_utc"])), str(row["channel"]),
            str(row["vsx_oid"]),
        )
    )
    measurement_audit.sort(
        key=lambda row: (
            parse_utc(str(row["observed_utc"])), str(row["channel"]),
            str(row["catalogue_sha256"]), str(row["star_id"]),
        )
    )
    stars = [
        StarSeries(
            vsx_oid=oid,
            vsx_name=eligible_oid_metadata[oid][0],
            vsx_type=eligible_oid_metadata[oid][1],
            period_days=eligible_oid_metadata[oid][2],
            points=tuple(sorted(points, key=lambda point: (point.observed_utc, point.channel))),
        )
        for oid, points in points_by_oid.items()
    ]
    stars.sort(key=lambda star: (star.period_days, star.vsx_name, star.vsx_oid))
    sine_fits_by_oid: dict[str, tuple[SineFit, ...]] = {}
    sine_fit_rows: list[dict[str, object]] = []
    for star in stars:
        reference_utc = min(point.observed_utc for point in star.points)
        fits = tuple(
            fit_fixed_period_sine(
                [point for point in star.points if point.channel == channel],
                star.period_days,
                reference_utc,
            )
            for channel in ("R", "G", "B")
            if any(point.channel == channel for point in star.points)
        )
        sine_fits_by_oid[star.vsx_oid] = fits
        sine_fit_rows.extend(_sine_fit_row(star, fit) for fit in fits)

    selection_audit: list[dict[str, object]] = []
    plotted_oids = set(points_by_oid)
    for row in crossmatch_rows:
        key = (row["catalogue_sha256"], row["star_id"])
        period = _finite_float(row["period_days"])
        if row["selection_status"] != "eligible_catalogue_variable":
            plot_selection = row["selection_status"]
        elif period is None or not (min_period_days < period < max_period_days):
            plot_selection = "period_outside_open_interval"
        elif row["vsx_oid"] in plotted_oids:
            plot_selection = "plotted"
        else:
            plot_selection = "no_qualifying_measurements"
        selection_audit.append({
            "catalogue_sha256": row["catalogue_sha256"],
            "star_id": row["star_id"],
            "vsx_oid": row["vsx_oid"],
            "vsx_name": row["vsx_name"],
            "vsx_flag": row["vsx_flag"],
            "vsx_type": row["vsx_type"],
            "period_days": row["period_days"],
            "catalogue_selection_status": row["selection_status"],
            "plot_selection_status": plot_selection,
            "plotted_measurement_count": plotted_count_by_key[key],
        })

    temporary, empty_existing = _prepare_output(output)
    try:
        _write_csv(temporary / "variable_star_measurements.csv", MEASUREMENT_FIELDS, plotted_rows)
        _write_csv(
            temporary / "variable_star_selection_audit.csv",
            SELECTION_AUDIT_FIELDS,
            selection_audit,
        )
        _write_csv(
            temporary / "variable_star_measurement_audit.csv",
            MEASUREMENT_AUDIT_FIELDS,
            measurement_audit,
        )
        _write_csv(
            temporary / "variable_star_sine_fits.csv",
            SINE_FIT_FIELDS,
            sine_fit_rows,
        )
        page_count = _write_pdf(
            temporary / "variable_star_time_series.pdf",
            stars,
            min_period_days,
            max_period_days,
            max_catalogue_magnitude,
        )
        outputs = (
            "variable_star_time_series.pdf",
            "variable_star_measurements.csv",
            "variable_star_selection_audit.csv",
            "variable_star_measurement_audit.csv",
            "variable_star_sine_fits.csv",
        )
        summary: dict[str, object] = {
            "schema_version": 1,
            "created_utc": datetime.now(UTC).isoformat(),
            "formula": "m_corrected = m_machine - k_night,channel X",
            "nightly_flux_average_formula": (
                "m_night = -2.5 log10(mean(10^(-0.4 m_corrected)))"
            ),
            "distance_correction_applied": False,
            "phase_folding_applied": False,
            "fixed_period_sine_fit_applied": True,
            "fixed_period_sine_formula": (
                "m(t) = mean - semi_amplitude*cos(2*pi*((t-reference)/period-phase_brightest))"
            ),
            "sine_fit_weighting": "unweighted nightly points",
            "min_period_days_exclusive": min_period_days,
            "max_period_days_exclusive": max_period_days,
            "max_catalogue_magnitude_exclusive": max_catalogue_magnitude,
            "start_utc_inclusive": start_utc.isoformat().replace("+00:00", "Z"),
            "selected_star_count": len(stars),
            "page_count": page_count,
            "plotted_point_count": len(plotted_rows),
            "fitted_channel_count": sum(
                fit.status == "fitted"
                for fits in sine_fits_by_oid.values()
                for fit in fits
            ),
            "sine_fit_status_counts": dict(sorted(Counter(
                fit.status
                for fits in sine_fits_by_oid.values()
                for fit in fits
            ).items())),
            "contributing_measurement_count": sum(
                len(measurements) for measurements in accepted_by_group.values()
            ),
            "per_channel_counts": dict(sorted(Counter(row["channel"] for row in plotted_rows).items())),
            "excluded_pre_boundary_count": exclusion_counts["before_start_utc"],
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
            "catalogue_provenance": provenance,
            "inputs": {
                "corrected_csv": str(corrected_csv.resolve()),
                "corrected_csv_sha256": _sha256(corrected_csv),
                "crossmatch_csv": str(crossmatch_csv.resolve()),
                "crossmatch_csv_sha256": actual_crossmatch_hash,
                "provenance_json_sha256": _sha256(provenance_json),
            },
            "output_sha256": {
                name: _sha256(temporary / name) for name in outputs
            },
            "outputs": list(outputs) + ["variable_star_summary.json"],
        }
        (temporary / "variable_star_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if empty_existing:
            output.rmdir()
        temporary.replace(output)
        return summary
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nightly-calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crossmatch", type=Path, default=DATA / "vsx_crossmatch.csv")
    parser.add_argument(
        "--crossmatch-provenance",
        type=Path,
        default=DATA / "vsx_crossmatch.provenance.json",
    )
    parser.add_argument("--min-period-days", type=float, default=DEFAULT_MIN_PERIOD_DAYS)
    parser.add_argument("--max-period-days", type=float, default=DEFAULT_MAX_PERIOD_DAYS)
    parser.add_argument(
        "--max-catalogue-magnitude",
        type=float,
        default=DEFAULT_MAX_CATALOGUE_MAGNITUDE,
    )
    parser.add_argument(
        "--start-utc",
        type=parse_utc,
        default=DEFAULT_START_UTC,
        help="inclusive UTC lower boundary; default excludes the isolated March datum",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    corrected = args.nightly_calibration / "corrected_stellar_photometry.csv"
    try:
        summary = generate_products(
            corrected,
            args.crossmatch,
            args.crossmatch_provenance,
            args.output,
            args.max_period_days,
            args.start_utc,
            args.min_period_days,
            args.max_catalogue_magnitude,
        )
    except (OSError, ValueError) as exc:
        print(f"Variable-star plotting failed: {exc}")
        return 2
    print(
        f"Variable-star time series: {summary['selected_star_count']} stars, "
        f"{summary['plotted_point_count']} points, {summary['page_count']} pages"
    )
    print(Path(args.output).resolve() / "variable_star_time_series.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
