"""Apply only a confirmed stellar-trained v22 correction to planet rows."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np

from v22.mmto_differential_data import PlanetMeasurement
from v22.mmto_differential_features import FeatureTable
from v22.mmto_differential_models import ConfirmedModel


STATUSES = (
    "corrected",
    "insufficient_local_stars",
    "out_of_domain",
    "invalid_measurement",
    "model_unavailable",
)


@dataclass(frozen=True, slots=True)
class CorrectedPlanetMeasurement:
    run_id: str
    source_sha256: str
    observed_utc: str
    night: str
    identity_type: str
    identity_name: str
    identity_status: str
    candidate_rank: int | None
    detection_id: str
    channel: str
    raw_machine_magnitude: float | None
    v21_control_magnitude: float | None
    v22_relative_magnitude: float | None
    predicted_nuisance_magnitude: float | None
    correction_status: str
    correction_reason: str
    distance_normalized_magnitude: float | None
    distance_status: str
    x_px: float | None
    y_px: float | None
    comparison_count: int


def _airmass(row: PlanetMeasurement) -> float | None:
    if row.x_px is None or row.y_px is None:
        return None
    dx = row.x_px - row.image_width_px / 2.0
    dy = row.y_px - row.image_height_px / 2.0
    radius = math.hypot(dx, dy) / max(min(row.image_width_px, row.image_height_px) / 2.0, 1.0)
    zenith_distance = 90.0 * min(max(radius, 0.0), 1.0)
    altitude = 90.0 - zenith_distance
    denominator = math.cos(math.radians(zenith_distance)) + 0.50572 * (
        96.07995 - zenith_distance
    ) ** -1.6364
    return 1.0 / denominator if altitude >= 0.0 and denominator > 0.0 else None


def _v21_control(row: PlanetMeasurement, context: FeatureTable) -> float | None:
    if row.machine_magnitude is None:
        return None
    run = next(
        (item for item in context.data.runs if item.run_id == row.run_id), None
    )
    if run is None:
        return None
    coefficient = context.control.extinction_coefficients.get(
        (row.night, row.channel, run.catalogue_sha256)
    )
    airmass = _airmass(row)
    if coefficient is None or airmass is None:
        return None
    return row.machine_magnitude - coefficient * airmass


def _context_values(
    row: PlanetMeasurement, context: FeatureTable
) -> tuple[dict[str, float], dict[int, tuple[float, float, int]], tuple[float, float, int]]:
    comparisons = [
        item
        for item in context.comparison_residuals
        if item.source_sha256 == row.source_sha256 and item.channel == row.channel
    ]
    values = np.asarray([item.residual_magnitude for item in comparisons], dtype=float)
    exposure = (
        float(np.median(values)) if len(values) else math.nan,
        float(np.median(np.abs(values - np.median(values)))) if len(values) else math.nan,
        len(values),
    )
    local = {}
    for radius in (128, 256, 512):
        selected = [
            item.residual_magnitude
            for item in comparisons
            if row.x_px is not None
            and row.y_px is not None
            and math.hypot(item.x_px - row.x_px, item.y_px - row.y_px) <= radius
        ]
        array = np.asarray(selected, dtype=float)
        local[radius] = (
            float(np.median(array)) if len(array) else math.nan,
            float(np.median(np.abs(array - np.median(array)))) if len(array) else math.nan,
            len(array),
        )

    x = (
        (row.x_px - row.image_width_px / 2.0) / max(row.image_width_px / 2.0, 1.0)
        if row.x_px is not None
        else math.nan
    )
    y = (
        (row.y_px - row.image_height_px / 2.0) / max(row.image_height_px / 2.0, 1.0)
        if row.y_px is not None
        else math.nan
    )
    angle = math.atan2(y, x) if math.isfinite(x) and math.isfinite(y) else math.nan

    def optional(name: str, value: float | None) -> None:
        features[name] = float(value) if value is not None else math.nan
        missing_name = name.removesuffix("_px").removesuffix("_adu") + "_missing"
        features[missing_name] = 0.0 if value is not None else 1.0

    features: dict[str, float] = {
        "x_normalized": x,
        "y_normalized": y,
        "radius_normalized": math.hypot(x, y) if math.isfinite(x) and math.isfinite(y) else math.nan,
        "azimuth_sin": math.sin(angle) if math.isfinite(angle) else math.nan,
        "azimuth_cos": math.cos(angle) if math.isfinite(angle) else math.nan,
        "blind_airmass": _airmass(row) or math.nan,
        "exposure_median_magnitude": exposure[0],
        "exposure_mad_magnitude": exposure[1],
        "exposure_count": float(exposure[2]),
    }
    optional("major_sigma_px", row.major_sigma_px)
    optional("area_px", row.area_px)
    optional("axis_ratio", row.axis_ratio)
    optional("peak_snr", row.peak_snr)
    optional("aperture_radius_px", row.aperture_radius_px)
    optional("exposure_seconds", row.exposure_seconds)
    optional("global_noise_adu", row.global_noise_adu)
    optional("aperture_background_adu", row.aperture_background_adu)
    # Match the exact historical feature names used by the stellar table.
    features["major_sigma_missing"] = features.pop("major_sigma_missing", features.get("major_sigma_missing", 0.0))
    features["area_missing"] = features.pop("area_missing", features.get("area_missing", 0.0))
    features["axis_ratio_missing"] = features.pop("axis_ratio_missing", features.get("axis_ratio_missing", 0.0))
    features["peak_snr_missing"] = features.pop("peak_snr_missing", features.get("peak_snr_missing", 0.0))
    features["aperture_radius_missing"] = features.pop("aperture_radius_missing", features.get("aperture_radius_missing", 0.0))
    features["exposure_missing"] = features.pop("exposure_seconds_missing", 0.0)
    features["global_noise_missing"] = features.pop("global_noise_missing", features.get("global_noise_missing", 0.0))
    features["aperture_background_missing"] = features.pop("aperture_background_missing", features.get("aperture_background_missing", 0.0))
    for radius in (128, 256, 512):
        median, mad, count = local[radius]
        features[f"local_median_{radius}_px"] = median
        features[f"local_mad_{radius}_px"] = mad
        features[f"local_count_{radius}_px"] = float(count)
    return features, local, exposure


def _predict(
    model: ConfirmedModel,
    row: PlanetMeasurement,
    context: FeatureTable,
) -> tuple[float | None, str, int]:
    features, local, exposure = _context_values(row, context)
    minimum_local = int(context.config.get("minimum_local_comparisons", 12))
    minimum_exposure = int(context.config.get("minimum_exposure_comparisons", 30))
    supported_count = max(item[2] for item in local.values())
    if supported_count < minimum_local and exposure[2] < minimum_exposure:
        return None, "insufficient_local_stars", supported_count
    fitted = model.fitted_pipeline
    if fitted.name == "local_ensemble":
        for radius in (128, 256, 512):
            median, _, count = local[radius]
            if count >= minimum_local and math.isfinite(median):
                return median, "corrected", count
        if exposure[2] >= minimum_exposure and math.isfinite(exposure[0]):
            return exposure[0], "corrected", exposure[2]
        return None, "insufficient_local_stars", supported_count
    if row.channel not in fitted.estimators:
        return None, "model_unavailable", supported_count
    vector = np.asarray(
        [features.get(name, math.nan) for name in fitted.feature_names], dtype=float
    ).reshape(1, -1)
    median = fitted.support_medians[row.channel]
    support_vector = np.where(np.isfinite(vector), vector, median)
    if fitted.support[row.channel].status(support_vector)[0] != "supported":
        return None, "out_of_domain", supported_count
    prediction = float(fitted.estimators[row.channel].predict(vector)[0])
    return prediction, "corrected", supported_count


def apply_to_planets(
    model: ConfirmedModel | None,
    planets: Sequence[PlanetMeasurement],
    context: FeatureTable,
) -> tuple[CorrectedPlanetMeasurement, ...]:
    output = []
    for row in planets:
        raw = row.machine_magnitude
        v21 = _v21_control(row, context)
        if not row.valid_measurement or raw is None:
            prediction, status, count = None, "invalid_measurement", 0
            reason = ";".join(row.exclusion_reasons) or "invalid_measurement"
        elif model is None:
            prediction, status, count = None, "model_unavailable", 0
            reason = "no_candidate_passed_validation_and_final_test"
        else:
            prediction, status, count = _predict(model, row, context)
            reason = "" if status == "corrected" else status
        corrected = (
            raw - prediction
            if raw is not None and prediction is not None and status == "corrected"
            else None
        )
        output.append(
            CorrectedPlanetMeasurement(
                run_id=row.run_id,
                source_sha256=row.source_sha256,
                observed_utc=row.observed_utc,
                night=row.night,
                identity_type=row.identity_type,
                identity_name=row.identity_name,
                identity_status=row.identity_status,
                candidate_rank=row.candidate_rank,
                detection_id=row.detection_id,
                channel=row.channel,
                raw_machine_magnitude=raw,
                v21_control_magnitude=v21,
                v22_relative_magnitude=corrected,
                predicted_nuisance_magnitude=prediction,
                correction_status=status,
                correction_reason=reason,
                distance_normalized_magnitude=None,
                distance_status="distance_unavailable",
                x_px=row.x_px,
                y_px=row.y_px,
                comparison_count=count,
            )
        )
    output.sort(
        key=lambda item: (
            item.identity_type,
            item.identity_name,
            item.channel,
            item.observed_utc,
            item.detection_id,
            item.candidate_rank if item.candidate_rank is not None else -1,
        )
    )
    return tuple(output)
