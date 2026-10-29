"""Whole-night validation, matched sky baselines, and uncertainty audits."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Mapping, Sequence

import numpy as np

from .fitting import FitConfig, fit_orbit_families
from .geometry import predict_topocentric_unit, tangent_residuals_arcmin
from .ranging import RangingConfig, systematic_range_seeds
from .types import HeliocentricState, Observation, OrbitFitResult, OrbitSolution


@dataclass(frozen=True)
class NightSplit:
    train: tuple[Observation, ...]
    withheld: tuple[Observation, ...]
    train_nights: tuple[str, ...]
    withheld_nights: tuple[str, ...]
    modulus: int


@dataclass(frozen=True)
class BaselineModel:
    kind: str
    reference_jd_tdb: float
    reference_unit: tuple[float, float, float]
    east_rate_rad_per_day: float = 0.0
    north_rate_rad_per_day: float = 0.0


@dataclass(frozen=True)
class PredictionScore:
    run_ids: tuple[str, ...]
    sigmas_arcmin: tuple[float, ...]
    residuals_arcmin: tuple[float, ...]
    median_arcmin: float
    rms_arcmin: float
    p90_arcmin: float
    weighted_chi_square: float


@dataclass(frozen=True)
class CovarianceResult:
    supported: bool
    rank: int
    parameter_count: int
    covariance: np.ndarray | None
    reason: str


@dataclass(frozen=True)
class BootstrapResult:
    seed: int
    requested_replicates: int
    sampled_nights: tuple[tuple[str, ...], ...]
    statuses: tuple[str, ...]
    states: tuple[HeliocentricState, ...]


@dataclass(frozen=True)
class EvaluationResult:
    split: NightSplit
    primary_sigma_scale: float
    primary_fit: OrbitFitResult
    sensitivity: Mapping[float, OrbitFitResult]
    fixed_baseline: BaselineModel
    angular_velocity_baseline: BaselineModel
    scores: Mapping[str, PredictionScore | None]
    covariance: CovarianceResult
    bootstrap: BootstrapResult
    scientific_status: str
    status_reason: str


def split_nights(observations: Sequence[Observation], modulus: int = 5) -> NightSplit:
    if modulus < 2:
        raise ValueError("holdout modulus must be at least two")
    ordered = sorted(observations, key=lambda row: (row.jd_tdb, row.direction.run_id))
    nights = tuple(sorted({row.direction.night for row in ordered}))
    withheld_nights = tuple(night for index, night in enumerate(nights, start=1) if index % modulus == 0)
    withheld_set = set(withheld_nights)
    train_nights = tuple(night for night in nights if night not in withheld_set)
    train = tuple(row for row in ordered if row.direction.night not in withheld_set)
    withheld = tuple(row for row in ordered if row.direction.night in withheld_set)
    if not train or not withheld:
        raise ValueError("whole-night split needs both training and withheld observations")
    return NightSplit(train, withheld, train_nights, withheld_nights, modulus)


def _normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("direction cannot be normalised")
    return vector / norm


def _basis(unit: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pole = np.array([0.0, 0.0, 1.0])
    east = np.cross(pole, unit)
    if np.linalg.norm(east) < 1e-12:
        east = np.cross(np.array([1.0, 0.0, 0.0]), unit)
    east = _normalise(east)
    north = _normalise(np.cross(unit, east))
    return east, north


def fit_fixed_direction(train: Sequence[Observation]) -> BaselineModel:
    if not train:
        raise ValueError("fixed-direction baseline needs training observations")
    weights = np.asarray([1.0 / row.sigma_arcmin**2 for row in train])
    units = np.asarray([row.measured_unit for row in train])
    unit = _normalise(np.sum(weights[:, None] * units, axis=0))
    epoch = float(np.median([row.jd_tdb for row in train]))
    return BaselineModel("fixed_direction", epoch, tuple(float(value) for value in unit))


def fit_angular_velocity(train: Sequence[Observation]) -> BaselineModel:
    if len(train) < 2:
        raise ValueError("angular-velocity baseline needs two observations")
    fixed = fit_fixed_direction(train)
    origin = np.asarray(fixed.reference_unit)
    east, north = _basis(origin)
    units = np.asarray([row.measured_unit for row in train])
    denominator = np.maximum(units @ origin, 1e-12)
    coordinates = np.column_stack([units @ east / denominator, units @ north / denominator])
    delta = np.asarray([row.jd_tdb - fixed.reference_jd_tdb for row in train])
    weights = np.asarray([1.0 / row.sigma_arcmin**2 for row in train])
    design = np.column_stack([np.ones(len(train)), delta])
    weighted_design = design * np.sqrt(weights)[:, None]
    coefficients = np.linalg.lstsq(weighted_design, coordinates * np.sqrt(weights)[:, None], rcond=None)[0]
    reference = _normalise(origin + coefficients[0, 0] * east + coefficients[0, 1] * north)
    reference_east, reference_north = _basis(reference)
    # The basis rotation from the small intercept adjustment is below the model's
    # linear approximation; rates remain in the newly anchored tangent frame.
    return BaselineModel(
        "angular_velocity",
        fixed.reference_jd_tdb,
        tuple(float(value) for value in reference),
        float(coefficients[1, 0]),
        float(coefficients[1, 1]),
    )


def _baseline_predictions(model: BaselineModel, observations: Sequence[Observation]) -> np.ndarray:
    reference = np.asarray(model.reference_unit)
    east, north = _basis(reference)
    result = []
    for row in observations:
        delta = row.jd_tdb - model.reference_jd_tdb
        unit = reference + delta * (
            model.east_rate_rad_per_day * east + model.north_rate_rad_per_day * north
        )
        result.append(_normalise(unit))
    return np.asarray(result)


def score_predictions(
    model: BaselineModel | OrbitSolution | HeliocentricState,
    observations: Sequence[Observation],
) -> PredictionScore:
    if not observations:
        raise ValueError("prediction scoring needs observations")
    if isinstance(model, BaselineModel):
        predicted = _baseline_predictions(model, observations)
    else:
        state = model.state if isinstance(model, OrbitSolution) else model
        predicted = predict_topocentric_unit(state, observations, light_time=True)
    measured = np.asarray([row.measured_unit for row in observations])
    residual_vectors = tangent_residuals_arcmin(measured, predicted)
    norms = np.linalg.norm(residual_vectors, axis=1)
    sigmas = np.asarray([row.sigma_arcmin for row in observations])
    return PredictionScore(
        tuple(row.direction.run_id for row in observations),
        tuple(float(value) for value in sigmas),
        tuple(float(value) for value in norms),
        float(np.median(norms)),
        float(np.sqrt(np.mean(norms**2))),
        float(np.percentile(norms, 90.0)),
        float(np.sum(np.square(residual_vectors / sigmas[:, None]))),
    )


def local_covariance(fit: np.ndarray | OrbitSolution | OrbitFitResult) -> CovarianceResult:
    if isinstance(fit, OrbitFitResult):
        if not fit.solutions:
            return CovarianceResult(False, 0, 6, None, "no_orbit_solution")
        matrix = np.asarray(fit.solutions[0].jacobian, dtype=float)
    elif isinstance(fit, OrbitSolution):
        matrix = np.asarray(fit.jacobian, dtype=float)
    else:
        matrix = np.asarray(fit, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != 6:
        return CovarianceResult(False, 0, 6, None, "missing_six_parameter_jacobian")
    rank = int(np.linalg.matrix_rank(matrix))
    if rank < 6:
        return CovarianceResult(False, rank, 6, None, "rank_deficient_jacobian")
    covariance = np.linalg.inv(matrix.T @ matrix)
    if not np.all(np.isfinite(covariance)):
        return CovarianceResult(False, rank, 6, None, "nonfinite_covariance")
    return CovarianceResult(True, rank, 6, covariance, "")


def bootstrap_nights(
    train: Sequence[Observation],
    fit_config: FitConfig,
    replicates: int,
    seed: int,
) -> BootstrapResult:
    if replicates < 0:
        raise ValueError("bootstrap replicate count cannot be negative")
    grouped: dict[str, list[Observation]] = {}
    for row in train:
        grouped.setdefault(row.direction.night, []).append(row)
    nights = tuple(sorted(grouped))
    if not nights and replicates:
        raise ValueError("bootstrap needs training nights")
    generator = np.random.default_rng(seed)
    samples: list[tuple[str, ...]] = []
    statuses: list[str] = []
    states: list[HeliocentricState] = []
    for _ in range(replicates):
        selected = tuple(str(value) for value in generator.choice(nights, size=len(nights), replace=True))
        samples.append(selected)
        rows = [row for night in selected for row in grouped[night]]
        try:
            seeds = systematic_range_seeds(rows, RangingConfig())
            fitted = fit_orbit_families(rows, seeds, fit_config)
        except (ValueError, RuntimeError, OverflowError, np.linalg.LinAlgError):
            statuses.append("fit_error")
            continue
        if fitted.solutions:
            statuses.append("accepted")
            states.append(fitted.solutions[0].state)
        else:
            statuses.append("unresolved")
    return BootstrapResult(seed, replicates, tuple(samples), tuple(statuses), tuple(states))


def _scaled_observations(rows: Sequence[Observation], scale: float) -> tuple[Observation, ...]:
    return tuple(replace(row, sigma_arcmin=row.sigma_arcmin * scale) for row in rows)


def _fit(rows: Sequence[Observation], config: FitConfig) -> OrbitFitResult:
    seeds = systematic_range_seeds(rows, RangingConfig())
    return fit_orbit_families(rows, seeds, config)


def evaluate_controlled(
    observations: Sequence[Observation],
    fit_config: FitConfig,
    *,
    bootstrap_replicates: int = 100,
    bootstrap_seed: int = 1729,
) -> EvaluationResult:
    split = split_nights(observations)
    primary = _fit(split.train, fit_config)
    sensitivity = {
        scale: _fit(_scaled_observations(split.train, scale), fit_config)
        for scale in (0.5, 2.0)
    }
    fixed = fit_fixed_direction(split.train)
    moving = fit_angular_velocity(split.train)
    fixed_score = score_predictions(fixed, split.withheld)
    moving_score = score_predictions(moving, split.withheld)
    orbit_score = score_predictions(primary.solutions[0], split.withheld) if primary.solutions else None
    covariance = local_covariance(primary)
    bootstrap = bootstrap_nights(split.train, fit_config, bootstrap_replicates, bootstrap_seed)
    uncertainty_supported = covariance.supported or sum(status == "accepted" for status in bootstrap.statuses) >= 2
    if orbit_score is None:
        status = "unresolved"
        reason = "no_admissible_orbit_family"
    elif not uncertainty_supported:
        status = "unresolved"
        reason = "uncertainty_not_supported"
    elif (
        orbit_score.weighted_chi_square < fixed_score.weighted_chi_square
        and orbit_score.weighted_chi_square < moving_score.weighted_chi_square
    ):
        status = "predictive"
        reason = ""
    else:
        status = "not_predictive"
        reason = "held_out_orbit_did_not_beat_both_baselines"
    return EvaluationResult(
        split,
        1.0,
        primary,
        sensitivity,
        fixed,
        moving,
        {"orbit": orbit_score, "fixed_direction": fixed_score, "angular_velocity": moving_score},
        covariance,
        bootstrap,
        status,
        reason,
    )
