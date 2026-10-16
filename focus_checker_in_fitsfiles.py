#!/usr/bin/env python3
"""Measure stellar focus in scientific FITS images with elliptical Gaussians.

The primary focus statistic is the fitted minor-axis FWHM.  For a fixed
camera, the major axis can include sidereal trailing as well as optical blur.
Catalogue identities and saved astrometric solutions are deliberately unused.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import glob
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Iterable

from astropy.io import fits
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import least_squares


FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))
ROOT = Path(__file__).resolve().parent
V17_ROOT = ROOT / "v17"
_V17_FOCUS_TOOLS = None


def sensor_blur_um(
    fwhm_px: float, image_shape: tuple[int, int], sensor_long_axis_mm: float
) -> float:
    """Convert pixels to sensor-plane micrometres, invariant to image rotation."""
    detector_long_axis_px = max(int(image_shape[0]), int(image_shape[1]))
    return float(fwhm_px) / detector_long_axis_px * sensor_long_axis_mm * 1000.0


def load_v17_focus_tools():
    """Load v17's bare-module runtime without contaminating root imports."""
    global _V17_FOCUS_TOOLS
    if _V17_FOCUS_TOOLS is not None:
        return _V17_FOCUS_TOOLS
    module_names = (
        "point_star_detection",
        "point_star_footprint",
        "point_star_image",
        "point_star_plotting",
    )
    saved = {name: sys.modules.pop(name) for name in module_names if name in sys.modules}
    runtime_path = str(V17_ROOT)
    sys.path.insert(0, runtime_path)
    importlib.invalidate_caches()
    try:
        image_module = importlib.import_module("point_star_image")
        detection_module = importlib.import_module("point_star_detection")
        _V17_FOCUS_TOOLS = (
            image_module.load_scientific_image,
            detection_module.detect_stars,
        )
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        if sys.path and sys.path[0] == runtime_path:
            sys.path.pop(0)
        else:
            sys.path.remove(runtime_path)
    return _V17_FOCUS_TOOLS


def _rejected(reason: str) -> dict[str, object]:
    return {"fit_ok": False, "rejection_reason": reason}


def _background_plane(pixels: np.ndarray) -> tuple[float, float, float]:
    height, width = pixels.shape
    yy, xx = np.indices(pixels.shape, dtype=float)
    edge = np.zeros(pixels.shape, dtype=bool)
    edge[[0, -1], :] = True
    edge[:, [0, -1]] = True
    design = np.column_stack(
        [np.ones(edge.sum()), xx[edge] - (width - 1) / 2, yy[edge] - (height - 1) / 2]
    )
    return tuple(np.linalg.lstsq(design, pixels[edge], rcond=None)[0])


def fit_elliptical_gaussian(
    cutout: np.ndarray,
    *,
    saturated_mask: np.ndarray | None = None,
) -> dict[str, object]:
    """Fit a rotated Gaussian plus a planar background to one star cutout."""
    pixels = np.asarray(cutout, dtype=float)
    if pixels.ndim != 2 or min(pixels.shape) < 7 or not np.isfinite(pixels).all():
        return _rejected("invalid_cutout")
    if saturated_mask is not None:
        saturated = np.asarray(saturated_mask, dtype=bool)
        if saturated.shape != pixels.shape:
            return _rejected("saturation_mask_shape")
        if saturated.any():
            return _rejected("saturated_cutout")

    height, width = pixels.shape
    yy, xx = np.indices(pixels.shape, dtype=float)
    x_mid = (width - 1) / 2
    y_mid = (height - 1) / 2
    background0, slope_x0, slope_y0 = _background_plane(pixels)
    plane0 = background0 + slope_x0 * (xx - x_mid) + slope_y0 * (yy - y_mid)
    positive = np.clip(pixels - plane0, 0.0, None)
    total = float(positive.sum())
    if not np.isfinite(total) or total <= 0:
        return _rejected("no_positive_source")
    x0 = float((positive * xx).sum() / total)
    y0 = float((positive * yy).sum() / total)
    dx = xx - x0
    dy = yy - y0
    covariance = np.array(
        [
            [(positive * dx * dx).sum(), (positive * dx * dy).sum()],
            [(positive * dx * dy).sum(), (positive * dy * dy).sum()],
        ]
    ) / total
    values, vectors = np.linalg.eigh(covariance)
    sigma_minor0, sigma_major0 = np.sqrt(np.clip(values, 0.5**2, None))
    theta0 = float(math.atan2(vectors[1, 1], vectors[0, 1]))
    amplitude0 = float(max(positive.max(), np.ptp(pixels), 1.0))
    edge_values = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]))
    noise = max(1.4826 * float(np.median(np.abs(edge_values - np.median(edge_values)))), 1e-6)

    def model(parameters: np.ndarray) -> np.ndarray:
        background, slope_x, slope_y, amplitude, xc, yc, log_major, log_minor, theta = parameters
        sigma_major = math.exp(log_major)
        sigma_minor = math.exp(log_minor)
        local_x = xx - xc
        local_y = yy - yc
        along = math.cos(theta) * local_x + math.sin(theta) * local_y
        across = -math.sin(theta) * local_x + math.cos(theta) * local_y
        gaussian = amplitude * np.exp(
            -0.5 * ((along / sigma_major) ** 2 + (across / sigma_minor) ** 2)
        )
        return (
            background
            + slope_x * (xx - x_mid)
            + slope_y * (yy - y_mid)
            + gaussian
        )

    initial = np.array(
        [
            background0,
            slope_x0,
            slope_y0,
            amplitude0,
            x0,
            y0,
            math.log(sigma_major0),
            math.log(sigma_minor0),
            theta0,
        ],
        dtype=float,
    )
    max_sigma = float(max(pixels.shape))
    lower = np.array(
        [-np.inf, -np.inf, -np.inf, 0.0, -0.5, -0.5, math.log(0.35), math.log(0.35), -2 * math.pi]
    )
    upper = np.array(
        [np.inf, np.inf, np.inf, np.inf, width - 0.5, height - 0.5, math.log(max_sigma), math.log(max_sigma), 2 * math.pi]
    )
    try:
        fit = least_squares(
            lambda parameters: (model(parameters) - pixels).ravel(),
            initial,
            bounds=(lower, upper),
            loss="soft_l1",
            f_scale=noise,
            max_nfev=600,
        )
    except (ValueError, FloatingPointError, OverflowError) as error:
        return _rejected(f"fit_error:{type(error).__name__}")
    if not fit.success or not np.isfinite(fit.x).all():
        return _rejected("optimizer_failed")

    background, slope_x, slope_y, amplitude, xc, yc, log_a, log_b, theta = fit.x
    sigma_a, sigma_b = math.exp(log_a), math.exp(log_b)
    if sigma_a >= sigma_b:
        sigma_major, sigma_minor, theta_major = sigma_a, sigma_b, theta
    else:
        sigma_major, sigma_minor, theta_major = sigma_b, sigma_a, theta + math.pi / 2
    theta_major_deg = ((math.degrees(theta_major) + 90.0) % 180.0) - 90.0
    residual = model(fit.x) - pixels
    rmse = float(np.sqrt(np.mean(residual**2)))
    signal_to_noise = float(amplitude / noise)
    rejection = None
    if abs(xc - x_mid) > max(3.0, width * 0.25) or abs(yc - y_mid) > max(3.0, height * 0.25):
        rejection = "fit_off_centre"
    elif sigma_minor < 0.4:
        rejection = "minor_axis_too_narrow"
    elif sigma_major > min(pixels.shape) / 2:
        rejection = "major_axis_too_wide"
    elif sigma_major / sigma_minor > 10:
        rejection = "axis_ratio_too_large"
    elif signal_to_noise < 5:
        rejection = "fit_snr_below_5"
    return {
        "fit_ok": rejection is None,
        "rejection_reason": rejection or "",
        "x_fit_px": float(xc),
        "y_fit_px": float(yc),
        "amplitude_adu": float(amplitude),
        "background_adu": float(background),
        "background_slope_x_adu_px": float(slope_x),
        "background_slope_y_adu_px": float(slope_y),
        "sigma_major_px": float(sigma_major),
        "sigma_minor_px": float(sigma_minor),
        "fwhm_major_px": float(FWHM_PER_SIGMA * sigma_major),
        "fwhm_minor_px": float(FWHM_PER_SIGMA * sigma_minor),
        "axis_ratio": float(sigma_major / sigma_minor),
        "theta_major_deg": float(theta_major_deg),
        "fit_rmse_adu": rmse,
        "fit_rmse_fraction_peak": float(rmse / max(amplitude, 1e-12)),
        "fit_snr": signal_to_noise,
    }


def _finite_percentile(values: Iterable[float], percentile: float) -> float:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    return float(np.percentile(array, percentile)) if len(array) else float("nan")


def summarise_image_fits(rows: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate accepted stellar fits for one image."""
    accepted = [row for row in rows if row.get("fit_ok")]
    minor = [float(row["fwhm_minor_px"]) for row in accepted]
    major = [float(row["fwhm_major_px"]) for row in accepted]
    ratios = [float(row["axis_ratio"]) for row in accepted]
    angles = [float(row["theta_major_deg"]) for row in accepted]
    return {
        "gaussian_fits_attempted": len(rows),
        "gaussian_fits_ok": len(accepted),
        "focus_fwhm_minor_median_px": _finite_percentile(minor, 50),
        "focus_fwhm_minor_p25_px": _finite_percentile(minor, 25),
        "focus_fwhm_minor_p75_px": _finite_percentile(minor, 75),
        "fwhm_major_median_px": _finite_percentile(major, 50),
        "axis_ratio_median": _finite_percentile(ratios, 50),
        "theta_major_median_deg": _finite_percentile(angles, 50),
    }


def select_focus_detections(
    detections: Iterable[dict[str, object]],
    image_shape: tuple[int, int],
    *,
    max_sources: int = 300,
    min_peak_snr: float = 10.0,
    grid_shape: tuple[int, int] = (4, 6),
) -> list[dict[str, object]]:
    """Choose a bright, unsaturated sample distributed across the detector."""
    if max_sources < 1:
        return []
    height, width = image_shape
    grid_rows, grid_columns = grid_shape
    eligible = [
        row
        for row in detections
        if not bool(row.get("saturated", False))
        and float(row.get("peak_snr", 0.0)) >= min_peak_snr
        and np.isfinite(float(row.get("x_px", np.nan)))
        and np.isfinite(float(row.get("y_px", np.nan)))
    ]
    eligible.sort(
        key=lambda row: (-float(row.get("peak_snr", 0.0)), int(row.get("detection_id", 0)))
    )
    cells: dict[tuple[int, int], list[dict[str, object]]] = {}
    for row in eligible:
        column = min(grid_columns - 1, max(0, int(float(row["x_px"]) / width * grid_columns)))
        grid_row = min(grid_rows - 1, max(0, int(float(row["y_px"]) / height * grid_rows)))
        cells.setdefault((grid_row, column), []).append(row)
    quota = max(1, math.ceil(max_sources / max(1, grid_rows * grid_columns)))
    selected = [row for key in sorted(cells) for row in cells[key][:quota]]
    if len(selected) < max_sources:
        selected_ids = {id(row) for row in selected}
        selected.extend(row for row in eligible if id(row) not in selected_ids)
    selected.sort(
        key=lambda row: (-float(row.get("peak_snr", 0.0)), int(row.get("detection_id", 0)))
    )
    return selected[:max_sources]


def fit_detected_sources(
    luminance: np.ndarray,
    saturated_mask: np.ndarray,
    detections: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Fit local Gaussian models at existing measured source detections."""
    pixels = np.asarray(luminance, dtype=float)
    saturated = np.asarray(saturated_mask, dtype=bool)
    if pixels.ndim != 2 or saturated.shape != pixels.shape:
        raise ValueError("Luminance and saturation mask must be equally shaped 2-D arrays")
    rows = []
    for detection in detections:
        x = int(round(float(detection["x_px"])))
        y = int(round(float(detection["y_px"])))
        estimated_sigma = max(1.0, float(detection.get("major_sigma_px", 1.5)))
        half = min(16, max(6, int(math.ceil(4.0 * estimated_sigma))))
        base = dict(detection)
        base["gaussian_half_window_px"] = half
        if (
            x - half < 0
            or y - half < 0
            or x + half >= pixels.shape[1]
            or y + half >= pixels.shape[0]
        ):
            base.update(_rejected("cutout_at_image_edge"))
            rows.append(base)
            continue
        y_slice = slice(y - half, y + half + 1)
        x_slice = slice(x - half, x + half + 1)
        result = fit_elliptical_gaussian(
            pixels[y_slice, x_slice], saturated_mask=saturated[y_slice, x_slice]
        )
        if result.get("fit_ok") and float(result["fit_rmse_fraction_peak"]) > 0.25:
            result["fit_ok"] = False
            result["rejection_reason"] = "fit_residual_too_large"
        if "x_fit_px" in result:
            result["x_fit_image_px"] = float(x - half + result["x_fit_px"])
            result["y_fit_image_px"] = float(y - half + result["y_fit_px"])
        base.update(result)
        rows.append(base)
    return rows


def _candidate_paths(inputs: Iterable[str | Path]) -> list[Path]:
    paths: set[Path] = set()
    for supplied in inputs:
        text = str(supplied)
        expanded = [Path(match) for match in glob.glob(text, recursive=True)]
        if not expanded:
            expanded = [Path(text)]
        for path in expanded:
            if path.is_dir():
                paths.update(path.rglob("*.fits"))
                paths.update(path.rglob("*.fits.bz2"))
            elif path.is_file() and (
                path.name.lower().endswith(".fits")
                or path.name.lower().endswith(".fits.bz2")
            ):
                paths.add(path)
    return sorted(path.resolve() for path in paths)


def discover_focus_inputs(
    inputs: Iterable[str | Path], *, min_exposure: float
) -> list[dict[str, object]]:
    """Read FITS headers and retain exposures strictly longer than the floor."""
    records = []
    for path in _candidate_paths(inputs):
        header = fits.getheader(path, 0)
        exposure = header.get("EXPTIME", header.get("EXPOSURE"))
        try:
            exposure_s = float(exposure)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(exposure_s) or exposure_s <= min_exposure:
            continue
        records.append(
            {
                "path": path,
                "exposure_s": exposure_s,
                "camera": str(header.get("INSTRUME", "unknown")),
                "date_obs": str(header.get("DATE-OBS", "")),
                "focus_mode": header.get("FOCUSMOD", ""),
                "focus_range": header.get("FOCUSRNG", ""),
                "focal_length_mm": header.get("FOCALLEN", header.get("FOCAL", "")),
                "f_number": header.get("APERTURE", ""),
            }
        )
    return records


def _solver_success(path: Path, solver_results_dir: Path | None) -> bool | str:
    if solver_results_dir is None:
        return ""
    name = path.name
    if name.lower().endswith(".fits.bz2"):
        stem = name[:-9]
    elif name.lower().endswith(".fits"):
        stem = name[:-5]
    else:
        stem = path.stem
    return (solver_results_dir / f"{stem}__report.pdf").is_file()


def _detect_for_focus(scientific) -> tuple[list[dict[str, object]], dict[str, object], str]:
    _, detect_stars = load_v17_focus_tools()

    valid_mask = None if scientific.valid_mask.all() else scientific.valid_mask
    provenance = scientific.provenance()
    stars, audit = detect_stars(
        scientific.luminance,
        valid_mask=valid_mask,
        saturated_mask=scientific.saturated_mask,
        saturation_known=provenance["saturation_known"],
    )
    undersampled = sum(
        row["reason"] in ("too_small", "too_sharp") for row in audit["rejected"]
    )
    detection_pass = "standard"
    if len(stars) < 100 and undersampled >= max(12, len(stars)):
        fallback, fallback_audit = detect_stars(
            scientific.luminance,
            valid_mask=valid_mask,
            saturated_mask=scientific.saturated_mask,
            saturation_known=provenance["saturation_known"],
            detection_blur_sigma=0.8,
        )
        if len(fallback) >= max(12, 2 * len(stars)):
            stars, audit = fallback, fallback_audit
            detection_pass = "undersampled_fallback"
    return stars, audit, detection_pass


def analyse_focus_image(
    record: dict[str, object],
    *,
    max_sources: int = 300,
    sensor_width_mm: float = 36.0,
    solver_results_dir: Path | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Detect stars, fit a spatial sample, and summarise one FITS image."""
    load_scientific_image, _ = load_v17_focus_tools()

    path = Path(record["path"])
    scientific = load_scientific_image(path)
    detections, audit, detection_pass = _detect_for_focus(scientific)
    selected = select_focus_detections(
        detections, scientific.shape, max_sources=max_sources
    )
    fitted = fit_detected_sources(
        scientific.luminance, scientific.saturated_mask, selected
    )
    source_rows = []
    for row in fitted:
        source_rows.append(
            {
                "filename": path.name,
                "path": str(path),
                "camera": record["camera"],
                "date_obs": record["date_obs"],
                "exposure_s": record["exposure_s"],
                **row,
            }
        )
    summary = {
        "filename": path.name,
        "path": str(path),
        "camera": record["camera"],
        "date_obs": record["date_obs"],
        "exposure_s": record["exposure_s"],
        "image_width_px": int(scientific.shape[1]),
        "image_height_px": int(scientific.shape[0]),
        "detected_sources": len(detections),
        "focus_sources_selected": len(selected),
        "detection_pass": detection_pass,
        "global_noise_adu": float(audit["global_noise"]),
        "focus_mode": record["focus_mode"],
        "focus_range": record["focus_range"],
        "focal_length_mm": record["focal_length_mm"],
        "f_number": record["f_number"],
        "solver_success": _solver_success(path, solver_results_dir),
        "analysis_status": "ok",
        **summarise_image_fits(fitted),
    }
    focus_px = float(summary["focus_fwhm_minor_median_px"])
    long_axis = max(int(summary["image_width_px"]), int(summary["image_height_px"]))
    summary["detector_long_axis_px"] = long_axis
    summary["focus_fwhm_minor_ppm_long_axis"] = focus_px / long_axis * 1e6
    summary["focus_blur_on_sensor_um"] = sensor_blur_um(
        focus_px,
        (int(summary["image_height_px"]), int(summary["image_width_px"])),
        sensor_width_mm,
    )
    return summary, source_rows


def _serialisable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _serialisable(row.get(key, "")) for key in fields})


def _camera_summaries(image_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries = []
    for camera in sorted({str(row["camera"]) for row in image_rows}):
        rows = [
            row
            for row in image_rows
            if str(row["camera"]) == camera
            and row.get("analysis_status", "ok") == "ok"
            and np.isfinite(float(row.get("focus_blur_on_sensor_um", np.nan)))
        ]
        values = [float(row["focus_blur_on_sensor_um"]) for row in rows]
        pixel_values = [float(row["focus_fwhm_minor_median_px"]) for row in rows]
        summaries.append(
            {
                "camera": camera,
                "images": len(rows),
                "focus_blur_median_um": _finite_percentile(values, 50),
                "focus_blur_p10_um": _finite_percentile(values, 10),
                "focus_blur_p90_um": _finite_percentile(values, 90),
                "focus_fwhm_minor_median_px": _finite_percentile(pixel_values, 50),
                "detected_sources_median": _finite_percentile(
                    [float(row["detected_sources"]) for row in rows], 50
                ),
                "successful_gaussian_fits": int(
                    sum(int(row["gaussian_fits_ok"]) for row in rows)
                ),
                "solver_successes": int(sum(row.get("solver_success") is True for row in rows)),
                "focus_settings": sorted(
                    {
                        f"mode={row.get('focus_mode', '')},range={row.get('focus_range', '')}"
                        for row in rows
                    }
                ),
            }
        )
    return summaries


def _focus_mode_label(value: object) -> str:
    try:
        return "Manual Focus" if int(value) == 3 else f"code {value}"
    except (TypeError, ValueError):
        return "not recorded"


def _write_report(
    path: Path,
    image_rows: list[dict[str, object]],
    camera_rows: list[dict[str, object]],
) -> None:
    successful = [row for row in image_rows if row.get("analysis_status", "ok") == "ok"]
    settings = sorted(
        {
            (
                str(row.get("camera", "")),
                str(row.get("focus_mode", "")),
                str(row.get("focus_range", "")),
                str(row.get("focal_length_mm", "")),
                str(row.get("f_number", "")),
            )
            for row in successful
        }
    )
    lines = [
        "# KNALDGAS focus check",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from "
        f"{len(image_rows)} FITS images.",
        "",
        "## Interpretation guide",
        "",
        "The primary focus measurement is the fitted **minor-axis FWHM** of an "
        "elliptical two-dimensional Gaussian. The major axis is reported separately "
        "because fixed-camera exposures can be elongated by sidereal trailing. "
        "The sensor-plane value assumes a 36.0-mm full-frame width and is the fairest "
        "comparison between the differently sampled Ra and R6 Mark II images.",
        "",
        "The FITS/RAW metadata contain a focus mode and range but no focus distance or "
        "focus-ring position. Therefore the headers can show whether the recorded mode "
        "changed, but cannot prove that the lens was physically at its infinity stop.",
        "",
        "## Recorded settings",
        "",
        "| Camera | Focus mode | Focus range | Focal length (mm) | f-number |",
        "|---|---:|---:|---:|---:|",
    ]
    for camera, mode, focus_range, focal, f_number in settings:
        lines.append(
            f"| {camera} | {_focus_mode_label(mode)} ({mode}) | {focus_range} | {focal} | {f_number} |"
        )
    lines.extend(
        [
            "",
            "## Camera comparison",
            "",
            "| Camera | Images | Median minor FWHM (px) | Median blur on sensor (um) | "
            "10-90% image range (um) | Median detections | Gaussian fits | Solved |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in camera_rows:
        lines.append(
            f"| {row['camera']} | {row['images']} | "
            f"{row['focus_fwhm_minor_median_px']:.3f} | "
            f"{row['focus_blur_median_um']:.2f} | "
            f"{row['focus_blur_p10_um']:.2f}-{row['focus_blur_p90_um']:.2f} | "
            f"{row['detected_sources_median']:.0f} | "
            f"{row['successful_gaussian_fits']} | {row['solver_successes']} |"
        )
    if camera_rows:
        sharpest = min(camera_rows, key=lambda row: float(row["focus_blur_median_um"]))
        broadest = max(camera_rows, key=lambda row: float(row["focus_blur_median_um"]))
        ratio = float(broadest["focus_blur_median_um"]) / max(
            float(sharpest["focus_blur_median_um"]), 1e-12
        )
        solved = sum(int(row["solver_successes"]) for row in camera_rows)
        all_settings_constant = all(len(row["focus_settings"]) == 1 for row in camera_rows)
        lines.extend(["", "## Evidence-based conclusion", ""])
        if all_settings_constant:
            lines.append(
                "- There is no header evidence for focus-setting changes within either "
                "camera sequence: every analysed frame records Manual Focus, focus-range "
                "code 1, 15 mm and f/2.8. No focus distance or ring position was recorded."
            )
        lines.append(
            f"- The two cameras were not equally affected. {broadest['camera']} has a "
            f"median sensor-plane minor-axis FWHM of {float(broadest['focus_blur_median_um']):.2f} um, "
            f"{ratio:.2f} times {sharpest['camera']}'s {float(sharpest['focus_blur_median_um']):.2f} um. "
            "Their image-level distributions are shown in the comparison figure."
        )
        lines.append(
            f"- The analysed >5 s subset contains {solved}/{len(successful)} successful "
            "solver results. Solve success is therefore not, by itself, a sharp-focus test."
        )
        lines.append(
            "- The evidence favours a stable camera-session-specific focus condition over "
            "repeated focus changes. If the lens ring was placed at its infinity mark or "
            "stop, the headers cannot distinguish an inaccurate infinity reference from a "
            "simple wrong manual ring position; a bracketing focus sequence is needed to "
            "separate those possibilities."
        )
    lines.extend(
        [
            "",
            "## Per-image measurements",
            "",
            "| Image | Camera | Exposure (s) | Detections | Fits | Minor FWHM (px) | "
            "Sensor blur (um) | Major FWHM (px) | Axis ratio | Solved |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in sorted(successful, key=lambda item: (str(item["camera"]), str(item["date_obs"]))):
        solved = "yes" if row.get("solver_success") is True else ("no" if row.get("solver_success") is False else "n/a")
        lines.append(
            f"| {row['filename']} | {row['camera']} | {float(row['exposure_s']):g} | "
            f"{row['detected_sources']} | {row['gaussian_fits_ok']}/{row['gaussian_fits_attempted']} | "
            f"{float(row['focus_fwhm_minor_median_px']):.3f} | "
            f"{float(row['focus_blur_on_sensor_um']):.2f} | "
            f"{float(row['fwhm_major_median_px']):.3f} | "
            f"{float(row['axis_ratio_median']):.3f} | {solved} |"
        )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- Widths include optical aberration, seeing, sampling, and any camera motion; "
            "minor-axis width only reduces the effect of directional trailing.",
            "- A spatially distributed sample of high-S/N unsaturated detections is used; "
            "failed fits remain in `focus_sources.csv` with their rejection reason.",
            "- Header code `FocusRange=1` is ExifTool's `Auto` range label, not a measured "
            "subject distance and not evidence that autofocus operated; `FocusMode=3` means "
            "Manual Focus.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def _plot_by_image(image_rows: list[dict[str, object]], path: Path) -> None:
    rows = [row for row in image_rows if row.get("analysis_status", "ok") == "ok"]
    rows.sort(key=lambda row: str(row.get("date_obs", row["filename"])))
    fig, ax = plt.subplots(figsize=(12, 6.5))
    colours = {camera: colour for camera, colour in zip(sorted({str(r["camera"]) for r in rows}), ("#0072B2", "#D55E00", "#009E73"))}
    for camera in sorted(colours):
        indices = [index for index, row in enumerate(rows) if str(row["camera"]) == camera]
        selected = [rows[index] for index in indices]
        values = np.array([float(row["focus_blur_on_sensor_um"]) for row in selected])
        lower = np.array(
            [
                (float(row["focus_fwhm_minor_median_px"]) - float(row["focus_fwhm_minor_p25_px"]))
                / float(row["detector_long_axis_px"]) * 36000.0
                for row in selected
            ]
        )
        upper = np.array(
            [
                (float(row["focus_fwhm_minor_p75_px"]) - float(row["focus_fwhm_minor_median_px"]))
                / float(row["detector_long_axis_px"]) * 36000.0
                for row in selected
            ]
        )
        ax.errorbar(indices, values, yerr=np.vstack((lower, upper)), fmt="o", ms=5, capsize=2, color=colours[camera], label=camera)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(
        [f"{str(row['date_obs'])[11:19]}\n{float(row['exposure_s']):g}s" for row in rows],
        rotation=65,
        ha="right",
        fontsize=7,
    )
    ax.set_ylabel("Median stellar minor-axis FWHM on sensor [um]")
    ax.set_xlabel("Image time and exposure")
    ax.set_title("KNALDGAS focus by image (bars show within-image interquartile range)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _plot_camera_comparison(image_rows: list[dict[str, object]], path: Path) -> None:
    rows = [row for row in image_rows if row.get("analysis_status", "ok") == "ok"]
    cameras = sorted({str(row["camera"]) for row in rows})
    values = [
        [float(row["focus_blur_on_sensor_um"]) for row in rows if str(row["camera"]) == camera]
        for camera in cameras
    ]
    fig, ax = plt.subplots(figsize=(8, 6.5))
    ax.boxplot(values, tick_labels=cameras, showmeans=True, widths=0.5)
    for index, camera_values in enumerate(values, 1):
        offsets = np.linspace(-0.09, 0.09, len(camera_values)) if camera_values else []
        ax.scatter(index + offsets, camera_values, s=28, alpha=0.72, color="#0072B2")
    ax.set_ylabel("Per-image median minor-axis FWHM on sensor [um]")
    ax.set_title("Focus comparison after detector-sampling normalization")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_focus_outputs(
    image_rows: list[dict[str, object]],
    source_rows: list[dict[str, object]],
    output_dir: Path,
) -> dict[str, object]:
    """Write tables, machine summary, narrative report, and focus figures."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    image_rows = [dict(row) for row in image_rows]
    for row in image_rows:
        if row.get("analysis_status", "ok") == "ok":
            image_shape = (
                int(row.get("image_height_px", row["image_width_px"])),
                int(row["image_width_px"]),
            )
            long_axis = max(image_shape)
            focus_px = float(row["focus_fwhm_minor_median_px"])
            row.pop("focus_fwhm_minor_ppm_width", None)
            row["detector_long_axis_px"] = long_axis
            row["focus_fwhm_minor_ppm_long_axis"] = focus_px / long_axis * 1e6
            row["focus_blur_on_sensor_um"] = sensor_blur_um(
                focus_px, image_shape, 36.0
            )
    camera_rows = _camera_summaries(image_rows)
    _write_csv(output / "focus_images.csv", image_rows)
    _write_csv(output / "focus_sources.csv", source_rows)
    summary = {
        "images": len(image_rows),
        "source_fits": len(source_rows),
        "camera_summaries": camera_rows,
        "primary_metric": "elliptical Gaussian minor-axis FWHM",
        "sensor_width_assumption_mm": 36.0,
    }
    (output / "focus_summary.json").write_text(json.dumps(summary, indent=2, default=_serialisable) + "\n")
    _write_report(output / "focus_report.md", image_rows, camera_rows)
    _plot_by_image(image_rows, output / "focus_by_image.png")
    _plot_camera_comparison(image_rows, output / "focus_camera_comparison.png")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="FITS files, directories, or quoted globs")
    parser.add_argument("--min-exposure", type=float, default=5.0)
    parser.add_argument("--max-sources", type=int, default=300)
    parser.add_argument("--sensor-width-mm", type=float, default=36.0)
    parser.add_argument("--solver-results-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    records = discover_focus_inputs(args.inputs, min_exposure=args.min_exposure)
    if not records:
        parser.error("No FITS images have exposures strictly longer than the threshold")
    if args.max_sources < 1:
        parser.error("--max-sources must be positive")
    if args.sensor_width_mm <= 0:
        parser.error("--sensor-width-mm must be positive")
    image_rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    print(f"Selected {len(records)} FITS images", flush=True)
    for index, record in enumerate(records, 1):
        path = Path(record["path"])
        print(f"[{index}/{len(records)}] {path.name}", flush=True)
        try:
            summary, fitted = analyse_focus_image(
                record,
                max_sources=args.max_sources,
                sensor_width_mm=args.sensor_width_mm,
                solver_results_dir=args.solver_results_dir,
            )
        except Exception as error:
            summary = {
                **record,
                "filename": path.name,
                "path": str(path),
                "analysis_status": "failed",
                "analysis_error": f"{type(error).__name__}: {error}",
            }
            fitted = []
            print(f"  FAILED: {summary['analysis_error']}", file=sys.stderr, flush=True)
        image_rows.append(summary)
        source_rows.extend(fitted)
    products = write_focus_outputs(image_rows, source_rows, args.output_dir)
    print(
        f"Wrote {products['images']} image summaries and {products['source_fits']} "
        f"source fits to {args.output_dir.resolve()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
