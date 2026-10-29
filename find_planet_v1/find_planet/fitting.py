"""Robust differential correction and preservation of distinct orbit families."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np
from scipy.optimize import least_squares

from .dynamics import state_to_elements
from .geometry import predict_topocentric_unit, tangent_residuals_arcmin
from .types import (
    FitSeedAudit,
    HeliocentricState,
    Observation,
    ObservationFit,
    OrbitFitResult,
    OrbitSolution,
)


@dataclass(frozen=True)
class FitConfig:
    max_nfev: int = 300
    maximum_seed_count: int | None = None
    light_time: bool = True
    perihelion_min_au: float = 0.05
    aphelion_max_au: float = 50.0
    family_prediction_threshold_arcmin: float = 0.05
    family_position_threshold_au: float = 0.01
    family_velocity_threshold_au_per_day: float = 1e-4

    def __post_init__(self) -> None:
        if self.max_nfev <= 0:
            raise ValueError("fit evaluation limit must be positive")
        if self.maximum_seed_count is not None and self.maximum_seed_count <= 0:
            raise ValueError("maximum seed count must be positive")


def _state(parameters: np.ndarray, epoch: float) -> HeliocentricState:
    return HeliocentricState(
        reference_jd_tdb=float(epoch),
        position_au=tuple(float(value) for value in parameters[:3]),
        velocity_au_per_day=tuple(float(value) for value in parameters[3:]),
    )


def _admissible(solution: HeliocentricState, config: FitConfig):
    elements = state_to_elements(solution)
    perihelion = elements.semimajor_axis_au * (1.0 - elements.eccentricity)
    aphelion = elements.semimajor_axis_au * (1.0 + elements.eccentricity)
    if perihelion < config.perihelion_min_au:
        raise ValueError("fitted perihelion below v1 limit")
    if aphelion > config.aphelion_max_au:
        raise ValueError("fitted aphelion above v1 limit")
    return elements


def _solution_from_fit(
    parameters: np.ndarray,
    epoch: float,
    observations: Sequence[Observation],
    config: FitConfig,
    cost: float,
    seed_index: int,
    jacobian: np.ndarray,
) -> OrbitSolution:
    state = _state(parameters, epoch)
    elements = _admissible(state, config)
    measured = np.asarray([row.measured_unit for row in observations])
    predicted = predict_topocentric_unit(state, observations, light_time=config.light_time)
    residuals = tangent_residuals_arcmin(measured, predicted)
    rows = []
    for observation, residual in zip(observations, residuals):
        norm = float(np.linalg.norm(residual))
        scaled = norm / observation.sigma_arcmin
        rows.append(
            ObservationFit(
                run_id=observation.direction.run_id,
                east_arcmin=float(residual[0]),
                north_arcmin=float(residual[1]),
                norm_arcmin=norm,
                sigma_arcmin=float(observation.sigma_arcmin),
                robust_weight=float(1.0 / math.sqrt(1.0 + scaled * scaled)),
                status="used",
                reason="",
            )
        )
    return OrbitSolution(
        state,
        elements,
        float(cost),
        True,
        tuple(rows),
        seed_index,
        tuple(tuple(float(value) for value in row) for row in jacobian),
    )


def _same_family(
    first: OrbitSolution,
    second: OrbitSolution,
    observations: Sequence[Observation],
    config: FitConfig,
) -> bool:
    first_position = np.asarray(first.state.position_au)
    second_position = np.asarray(second.state.position_au)
    first_velocity = np.asarray(first.state.velocity_au_per_day)
    second_velocity = np.asarray(second.state.velocity_au_per_day)
    if np.linalg.norm(first_position - second_position) >= config.family_position_threshold_au:
        return False
    if np.linalg.norm(first_velocity - second_velocity) >= config.family_velocity_threshold_au_per_day:
        return False
    first_prediction = predict_topocentric_unit(first.state, observations, light_time=config.light_time)
    second_prediction = predict_topocentric_unit(second.state, observations, light_time=config.light_time)
    separation = np.linalg.norm(tangent_residuals_arcmin(first_prediction, second_prediction), axis=1)
    return float(np.sqrt(np.mean(separation**2))) < config.family_prediction_threshold_arcmin


def fit_orbit_families(
    observations: Sequence[Observation],
    seeds: Sequence[HeliocentricState],
    config: FitConfig,
) -> OrbitFitResult:
    if not observations:
        raise ValueError("orbit fitting needs observations")
    if not seeds:
        return OrbitFitResult(float(np.median([row.jd_tdb for row in observations])), (), ())
    measured = np.asarray([row.measured_unit for row in observations])
    sigmas = np.asarray([row.sigma_arcmin for row in observations], dtype=float)
    candidates: list[OrbitSolution] = []
    audit: list[FitSeedAudit] = []
    limit = len(seeds) if config.maximum_seed_count is None else min(len(seeds), config.maximum_seed_count)

    for seed_index, seed in enumerate(seeds):
        if seed_index >= limit:
            audit.append(FitSeedAudit(seed_index, "skipped", "resource_cap", None))
            continue
        initial = np.r_[seed.position_au, seed.velocity_au_per_day].astype(float)

        def residual(parameters: np.ndarray) -> np.ndarray:
            candidate = _state(parameters, seed.reference_jd_tdb)
            try:
                predicted = predict_topocentric_unit(candidate, observations, light_time=config.light_time)
                angular = tangent_residuals_arcmin(measured, predicted)
                return (angular / sigmas[:, None]).ravel()
            except (ValueError, RuntimeError, OverflowError, FloatingPointError):
                return np.full(2 * len(observations), 1e6 + float(np.linalg.norm(parameters)))

        optimum = least_squares(
            residual,
            initial,
            loss="soft_l1",
            f_scale=1.0,
            x_scale=np.array([1.0, 1.0, 1.0, 0.01, 0.01, 0.01]),
            max_nfev=config.max_nfev,
            ftol=1e-11,
            xtol=1e-11,
            gtol=1e-11,
        )
        if not optimum.success:
            audit.append(FitSeedAudit(seed_index, "rejected", "optimizer_not_converged", float(optimum.cost)))
            continue
        try:
            solution = _solution_from_fit(
                optimum.x,
                seed.reference_jd_tdb,
                observations,
                config,
                float(optimum.cost),
                seed_index,
                optimum.jac,
            )
        except (ValueError, RuntimeError, OverflowError):
            audit.append(FitSeedAudit(seed_index, "rejected", "inadmissible_fitted_state", float(optimum.cost)))
            continue
        candidates.append(solution)
        audit.append(FitSeedAudit(seed_index, "accepted", "", float(optimum.cost)))

    families: list[OrbitSolution] = []
    for candidate in sorted(candidates, key=lambda item: (item.cost, item.seed_index)):
        if not any(_same_family(candidate, existing, observations, config) for existing in families):
            families.append(candidate)
    reference_epoch = families[0].state.reference_jd_tdb if families else float(np.median([row.jd_tdb for row in observations]))
    return OrbitFitResult(reference_epoch, tuple(families), tuple(audit))
