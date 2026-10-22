"""Apply only a confirmed stellar-trained v23 correction to planet rows."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from v23.barghini_model import BarghiniParameters, detector_to_horizontal
from v23.mmto_differential_data import PlanetMeasurement
from v23.mmto_differential_features import (
    FeatureTable,
    _make_exposure_index,
    context_at_position,
    deployable_feature_mapping,
)
from v23.mmto_differential_models import ConfirmedModel
from v23.point_star_refraction import IntegratedRefraction, remove_refraction


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
    v23_relative_magnitude: float | None
    predicted_nuisance_magnitude: float | None
    correction_status: str
    correction_reason: str
    distance_normalized_magnitude: float | None
    distance_status: str
    x_px: float | None
    y_px: float | None
    comparison_count: int


def _load_blind_geometry(analysis_path: str):
    analysis = Path(analysis_path)
    try:
        result = json.loads((analysis / "result.json").read_text(encoding="utf-8"))
        zenith = json.loads(
            (analysis / "photometric_zenith.json").read_text(encoding="utf-8")
        ).get("zenith_unit_vector")
        camera = result["camera"]
        if zenith is None:
            return None
        zenith_vector = np.asarray(zenith, dtype=float)
        zenith_norm = float(np.linalg.norm(zenith_vector))
        if zenith_vector.shape != (3,) or not np.isfinite(zenith_vector).all() or zenith_norm <= 0.0:
            return None
        shape = np.asarray(camera["shape"], dtype=float)
        scale = float(np.linalg.norm(shape) / 2.0)
        p = np.asarray(camera["normalised_parameters"], dtype=float)
        parameters = BarghiniParameters(
            p[0], *(p[1:5] * scale).tolist(), math.exp(p[5]) / scale,
            p[6], p[7] / scale,
        )
        parity = -1.0 if camera.get("detector_parity") == "mirrored" else 1.0
        return (
            parameters,
            parity,
            np.asarray(camera["reference_rotation"], dtype=float),
            IntegratedRefraction.from_dict(camera.get("integrated_refraction")),
            zenith_vector / zenith_norm,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _airmass(row: PlanetMeasurement, geometry) -> float | None:
    if row.x_px is None or row.y_px is None or geometry is None:
        return None
    parameters, parity, rotation, refraction, zenith = geometry
    azimuth, zenith_distance = detector_to_horizontal(
        np.asarray([row.x_px]), np.asarray([row.y_px]), parameters
    )
    ray = np.column_stack(
        (
            np.sin(zenith_distance) * np.cos(azimuth),
            parity * np.sin(zenith_distance) * np.sin(azimuth),
            np.cos(zenith_distance),
        )
    )
    if not refraction.is_zero:
        ray = remove_refraction(
            ray,
            refraction.zenith_camera,
            refraction.refraction_a_arcsec,
            refraction.refraction_b_arcsec,
        )
    sky = ray @ rotation.T
    sine_altitude = float(np.clip(sky[0] @ zenith, -1.0, 1.0))
    altitude = math.degrees(math.asin(sine_altitude))
    zenith_distance_deg = 90.0 - altitude
    if altitude < 0.0:
        return None
    denominator = math.cos(math.radians(zenith_distance_deg)) + 0.50572 * (
        96.07995 - zenith_distance_deg
    ) ** -1.6364
    return 1.0 / denominator if denominator > 0.0 else None


def _v21_control(
    row: PlanetMeasurement, context: FeatureTable, airmass: float | None
) -> float | None:
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
    if coefficient is None or airmass is None:
        return None
    return row.machine_magnitude - coefficient * airmass


def _context_values(
    row: PlanetMeasurement, context: FeatureTable, airmass: float | None
) -> tuple[dict[str, float], dict[int, tuple[float, float, int]], tuple[float, float, int]]:
    comparisons = [
        item
        for item in context.comparison_residuals
        if item.source_sha256 == row.source_sha256 and item.channel == row.channel
    ]
    minimum_local = int(context.config.get("minimum_local_comparisons", 12))
    minimum_exposure = int(context.config.get("minimum_exposure_comparisons", 30))
    if row.x_px is None or row.y_px is None:
        exposure = (math.nan, math.nan, 0)
        local = {radius: (math.nan, math.nan, 0) for radius in (128, 256, 512)}
    else:
        exposure_median, exposure_mad, exposure_count, local = context_at_position(
            row.x_px,
            row.y_px,
            _make_exposure_index(comparisons),
            radii=(128, 256, 512),
            minimum_local=minimum_local,
            minimum_exposure=minimum_exposure,
        )
        exposure = (exposure_median, exposure_mad, exposure_count)
    features = deployable_feature_mapping(
        row,
        exposure,
        local,
        airmass=airmass,
        radii=(128, 256, 512),
        has_background="aperture_background_adu" in context.deployable_feature_names,
    )
    return features, local, exposure


def _predict(
    model: ConfirmedModel,
    row: PlanetMeasurement,
    context: FeatureTable,
    airmass: float | None,
) -> tuple[float | None, str, int]:
    features, local, exposure = _context_values(row, context, airmass)
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
    runs = {run.run_id: run for run in context.data.runs}
    geometries = {
        run_id: _load_blind_geometry(run.analysis_path)
        for run_id, run in runs.items()
    }
    for row in planets:
        raw = row.machine_magnitude
        airmass = _airmass(row, geometries.get(row.run_id))
        v21 = _v21_control(row, context, airmass)
        if not row.valid_measurement or raw is None:
            prediction, status, count = None, "invalid_measurement", 0
            reason = ";".join(row.exclusion_reasons) or "invalid_measurement"
        elif model is None:
            prediction, status, count = None, "model_unavailable", 0
            reason = "no_candidate_passed_validation_and_final_test"
        else:
            prediction, status, count = _predict(model, row, context, airmass)
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
                v23_relative_magnitude=corrected,
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
