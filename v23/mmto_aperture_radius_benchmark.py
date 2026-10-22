"""Aperture/annulus geometry and guarded selection for the v23 MMTO sweep."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from collections import defaultdict
import hashlib
import csv
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Iterable, Mapping

import numpy as np


CHANNELS = ("R", "G", "B")
CONTROL_NAME = "current_scaled_2.50"
TREND_FIELDS = (
    "magnitude_trend_mag",
    "psf_width_trend_mag",
    "field_radius_trend_mag",
    "airmass_trend_mag",
)


@dataclass(frozen=True, slots=True)
class ApertureGeometry:
    name: str
    mode: str
    value: float
    minimum_px: float
    maximum_px: float
    annulus_gap_px: float = 3.0
    annulus_width_px: float = 4.0
    annulus_gap_sigma: float = 0.0
    annulus_width_sigma: float = 0.0

    def aperture_radius(self, major_sigma_px: float) -> float:
        sigma = float(major_sigma_px)
        if not math.isfinite(sigma) or sigma <= 0:
            raise ValueError("major_sigma_px must be positive and finite")
        raw = self.value if self.mode == "fixed" else self.value * sigma
        if self.mode not in {"fixed", "scaled"}:
            raise ValueError(f"unknown aperture mode: {self.mode}")
        return float(min(self.maximum_px, max(self.minimum_px, raw)))

    def annulus_radii(self, major_sigma_px: float) -> tuple[float, float]:
        aperture = self.aperture_radius(major_sigma_px)
        sigma = float(major_sigma_px)
        inner = aperture + self.annulus_gap_px + self.annulus_gap_sigma * sigma
        width = self.annulus_width_px + self.annulus_width_sigma * sigma
        return float(inner), float(inner + width)


def current_geometry() -> ApertureGeometry:
    return ApertureGeometry(
        name=CONTROL_NAME,
        mode="scaled",
        value=2.5,
        minimum_px=3.0,
        maximum_px=9.0,
    )


def candidate_geometries() -> tuple[ApertureGeometry, ...]:
    """Return the declared aperture sweep with the v22 rule as control."""

    answer = [current_geometry()]
    answer.extend(
        ApertureGeometry(
            name=f"fixed_{radius:.2f}", mode="fixed", value=radius,
            minimum_px=radius, maximum_px=radius,
        )
        for radius in (2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0)
    )
    answer.extend(
        ApertureGeometry(
            name=f"scaled_{factor:.2f}", mode="scaled", value=factor,
            minimum_px=2.0, maximum_px=12.0,
        )
        for factor in (1.5, 2.0, 3.0, 3.5, 4.0)
    )
    return tuple(answer)


def annulus_geometries(aperture: ApertureGeometry) -> tuple[ApertureGeometry, ...]:
    """Hold the aperture fixed while testing plausible local-sky annuli."""

    answer = []
    for gap in (2.0, 3.0, 4.0, 5.0, 7.0):
        for width in (3.0, 4.0, 6.0, 8.0):
            answer.append(replace(
                aperture,
                name=f"{aperture.name}_gap_{gap:.0f}_width_{width:.0f}",
                annulus_gap_px=gap,
                annulus_width_px=width,
                annulus_gap_sigma=0.0,
                annulus_width_sigma=0.0,
            ))
    for gap_sigma in (1.0, 2.0, 3.0):
        for width_sigma in (2.0, 3.0, 4.0):
            answer.append(replace(
                aperture,
                name=(f"{aperture.name}_gap_{gap_sigma:.1f}sigma_"
                      f"width_{width_sigma:.1f}sigma"),
                annulus_gap_px=0.0,
                annulus_width_px=0.0,
                annulus_gap_sigma=gap_sigma,
                annulus_width_sigma=width_sigma,
            ))
    return tuple(answer)


def assign_night_roles(nights: Iterable[str]) -> dict[str, str]:
    """Assign complete nights to stable 60/20/20 train/validation/test roles."""

    unique = sorted(set(str(night) for night in nights))
    ordered = sorted(
        unique,
        key=lambda night: hashlib.sha256(
            f"v23-aperture-radius:{night}".encode("utf-8")
        ).hexdigest(),
    )
    count = len(ordered)
    if count < 5:
        raise ValueError("at least five nights are required for held-out scoring")
    train_end = int(round(0.6 * count))
    validation_end = train_end + int(round(0.2 * count))
    return {
        night: ("train" if index < train_end else
                "validation" if index < validation_end else "test")
        for index, night in enumerate(ordered)
    }


def _complexity(name: str) -> tuple[int, int, str]:
    return (0 if name.startswith("fixed_") else 1, len(name), name)


def _median(values: Iterable[float]) -> float:
    array = np.asarray(tuple(values), dtype=float)
    return float(np.median(array))


def _trend_amplitude(rows: list[tuple[Mapping[str, object], float]], field: str) -> float:
    pairs = [
        (float(row[field]), residual)
        for row, residual in rows
        if row.get(field) is not None
        and math.isfinite(float(row[field]))
        and math.isfinite(residual)
    ]
    if len(pairs) < 20:
        return float("nan")
    x = np.asarray([pair[0] for pair in pairs], dtype=float)
    y = np.asarray([pair[1] for pair in pairs], dtype=float)
    low, high = np.quantile(x, (0.1, 0.9))
    use = (x >= low) & (x <= high)
    if use.sum() < 20 or high <= low:
        return float("nan")
    slope = float(np.polyfit(x[use], y[use], 1)[0])
    return abs(slope) * float(high - low)


def score_geometry(
    rows: Iterable[Mapping[str, object]],
    geometry_field: str,
    *,
    evaluation_role: str,
) -> dict[str, object]:
    """Score held-out differential repeatability using train-only star baselines."""

    usable = []
    for row in rows:
        try:
            magnitude = float(row[geometry_field])
            catalogue = float(row["catalogue_magnitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(magnitude) and math.isfinite(catalogue):
            usable.append((row, magnitude - catalogue))

    train = [(row, raw) for row, raw in usable if row.get("role") == "train"]
    image_values: dict[str, list[float]] = defaultdict(list)
    for row, raw in train:
        image_values[str(row["run_id"])].append(raw)
    image_medians = {run_id: _median(values) for run_id, values in image_values.items()}
    star_values: dict[str, list[float]] = defaultdict(list)
    for row, raw in train:
        star_values[str(row["star_id"])].append(raw - image_medians[str(row["run_id"])])
    star_baselines = {star_id: _median(values) for star_id, values in star_values.items()}

    evaluation = [(row, raw) for row, raw in usable
                  if row.get("role") == evaluation_role]
    missing = {str(row["star_id"]) for row, _raw in evaluation
               if str(row["star_id"]) not in star_baselines}
    preliminary: list[tuple[Mapping[str, object], float]] = []
    by_image: dict[str, list[float]] = defaultdict(list)
    for row, raw in evaluation:
        baseline = star_baselines.get(str(row["star_id"]))
        if baseline is None:
            continue
        value = raw - baseline
        preliminary.append((row, value))
        by_image[str(row["run_id"])].append(value)
    evaluation_medians = {
        run_id: _median(values) for run_id, values in by_image.items()
    }
    residual_rows = [
        (row, value - evaluation_medians[str(row["run_id"])])
        for row, value in preliminary
    ]
    residuals = np.asarray([value for _row, value in residual_rows], dtype=float)
    if residuals.size:
        q16, q84 = np.quantile(residuals, (0.16, 0.84))
        scatter = float(0.5 * (q84 - q16))
    else:
        scatter = float("nan")
    channels = {str(row.get("channel", "")) for row, _value in residual_rows}
    return {
        "geometry": geometry_field,
        "channel": next(iter(channels)) if len(channels) == 1 else "",
        "evaluation_role": evaluation_role,
        "robust_sigma_mag": scatter,
        "usable_rows": int(residuals.size),
        "stars_without_train_baseline": len(missing),
        "magnitude_trend_mag": _trend_amplitude(
            residual_rows, "catalogue_magnitude"),
        "psf_width_trend_mag": _trend_amplitude(
            residual_rows, "major_sigma_px"),
        "field_radius_trend_mag": _trend_amplitude(
            residual_rows, "field_radius_fraction"),
        "airmass_trend_mag": _trend_amplitude(residual_rows, "airmass"),
    }


def apply_trend_gates(
    metrics: Iterable[Mapping[str, object]],
    *,
    control_name: str,
    absolute_tolerance_mag: float = 0.005,
    relative_tolerance: float = 0.10,
) -> list[dict[str, object]]:
    """Reject a candidate when it introduces a larger held-out residual trend."""

    rows = [dict(row) for row in metrics]
    control = {
        str(row["channel"]): row
        for row in rows
        if str(row["geometry"]) == control_name
    }
    if set(control) != set(CHANNELS):
        raise ValueError("trend control must contain R, G and B")
    for row in rows:
        failures = []
        channel = str(row["channel"])
        if str(row["geometry"]) != control_name:
            for field in TREND_FIELDS:
                reference = float(control[channel].get(field, float("nan")))
                candidate = float(row.get(field, float("nan")))
                if math.isfinite(reference):
                    limit = max(
                        reference + absolute_tolerance_mag,
                        reference * (1.0 + relative_tolerance),
                    )
                    if not math.isfinite(candidate) or candidate > limit:
                        failures.append(field)
        row["trend_gate_passed"] = not failures
        row["trend_gate_failures"] = tuple(failures)
    return rows


def select_geometry(
    metrics: Iterable[Mapping[str, object]],
    *,
    minimum_gain_fraction: float = 0.02,
    equivalence_fraction: float = 0.01,
    control_name: str = CONTROL_NAME,
) -> dict[str, object]:
    """Select one global RGB geometry, or retain the declared control."""

    grouped: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in metrics:
        name = str(row["geometry"])
        channel = str(row["channel"])
        if channel in CHANNELS:
            grouped.setdefault(name, {})[channel] = row
    control = grouped.get(control_name, {})
    if set(control) != set(CHANNELS):
        raise ValueError("control metrics must contain exactly R, G and B")

    passing: list[tuple[str, float]] = []
    rejected: dict[str, tuple[str, ...]] = {}
    for name, by_channel in sorted(grouped.items()):
        if name == control_name:
            continue
        reasons = []
        if set(by_channel) != set(CHANNELS):
            reasons.append("missing_channel")
        else:
            for channel in CHANNELS:
                row = by_channel[channel]
                sigma = float(row["robust_sigma_mag"])
                control_sigma = float(control[channel]["robust_sigma_mag"])
                if not math.isfinite(sigma) or sigma <= 0:
                    reasons.append(f"{channel}_invalid_scatter")
                elif sigma > control_sigma * (1.0 - minimum_gain_fraction):
                    reasons.append(f"{channel}_insufficient_gain")
                if not bool(row.get("trend_gate_passed", False)):
                    reasons.append(f"{channel}_trend")
                if int(row.get("usable_rows", 0)) <= 0:
                    reasons.append(f"{channel}_no_rows")
        if reasons:
            rejected[name] = tuple(reasons)
        else:
            objective = sum(
                float(by_channel[channel]["robust_sigma_mag"])
                for channel in CHANNELS
            ) / len(CHANNELS)
            passing.append((name, objective))

    if not passing:
        return {
            "status": "no_candidate_passed",
            "selected_geometry": control_name,
            "control_geometry": control_name,
            "rejected": rejected,
        }
    best = min(value for _name, value in passing)
    equivalent = [
        (name, value) for name, value in passing
        if value <= best * (1.0 + equivalence_fraction)
    ]
    selected, objective = min(equivalent, key=lambda item: _complexity(item[0]))
    return {
        "status": "selected",
        "selected_geometry": selected,
        "control_geometry": control_name,
        "validation_mean_robust_sigma_mag": objective,
        "rejected": rejected,
    }


def adoption_decision(
    final_selection: Mapping[str, object],
    *,
    reused_opened_test_nights: bool,
) -> dict[str, object]:
    """Prevent a follow-up hypothesis from adopting on already opened nights."""

    proposed = str(final_selection["selected_geometry"])
    if reused_opened_test_nights and proposed != CONTROL_NAME:
        return {
            "status": "requires_new_independent_confirmation",
            "proposed_geometry": proposed,
            "adopted_geometry": CONTROL_NAME,
        }
    return {
        "status": str(final_selection["status"]),
        "proposed_geometry": proposed,
        "adopted_geometry": proposed,
    }


def sampled_night_count(rows: Iterable[Mapping[str, object]]) -> int:
    """Count observed nights without relying on full run-record objects."""

    return len({str(row["night"]) for row in rows})


def _representative_run_ids(runs, maximum_per_night: int) -> frozenset[str]:
    by_night = defaultdict(list)
    for run in runs:
        by_night[run.night].append(run)
    selected = set()
    for night, night_runs in by_night.items():
        ordered = sorted(
            night_runs,
            key=lambda run: hashlib.sha256(
                f"v23-aperture-run:{run.run_id}".encode("utf-8")
            ).hexdigest(),
        )
        selected.update(run.run_id for run in ordered[:maximum_per_night])
    return frozenset(selected)


def _repeat_star_ids(stellar, run_ids: frozenset[str], maximum_stars: int) -> frozenset[str]:
    by_star: dict[str, set[str]] = defaultdict(set)
    magnitudes: dict[str, list[float]] = defaultdict(list)
    for row in stellar:
        if row.run_id in run_ids:
            by_star[row.star_id].add(row.run_id)
            magnitudes[row.star_id].append(row.catalogue_magnitude)
    bins: dict[int, list[str]] = defaultdict(list)
    for star_id, values in magnitudes.items():
        bins[min(7, max(0, int(math.floor(_median(values)))))] .append(star_id)
    chosen = []
    per_bin = max(1, math.ceil(maximum_stars / max(1, len(bins))))
    for bin_id in sorted(bins):
        ordered = sorted(
            bins[bin_id],
            key=lambda star_id: (
                -len(by_star[star_id]),
                hashlib.sha256(star_id.encode("utf-8")).hexdigest(),
            ),
        )
        chosen.extend(ordered[:per_bin])
    if len(chosen) < maximum_stars:
        remaining = sorted(
            set(magnitudes) - set(chosen),
            key=lambda star_id: (
                -len(by_star[star_id]),
                hashlib.sha256(star_id.encode("utf-8")).hexdigest(),
            ),
        )
        chosen.extend(remaining[: maximum_stars - len(chosen)])
    return frozenset(chosen[:maximum_stars])


def _channel_arrays(image):
    planes = image.planes
    masks = image.plane_saturated_masks
    if set(planes) == {"R", "G1", "G2", "B"}:
        pixels = {
            "R": planes["R"],
            "G": (np.asarray(planes["G1"], float) + np.asarray(planes["G2"], float)) / 2.0,
            "B": planes["B"],
        }
        saturated = {
            "R": masks["R"],
            "G": masks["G1"] | masks["G2"],
            "B": masks["B"],
        }
    elif set(planes) == {"R", "G", "B"}:
        pixels = {channel: planes[channel] for channel in CHANNELS}
        saturated = {channel: masks[channel] for channel in CHANNELS}
    elif set(planes) == {"L"}:
        pixels = {channel: planes["L"] for channel in CHANNELS}
        saturated = {channel: masks["L"] for channel in CHANNELS}
    else:
        raise ValueError(f"unsupported scientific planes: {sorted(planes)}")
    return pixels, saturated


def _base_rows(data, run_ids: frozenset[str], star_ids: frozenset[str]):
    roles = assign_night_roles(run.night for run in data.runs if run.run_id in run_ids)
    answer = []
    for row in data.stellar:
        if row.run_id not in run_ids or row.star_id not in star_ids:
            continue
        if row.major_sigma_px is None or row.major_sigma_px <= 0:
            continue
        cx = 0.5 * (row.image_width_px - 1)
        cy = 0.5 * (row.image_height_px - 1)
        normalizer = 0.5 * min(row.image_width_px, row.image_height_px)
        answer.append({
            "role": roles[row.night],
            "night": row.night,
            "run_id": row.run_id,
            "source_sha256": row.source_sha256,
            "star_id": row.star_id,
            "detection_id": row.detection_id,
            "channel": row.channel,
            "catalogue_magnitude": row.catalogue_magnitude,
            "major_sigma_px": row.major_sigma_px,
            "field_radius_fraction": math.hypot(row.x_px - cx, row.y_px - cy) / normalizer,
            "airmass": row.airmass,
            "x_px": row.x_px,
            "y_px": row.y_px,
            "exposure_seconds": row.exposure_seconds,
            "saved_machine_magnitude": row.machine_magnitude,
        })
    return answer


def load_reused_aperture_rows(
    directory: Path,
    *,
    database: Path,
    manifest: Path,
    v21_control: Path,
    aperture_names: Iterable[str],
) -> list[dict[str, object]]:
    """Load a completed aperture pass only when its immutable inputs match."""

    directory = Path(directory)
    summary = json.loads((directory / "benchmark_summary.json").read_text())
    expected = {
        "database": str(Path(database).resolve()),
        "manifest": str(Path(manifest).resolve()),
        "v21_control": str(Path(v21_control).resolve()),
    }
    for field, value in expected.items():
        if str(Path(summary.get(field, "")).resolve()) != value:
            raise ValueError(f"reused aperture input mismatch: {field}")
    numeric = {
        "catalogue_magnitude", "major_sigma_px", "field_radius_fraction",
        "airmass", "x_px", "y_px", "exposure_seconds",
        "saved_machine_magnitude", *aperture_names,
    }
    with (directory / "radius_measurements.csv").open(
            newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = set(aperture_names) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"reused aperture columns are missing: {sorted(missing)}")
        rows = []
        for raw in reader:
            row: dict[str, object] = dict(raw)
            for field in numeric:
                value = raw.get(field)
                if value not in (None, ""):
                    row[field] = float(value)
            rows.append(row)
    return rows


def _reuse_run_sources_and_positions(database: Path, rows):
    run_ids = sorted({str(row["run_id"]) for row in rows})
    placeholders = ",".join("?" for _ in run_ids)
    uri = f"file:{Path(database).resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as connection:
        connection.execute("PRAGMA query_only=ON")
        run_by_id = {
            str(run_id): SimpleNamespace(run_id=str(run_id), source_path=str(source_path))
            for run_id, source_path in connection.execute(
                f"SELECT run_id,source_path FROM runs WHERE run_id IN ({placeholders})",
                run_ids,
            )
        }
        coordinates = {}
        for run_id, star_id, detection_id, raw in connection.execute(
            f"""SELECT run_id,star_id,detection_id,values_json FROM measurements
                WHERE product='star_coordinates.csv' AND run_id IN ({placeholders})""",
            run_ids,
        ):
            values = json.loads(raw)
            coordinates[(str(run_id), str(star_id), str(detection_id))] = (
                float(values["x_px"]), float(values["y_px"]),
            )
    if set(run_by_id) != set(run_ids):
        raise ValueError("reused aperture run IDs are absent from the database")
    for row in rows:
        if row.get("x_px") is None or row.get("y_px") is None:
            key = (str(row["run_id"]), str(row["star_id"]), str(row["detection_id"]))
            try:
                row["x_px"], row["y_px"] = coordinates[key]
            except KeyError as error:
                raise ValueError(f"missing reused coordinate: {key}") from error
    return run_by_id


def _measure_geometries(rows, run_by_id, geometries, *, progress=None):
    from .point_star_image import load_scientific_image
    from .point_star_photometry import measure_channel

    by_run: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_run[str(row["run_id"])].append(row)
    for index, run_id in enumerate(sorted(by_run), 1):
        run = run_by_id[run_id]
        image = load_scientific_image(run.source_path)
        channel_pixels, channel_saturated = _channel_arrays(image)
        exposure = (image.provenance().get("exposure") or {}).get("seconds")
        for row in by_run[run_id]:
            sigma = float(row["major_sigma_px"])
            channel = str(row["channel"])
            for geometry in geometries:
                aperture = geometry.aperture_radius(sigma)
                inner, outer = geometry.annulus_radii(sigma)
                measured = measure_channel(
                    channel_pixels[channel], image.valid_mask,
                    channel_saturated[channel],
                    x=float(row["x_px"]), y=float(row["y_px"]),
                    aperture_radius=aperture,
                    annulus_inner_radius=inner,
                    annulus_outer_radius=outer,
                    exposure_seconds=float(row.get("exposure_seconds") or exposure),
                )
                rate = float(measured["count_rate_adu_per_s"])
                row[geometry.name] = (
                    -2.5 * math.log10(rate)
                    if measured["measurement_method"] == "aperture"
                    and math.isfinite(rate) and rate > 0 else float("nan")
                )
        if progress is not None:
            progress(index, len(by_run), run.source_path)


def _score(rows, geometries, role: str):
    metrics = []
    for geometry in geometries:
        for channel in CHANNELS:
            subset = [row for row in rows if row["channel"] == channel]
            metrics.append(score_geometry(
                subset, geometry.name, evaluation_role=role))
    return metrics


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields=None):
    materialized = [dict(row) for row in rows]
    if fields is None:
        fields = tuple(dict.fromkeys(
            key for row in materialized for key in row
        ))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)


def _plot_metrics(path: Path, metrics, title: str):
    import matplotlib.pyplot as plt

    names = list(dict.fromkeys(str(row["geometry"]) for row in metrics))
    figure, axis = plt.subplots(figsize=(max(10.0, 0.52 * len(names)), 6.5))
    x = np.arange(len(names), dtype=float)
    offsets = {"R": -0.24, "G": 0.0, "B": 0.24}
    colours = {"R": "#c43b3b", "G": "#31824a", "B": "#3568b8"}
    for channel in CHANNELS:
        lookup = {
            str(row["geometry"]): float(row["robust_sigma_mag"])
            for row in metrics if row["channel"] == channel
        }
        axis.plot(x + offsets[channel], [lookup.get(name, np.nan) for name in names],
                  "o-", color=colours[channel], label=channel, linewidth=1.2)
    axis.set_xticks(x, names, rotation=55, ha="right")
    axis.set_ylabel("Held-out robust scatter (mag)")
    axis.set_title(title)
    axis.grid(alpha=0.25)
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def final_comparison_names(metrics: Iterable[Mapping[str, object]]) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(str(row["geometry"]) for row in metrics))
    if CONTROL_NAME not in names:
        raise ValueError("final comparison lacks the declared control")
    return (CONTROL_NAME, *[name for name in names if name != CONTROL_NAME])


def annulus_summary_names(
    metrics: Iterable[Mapping[str, object]],
    control_name: str,
) -> tuple[str, ...]:
    """Keep the control and lowest-scatter member of each annulus family."""

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in metrics:
        grouped[str(row["geometry"])].append(float(row["robust_sigma_mag"]))
    if control_name not in grouped:
        raise ValueError("annulus summary lacks its control")

    def best(names: Iterable[str]) -> str | None:
        eligible = [name for name in names if len(grouped[name]) == len(CHANNELS)]
        if not eligible:
            return None
        return min(eligible, key=lambda name: sum(grouped[name]) / len(CHANNELS))

    alternatives = [name for name in grouped if name != control_name]
    fixed = best(name for name in alternatives if "sigma" not in name)
    scaled = best(name for name in alternatives if "sigma" in name)
    return tuple(name for name in (control_name, fixed, scaled) if name is not None)


def _plot_annulus_summary(path: Path, metrics, control_name: str):
    import matplotlib.pyplot as plt

    names = annulus_summary_names(metrics, control_name)
    labels = ("Present +3/+7 px", "Best fixed alternative",
              "Best blob-scaled alternative")[:len(names)]
    colours = ("#3568b8", "#dd7f1d", "#5b9c47")
    figure, axis = plt.subplots(figsize=(12, 6.5))
    x = np.arange(len(CHANNELS), dtype=float)
    width = 0.23
    for number, (name, label) in enumerate(zip(names, labels)):
        lookup = {
            str(row["channel"]): float(row["robust_sigma_mag"])
            for row in metrics if row["geometry"] == name
        }
        axis.bar(
            x + (number - (len(names) - 1) / 2) * width,
            [lookup.get(channel, np.nan) for channel in CHANNELS],
            width=width, label=label, color=colours[number],
        )
    axis.set_xticks(x, CHANNELS, fontsize=15)
    axis.tick_params(axis="y", labelsize=13)
    axis.set_ylabel("Validation scatter (mag; lower is better)", fontsize=14)
    axis.set_title("v23 sky-annulus decision", fontsize=18)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(frameon=False, fontsize=13)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def _plot_final(path: Path, validation, test):
    import matplotlib.pyplot as plt

    names = final_comparison_names(test)
    figure, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)
    for axis, rows, role in zip(axes, (validation, test), ("Validation", "Final test")):
        x = np.arange(len(CHANNELS), dtype=float)
        width = 0.34
        for number, name in enumerate(names):
            lookup = {
                str(row["channel"]): float(row["robust_sigma_mag"])
                for row in rows if row["geometry"] == name
            }
            axis.bar(x + (number - (len(names) - 1) / 2) * width,
                     [lookup.get(channel, np.nan) for channel in CHANNELS],
                     width=width, label=name)
        axis.set_xticks(x, CHANNELS)
        axis.set_title(role)
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Robust differential scatter (mag)")
    axes[1].legend(frameon=False, fontsize=8)
    figure.suptitle("v23 aperture-radius decision")
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def run_aperture_benchmark(
    database: Path,
    manifest: Path,
    v21_control: Path,
    output: Path,
    *,
    maximum_runs_per_night: int = 2,
    maximum_stars: int = 128,
    reuse_aperture_run: Path | None = None,
    progress=None,
) -> dict[str, object]:
    """Remeasure native FITS, select on validation nights, and open test once."""

    from .mmto_differential_data import (
        load_measurements, load_v21_control, require_matching_runs,
    )

    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    apertures = candidate_geometries()
    if reuse_aperture_run is None:
        control = load_v21_control(v21_control)
        data = load_measurements(
            database, manifest, input_solver_version="0.21.0",
            run_ids=control.selected_run_ids,
        )
        require_matching_runs(control, data)
        run_ids = _representative_run_ids(data.runs, maximum_runs_per_night)
        star_ids = _repeat_star_ids(data.stellar, run_ids, maximum_stars)
        rows = _base_rows(data, run_ids, star_ids)
        run_by_id = {run.run_id: run for run in data.runs if run.run_id in run_ids}
        _measure_geometries(rows, run_by_id, apertures, progress=progress)
    else:
        rows = load_reused_aperture_rows(
            reuse_aperture_run, database=database, manifest=manifest,
            v21_control=v21_control,
            aperture_names=tuple(geometry.name for geometry in apertures),
        )
        run_by_id = _reuse_run_sources_and_positions(database, rows)
        run_ids = frozenset(run_by_id)
        star_ids = frozenset(str(row["star_id"]) for row in rows)
    validation_aperture = apply_trend_gates(
        _score(rows, apertures, "validation"), control_name=CONTROL_NAME)
    aperture_selection = select_geometry(validation_aperture)
    aperture_by_name = {geometry.name: geometry for geometry in apertures}
    chosen_aperture = aperture_by_name[str(aperture_selection["selected_geometry"])]

    annuli = annulus_geometries(chosen_aperture)
    _measure_geometries(rows, run_by_id, annuli, progress=progress)
    annulus_control = next(
        geometry.name for geometry in annuli
        if geometry.annulus_gap_px == 3.0 and geometry.annulus_width_px == 4.0
    )
    validation_annulus = apply_trend_gates(
        _score(rows, annuli, "validation"), control_name=annulus_control)
    annulus_selection = select_geometry(
        validation_annulus, control_name=annulus_control)
    chosen_name = str(annulus_selection["selected_geometry"])
    chosen_geometry = {geometry.name: geometry for geometry in annuli}[chosen_name]

    final_candidates = [current_geometry()]
    if chosen_geometry != current_geometry():
        final_candidates.append(chosen_geometry)
    validation_final = apply_trend_gates(
        _score(rows, final_candidates, "validation"), control_name=CONTROL_NAME)
    test_final = apply_trend_gates(
        _score(rows, final_candidates, "test"), control_name=CONTROL_NAME)
    if len(final_candidates) == 1:
        final_selection = {
            "status": "control_retained",
            "selected_geometry": CONTROL_NAME,
            "control_geometry": CONTROL_NAME,
        }
    else:
        final_selection = select_geometry(test_final)
    adoption = adoption_decision(
        final_selection,
        reused_opened_test_nights=reuse_aperture_run is not None,
    )
    adopted = str(adoption["adopted_geometry"])

    measurement_fields = (
        "role", "night", "run_id", "source_sha256", "star_id",
        "detection_id", "channel", "catalogue_magnitude",
        "major_sigma_px", "field_radius_fraction", "airmass",
        "x_px", "y_px", "exposure_seconds",
        "saved_machine_magnitude",
        *[geometry.name for geometry in apertures],
        *[geometry.name for geometry in annuli],
    )
    _write_csv(output / "radius_measurements.csv", rows, measurement_fields)
    _write_csv(output / "aperture_validation_metrics.csv", validation_aperture)
    _write_csv(output / "annulus_validation_metrics.csv", validation_annulus)
    _write_csv(output / "final_validation_metrics.csv", validation_final)
    _write_csv(output / "final_test_metrics.csv", test_final)
    _plot_metrics(
        output / "aperture_radius_comparison.pdf", validation_aperture,
        "Validation nights: aperture-radius sweep (annulus offsets fixed)")
    _plot_metrics(
        output / "sky_annulus_comparison.pdf", validation_annulus,
        "Validation nights: sky-annulus sweep around selected aperture")
    _plot_annulus_summary(
        output / "annulus_decision.pdf", validation_annulus, annulus_control)
    _plot_final(output / "final_radius_test.pdf", validation_final, test_final)
    role_counts = defaultdict(int)
    for row in rows:
        role_counts[str(row["role"])] += 1
    summary = {
        "status": "complete",
        "input_solver_version": "0.21.0",
        "database": str(Path(database).resolve()),
        "manifest": str(Path(manifest).resolve()),
        "v21_control": str(Path(v21_control).resolve()),
        "sampled_runs": len(run_ids),
        "sampled_nights": sampled_night_count(rows),
        "sampled_stars": len(star_ids),
        "sampled_channel_rows": len(rows),
        "role_row_counts": dict(sorted(role_counts.items())),
        "aperture_selection": aperture_selection,
        "annulus_selection": annulus_selection,
        "final_test_selection": final_selection,
        "adoption_decision": adoption,
        "adopted_geometry": adopted,
        "adopted_aperture_mode": chosen_geometry.mode if adopted != CONTROL_NAME else "scaled",
        "adopted_aperture_value": chosen_geometry.value if adopted != CONTROL_NAME else 2.5,
        "adopted_minimum_px": chosen_geometry.minimum_px if adopted != CONTROL_NAME else 3.0,
        "adopted_maximum_px": chosen_geometry.maximum_px if adopted != CONTROL_NAME else 9.0,
        "adopted_annulus_gap_px": chosen_geometry.annulus_gap_px if adopted != CONTROL_NAME else 3.0,
        "adopted_annulus_width_px": chosen_geometry.annulus_width_px if adopted != CONTROL_NAME else 4.0,
        "adopted_annulus_gap_sigma": chosen_geometry.annulus_gap_sigma if adopted != CONTROL_NAME else 0.0,
        "adopted_annulus_width_sigma": chosen_geometry.annulus_width_sigma if adopted != CONTROL_NAME else 0.0,
        "minimum_required_gain_fraction": 0.02,
        "test_opened_once_after_validation_selection": True,
        "followup_reuses_previously_opened_test_nights":
            reuse_aperture_run is not None,
        "reused_aperture_run": (str(Path(reuse_aperture_run).resolve())
                                if reuse_aperture_run is not None else None),
    }
    (output / "benchmark_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
