"""Fits and statistical model comparison for nested radial cameras."""
from __future__ import annotations

import math
from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares

from point_star_barghini import (
    ARCMIN_PER_RADIAN,
    ASTROMETRIC_LOSS_SCALE_ARCMIN,
    radial_soft_l1_residuals,
    tangent_residuals_arcmin,
)
from radial_model import ExtendedBarghiniCamera


def information_criteria(rss: float, n: int, k: int) -> dict[str, object]:
    """Return Gaussian AIC, finite-sample AICc, and BIC for a coordinate RSS."""
    invalid = {"valid": False, "aic": None, "aicc": None, "bic": None}
    if not math.isfinite(rss) or not math.isfinite(float(n)) or not math.isfinite(float(k)):
        return {**invalid, "reason": "non_finite_input"}
    if rss <= 0.0:
        return {**invalid, "reason": "non_positive_rss"}
    if k < 0:
        return {**invalid, "reason": "invalid_parameter_count"}
    if n <= k + 1:
        return {**invalid, "reason": "insufficient_sample"}
    aic = n * math.log(rss / n) + 2 * k
    return {
        "valid": True,
        "reason": None,
        "aic": float(aic),
        "aicc": float(aic + 2 * k * (k + 1) / (n - k - 1)),
        "bic": float(n * math.log(rss / n) + k * math.log(n)),
    }


def akaike_weights(rows: Sequence[Mapping[str, object]]) -> list[float | None]:
    """Return AICc weights aligned with rows, excluding invalid fits."""
    valid_indices: list[int] = []
    values: list[float] = []
    for index, row in enumerate(rows):
        value = row.get("aicc")
        if row.get("valid") and isinstance(value, (int, float)) and math.isfinite(value):
            valid_indices.append(index)
            values.append(float(value))
    answer: list[float | None] = [None] * len(rows)
    if not values:
        return answer
    minimum = min(values)
    relative = [math.exp(-0.5 * (value - minimum)) for value in values]
    total = sum(relative)
    for index, value in zip(valid_indices, relative, strict=True):
        answer[index] = float(value / total)
    return answer


@dataclass
class FitResult:
    camera: ExtendedBarghiniCamera
    success: bool
    failure_reason: str | None
    robust: bool
    k: int
    n: int
    rss_arcmin2: float
    rms_arcmin: float
    rms_px: float
    nfev: int
    optimizer_message: str
    jacobian_rank: int
    jacobian_condition: float
    minimum_derivative: float | None
    roundtrip_error_px: float | None


def _camera_from_vector(
    template: ExtendedBarghiniCamera, values: np.ndarray
) -> ExtendedBarghiniCamera:
    return ExtendedBarghiniCamera(
        template.shape,
        template.reference_rotation,
        values[:8],
        values[8:],
        template.detector_parity,
    )


def fit_extended_camera(
    camera: ExtendedBarghiniCamera,
    xy: np.ndarray,
    sky: np.ndarray,
    *,
    robust: bool,
    max_nfev: int = 600,
) -> FitResult:
    """Fit baseline plus radial coefficients to fixed star associations."""
    measured = np.asarray(xy, dtype=float)
    reference = np.asarray(sky, dtype=float)
    if measured.ndim != 2 or measured.shape[1] != 2:
        raise ValueError("xy must be an Nx2 array")
    if reference.shape != (len(measured), 3):
        raise ValueError("sky must be an Nx3 array paired with xy")
    q = camera.coefficients.size
    k = 8 + q
    h, w = camera.shape
    scale = camera.scale
    lower = np.r_[
        [-np.pi, -0.5, -0.5, -0.5, -0.5, -2.0, -0.8, 0.01],
        np.full(q, -2.0),
    ]
    upper = np.r_[
        [np.pi, w / scale + 0.5, h / scale + 0.5, w / scale + 0.5,
         h / scale + 0.5, 3.0, 0.8, 5.0],
        np.full(q, 2.0),
    ]
    start = np.r_[camera.p, camera.coefficients]

    def residual(values: np.ndarray) -> np.ndarray:
        candidate = _camera_from_vector(camera, values)
        angular = tangent_residuals_arcmin(candidate.to_sky(measured), reference)
        objective = (
            radial_soft_l1_residuals(angular, ASTROMETRIC_LOSS_SCALE_ARCMIN)
            if robust
            else angular
        )
        _, derivative = candidate.radial_derivative_grid()
        scaled = derivative * scale
        penalty = np.maximum(1.0e-9 - scaled, 0.0) * ARCMIN_PER_RADIAN * 1.0e3
        penalty[~np.isfinite(penalty)] = ARCMIN_PER_RADIAN * 1.0e9
        return np.r_[objective.ravel(), penalty]

    optimum = least_squares(
        residual,
        start,
        bounds=(lower, upper),
        loss="linear",
        x_scale="jac",
        max_nfev=max_nfev,
        ftol=1.0e-11,
        xtol=1.0e-11,
        gtol=1.0e-11,
    )
    fitted = _camera_from_vector(camera, optimum.x)
    angular = tangent_residuals_arcmin(fitted.to_sky(measured), reference)
    rss = float(np.sum(angular**2))
    rms_arcmin = float(np.sqrt(rss / len(measured))) if len(measured) else float("nan")
    active_radius = float(
        np.max(
            np.linalg.norm(
                measured - [fitted.physical.x_o, fitted.physical.y_o], axis=1
            )
        )
    ) if len(measured) else 0.0
    validation = fitted.is_valid(radius_limit_px=active_radius)

    raw_jacobian = np.asarray(optimum.jac[: 2 * len(measured), :], dtype=float)
    singular = np.linalg.svd(raw_jacobian, compute_uv=False) if raw_jacobian.size else np.array([])
    if singular.size and singular[0] > 0.0:
        tolerance = max(raw_jacobian.shape) * np.finfo(float).eps * singular[0]
        rank = int(np.sum(singular > tolerance))
        condition = float(singular[0] / singular[-1]) if singular[-1] > 0.0 else float("inf")
    else:
        rank = 0
        condition = float("inf")

    rms_px = float("nan")
    roundtrip_error = None
    if validation:
        try:
            predicted = fitted.project(reference)
            rms_px = float(np.sqrt(np.mean(np.sum((predicted - measured) ** 2, axis=1))))
            restored = fitted.project(fitted.to_sky(measured))
            roundtrip_error = float(np.max(np.linalg.norm(restored - measured, axis=1)))
        except ValueError:
            validation = type(validation)(
                False,
                "inverse_domain",
                validation.minimum_derivative,
                validation.endpoint_angle_rad,
            )

    failure_reason = None
    if not optimum.success:
        failure_reason = "optimizer_failed"
    elif not validation:
        failure_reason = validation.reason
    elif rank < k:
        failure_reason = "rank_deficient"
    success = failure_reason is None
    return FitResult(
        camera=fitted,
        success=success,
        failure_reason=failure_reason,
        robust=bool(robust),
        k=k,
        n=2 * len(measured),
        rss_arcmin2=rss,
        rms_arcmin=rms_arcmin,
        rms_px=rms_px,
        nfev=int(optimum.nfev),
        optimizer_message=str(optimum.message),
        jacobian_rank=rank,
        jacobian_condition=condition,
        minimum_derivative=validation.minimum_derivative,
        roundtrip_error_px=roundtrip_error,
    )


def spatial_folds(
    xy: np.ndarray,
    centre: np.ndarray | Sequence[float],
    fold_count: int = 8,
) -> np.ndarray:
    """Assign deterministic contiguous radial/azimuth holdout blocks.

    Even fold counts use two radial bands and ``fold_count / 2`` contiguous
    angular blocks per band.  Odd fold counts use one radial band.  Thus a
    held-out region is never deliberately surrounded by adjacent training
    stars at the same radius and azimuth.
    """
    points = np.asarray(xy, dtype=float)
    origin = np.asarray(centre, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or origin.shape != (2,):
        raise ValueError("spatial folds require Nx2 points and one 2-D centre")
    if fold_count < 2:
        raise ValueError("fold_count must be at least two")
    offset = points - origin
    radius = np.linalg.norm(offset, axis=1)
    angle = np.mod(np.arctan2(offset[:, 1], offset[:, 0]), 2.0 * np.pi)
    answer = np.empty(len(points), dtype=int)
    radial_band_count = 2 if fold_count % 2 == 0 else 1
    angular_block_count = fold_count // radial_band_count
    radial_order = np.lexsort((np.arange(len(points)), radius))
    for radial_band, band_indices in enumerate(
        np.array_split(radial_order, radial_band_count)
    ):
        angular_order = band_indices[
            np.lexsort((band_indices, angle[band_indices]))
        ]
        for angular_block, block_indices in enumerate(
            np.array_split(angular_order, angular_block_count)
        ):
            answer[block_indices] = radial_band * angular_block_count + angular_block
    return answer


def classify_order(
    *,
    fit_valid: bool,
    delta_aicc: float | None,
    delta_bic: float | None,
    validation_delta_rms_arcmin: float | None,
    validation_ci_high: float | None,
) -> str:
    """Classify one extension using penalised fit and blocked prediction."""
    values = (delta_aicc, delta_bic, validation_delta_rms_arcmin, validation_ci_high)
    if not fit_valid or any(value is None or not math.isfinite(value) for value in values):
        return "failed"
    if validation_delta_rms_arcmin > 0.0:
        return "worse_prediction"
    criteria_support = delta_aicc <= -10.0 and delta_bic < 0.0
    if criteria_support and validation_delta_rms_arcmin < 0.0 and validation_ci_high < 0.0:
        return "supported"
    if criteria_support:
        return "in_sample_only"
    return "unsupported"


def select_supported_order(rows: Sequence[Mapping[str, object]]) -> int | None:
    """Choose the smallest supported order within two AICc units of the best."""
    supported = [
        row
        for row in rows
        if row.get("classification") == "supported"
        and isinstance(row.get("aicc"), (int, float))
        and math.isfinite(float(row["aicc"]))
    ]
    if not supported:
        return None
    minimum = min(float(row["aicc"]) for row in supported)
    competitive = [row for row in supported if float(row["aicc"]) <= minimum + 2.0]
    return min(int(row["order"]) for row in competitive)


def _camera_for_order(
    initial: ExtendedBarghiniCamera,
    order: int,
    warm: ExtendedBarghiniCamera | None = None,
) -> ExtendedBarghiniCamera:
    source = warm if warm is not None else initial
    coefficients = np.zeros(order, dtype=float)
    copied = min(order, source.coefficients.size)
    if copied:
        coefficients[:copied] = source.coefficients[:copied]
    return ExtendedBarghiniCamera(
        initial.shape,
        initial.reference_rotation,
        source.p.copy(),
        coefficients,
        initial.detector_parity,
    )


def _fit_row(order: int, result: FitResult) -> dict[str, object]:
    information_parameter_count = result.k + 1  # fitted Gaussian variance
    row: dict[str, object] = {
        "order": order,
        "fit_valid": result.success,
        "failure_reason": result.failure_reason,
        "k": information_parameter_count,
        "camera_parameter_count": result.k,
        "information_parameter_count": information_parameter_count,
        "n": result.n,
        "rss_arcmin2": result.rss_arcmin2,
        "rms_arcmin": result.rms_arcmin,
        "rms_px": result.rms_px,
        "nfev": result.nfev,
        "jacobian_rank": result.jacobian_rank,
        "jacobian_condition": result.jacobian_condition,
        "minimum_derivative": result.minimum_derivative,
        "roundtrip_error_px": result.roundtrip_error_px,
    }
    criteria = information_criteria(
        result.rss_arcmin2, result.n, information_parameter_count
    )
    if result.success:
        row.update(criteria)
    else:
        row.update(
            valid=False,
            reason=result.failure_reason,
            aic=None,
            aicc=None,
            bic=None,
        )
    return row


def _paired_fold_interval(
    baseline: Sequence[Mapping[str, object]],
    extension: Sequence[Mapping[str, object]],
    *,
    seed: int,
    replicates: int,
) -> tuple[float | None, float | None]:
    if len(baseline) != len(extension) or not baseline:
        return None, None
    base_rss = np.asarray([row["holdout_rss_arcmin2"] for row in baseline], dtype=float)
    ext_rss = np.asarray([row["holdout_rss_arcmin2"] for row in extension], dtype=float)
    counts = np.asarray([int(row["holdout_count"]) for row in baseline], dtype=float)
    if not (
        np.all(np.isfinite(base_rss))
        and np.all(np.isfinite(ext_rss))
        and np.all(counts > 0.0)
    ):
        return None, None
    rng = np.random.default_rng(seed)
    sample = rng.integers(0, len(baseline), size=(replicates, len(baseline)))
    denominator = np.sum(counts[sample], axis=1)
    base_rms = np.sqrt(np.sum(base_rss[sample], axis=1) / denominator)
    ext_rms = np.sqrt(np.sum(ext_rss[sample], axis=1) / denominator)
    low, high = np.quantile(ext_rms - base_rms, [0.025, 0.975])
    return float(low), float(high)


def cross_validate_orders(
    initial: ExtendedBarghiniCamera,
    xy: np.ndarray,
    sky: np.ndarray,
    *,
    orders: Sequence[int] = tuple(range(6)),
    fold_count: int = 8,
    bootstrap_replicates: int = 10_000,
    seed: int = 0,
    max_nfev: int = 600,
    include_indices: bool = False,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Fit all data and spatial folds without reassociation or clipping."""
    measured = np.asarray(xy, dtype=float)
    reference = np.asarray(sky, dtype=float)
    order_values = sorted(set(int(order) for order in orders))
    if not order_values or order_values[0] != 0 or any(order < 0 or order > 5 for order in order_values):
        raise ValueError("orders must include zero and lie between zero and five")
    assignments = spatial_folds(
        measured, [initial.physical.x_o, initial.physical.y_o], fold_count
    )

    model_rows: list[dict[str, object]] = []
    warm: ExtendedBarghiniCamera | None = None
    for order in order_values:
        candidate = _camera_for_order(initial, order, warm)
        result = fit_extended_camera(
            candidate, measured, reference, robust=False, max_nfev=max_nfev
        )
        model_rows.append(_fit_row(order, result))
        if result.success:
            warm = result.camera

    fold_rows: list[dict[str, object]] = []
    baseline_full_valid = bool(model_rows[0]["fit_valid"])
    full_valid_by_order = {
        int(row["order"]): bool(row["fit_valid"]) for row in model_rows
    }
    baseline_aicc = model_rows[0].get("aicc")
    baseline_bic = model_rows[0].get("bic")
    criteria_supported_by_order: dict[int, bool] = {0: baseline_full_valid}
    for row in model_rows[1:]:
        order = int(row["order"])
        aicc = row.get("aicc")
        bic = row.get("bic")
        criteria_supported_by_order[order] = bool(
            full_valid_by_order[order]
            and isinstance(aicc, (int, float))
            and isinstance(bic, (int, float))
            and isinstance(baseline_aicc, (int, float))
            and isinstance(baseline_bic, (int, float))
            and math.isfinite(float(aicc))
            and math.isfinite(float(bic))
            and math.isfinite(float(baseline_aicc))
            and math.isfinite(float(baseline_bic))
            and float(aicc) - float(baseline_aicc) <= -10.0
            and float(bic) - float(baseline_bic) < 0.0
        )
    for fold in range(fold_count):
        holdout = np.flatnonzero(assignments == fold)
        training = np.flatnonzero(assignments != fold)
        fold_warm: ExtendedBarghiniCamera | None = None
        for order in order_values:
            skipped_reason = None
            if not baseline_full_valid:
                skipped_reason = "baseline_full_fit_invalid"
            elif not full_valid_by_order[order]:
                skipped_reason = "full_data_fit_invalid"
            elif order != 0 and not criteria_supported_by_order[order]:
                skipped_reason = "penalised_criteria_not_supported"
            if skipped_reason is not None:
                fold_row = {
                    "order": order,
                    "fold": fold,
                    "fit_valid": False,
                    "failure_reason": skipped_reason,
                    "training_count": len(training),
                    "holdout_count": len(holdout),
                    "training_index_sha256": hashlib.sha256(training.tobytes()).hexdigest(),
                    "holdout_index_sha256": hashlib.sha256(holdout.tobytes()).hexdigest(),
                    "holdout_rss_arcmin2": float("nan"),
                    "holdout_rms_arcmin": float("nan"),
                }
                if include_indices:
                    fold_row["training_indices"] = training.tolist()
                    fold_row["holdout_indices"] = holdout.tolist()
                fold_rows.append(fold_row)
                continue
            candidate = _camera_for_order(initial, order, fold_warm)
            result = fit_extended_camera(
                candidate,
                measured[training],
                reference[training],
                robust=False,
                max_nfev=max_nfev,
            )
            holdout_rss = float("nan")
            holdout_rms = float("nan")
            if result.success and holdout.size:
                residual = tangent_residuals_arcmin(
                    result.camera.to_sky(measured[holdout]), reference[holdout]
                )
                holdout_rss = float(np.sum(residual**2))
                holdout_rms = float(np.sqrt(holdout_rss / len(holdout)))
                fold_warm = result.camera
            fold_row: dict[str, object] = {
                    "order": order,
                    "fold": fold,
                    "fit_valid": result.success,
                    "failure_reason": result.failure_reason,
                    "training_count": len(training),
                    "holdout_count": len(holdout),
                    "training_index_sha256": hashlib.sha256(training.tobytes()).hexdigest(),
                    "holdout_index_sha256": hashlib.sha256(holdout.tobytes()).hexdigest(),
                    "holdout_rss_arcmin2": holdout_rss,
                    "holdout_rms_arcmin": holdout_rms,
                }
            if include_indices:
                fold_row["training_indices"] = training.tolist()
                fold_row["holdout_indices"] = holdout.tolist()
            fold_rows.append(fold_row)

    by_order_folds = {
        order: [row for row in fold_rows if row["order"] == order]
        for order in order_values
    }
    baseline_row = model_rows[0]
    baseline_folds = by_order_folds[0]
    for row in model_rows:
        order = int(row["order"])
        folds = by_order_folds[order]
        valid_cv = all(fold["fit_valid"] for fold in folds) and all(
            math.isfinite(float(fold["holdout_rss_arcmin2"])) for fold in folds
        )
        total_count = sum(int(fold["holdout_count"]) for fold in folds)
        validation_rms = (
            math.sqrt(
                sum(float(fold["holdout_rss_arcmin2"]) for fold in folds)
                / total_count
            )
            if valid_cv and total_count
            else None
        )
        row["validation_rms_arcmin"] = validation_rms
        row["delta_aicc"] = (
            float(row["aicc"]) - float(baseline_row["aicc"])
            if row["aicc"] is not None and baseline_row["aicc"] is not None
            else None
        )
        row["delta_bic"] = (
            float(row["bic"]) - float(baseline_row["bic"])
            if row["bic"] is not None and baseline_row["bic"] is not None
            else None
        )
        baseline_validation = None
        if all(fold["fit_valid"] for fold in baseline_folds):
            base_count = sum(int(fold["holdout_count"]) for fold in baseline_folds)
            baseline_validation = math.sqrt(
                sum(float(fold["holdout_rss_arcmin2"]) for fold in baseline_folds)
                / base_count
            )
        row["validation_delta_rms_arcmin"] = (
            validation_rms - baseline_validation
            if validation_rms is not None and baseline_validation is not None
            else None
        )
        ci_low, ci_high = _paired_fold_interval(
            baseline_folds,
            folds,
            seed=seed + order,
            replicates=bootstrap_replicates,
        )
        row["validation_delta_ci_low"] = ci_low
        row["validation_delta_ci_high"] = ci_high
        if order == 0:
            row["classification"] = "baseline"
        elif bool(row["fit_valid"]) and not criteria_supported_by_order[order]:
            row["classification"] = "unsupported"
        else:
            row["classification"] = classify_order(
                fit_valid=bool(row["fit_valid"] and valid_cv),
                delta_aicc=row["delta_aicc"],
                delta_bic=row["delta_bic"],
                validation_delta_rms_arcmin=row["validation_delta_rms_arcmin"],
                validation_ci_high=ci_high,
            )
    for row, weight in zip(model_rows, akaike_weights(model_rows), strict=True):
        row["akaike_weight"] = weight
    return model_rows, fold_rows
