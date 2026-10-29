"""Identity-free systematic ranging over an admissible bound-orbit region."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np

from .dynamics import SOLAR_GM_AU3_DAY2, state_to_elements
from .types import HeliocentricState, Observation, RangeSeedAudit


@dataclass(frozen=True)
class RangingConfig:
    distance_min_au: float = 0.02
    distance_max_au: float = 100.0
    distance_steps: int = 24
    range_rate_steps: int = 9
    perihelion_min_au: float = 0.05
    aphelion_max_au: float = 50.0

    def __post_init__(self) -> None:
        if not (0.0 < self.distance_min_au < self.distance_max_au):
            raise ValueError("ranging distances must be positive and increasing")
        if self.distance_steps < 2 or self.range_rate_steps < 3:
            raise ValueError("ranging grids need at least two distances and three rates")
        if not (0.0 < self.perihelion_min_au < self.aphelion_max_au):
            raise ValueError("admissible perihelion/aphelion limits are invalid")


def _reference_geometry(observations: Sequence[Observation]) -> tuple[Observation, np.ndarray]:
    if not observations:
        raise ValueError("systematic ranging needs observations")
    ordered = sorted(observations, key=lambda row: (row.jd_tdb, row.direction.run_id))
    epochs = np.array([row.jd_tdb for row in ordered])
    reference_epoch = float(np.median(epochs))
    reference = min(ordered, key=lambda row: (abs(row.jd_tdb - reference_epoch), row.direction.run_id))
    units = np.asarray([row.measured_unit for row in ordered], dtype=float)
    weights = 1.0 / np.square([row.sigma_arcmin for row in ordered])
    delta = epochs - reference.jd_tdb
    if len(ordered) == 1 or float(np.sum(weights * delta**2)) <= 1e-20:
        derivative = np.zeros(3)
    else:
        design = np.column_stack([np.ones(len(delta)), delta])
        weighted = design * np.sqrt(weights)[:, None]
        coefficients = np.linalg.lstsq(weighted, units * np.sqrt(weights)[:, None], rcond=None)[0]
        derivative = coefficients[1]
    reference_unit = np.asarray(reference.measured_unit, dtype=float)
    derivative -= float(derivative @ reference_unit) * reference_unit
    return reference, derivative


def systematic_range_seed_records(
    observations: Sequence[Observation],
    config: RangingConfig,
) -> tuple[list[HeliocentricState], list[RangeSeedAudit]]:
    reference, angular_derivative = _reference_geometry(observations)
    observer_position = np.asarray(reference.observer.position_au, dtype=float)
    observer_velocity = np.asarray(reference.observer.velocity_au_per_day, dtype=float)
    line = np.asarray(reference.measured_unit, dtype=float)
    seeds: list[HeliocentricState] = []
    audit: list[RangeSeedAudit] = []
    for distance in np.geomspace(
        config.distance_min_au,
        config.distance_max_au,
        config.distance_steps,
    ):
        position = observer_position + distance * line
        radius = float(np.linalg.norm(position))
        base_velocity = observer_velocity + distance * angular_derivative
        escape_speed2 = 2.0 * SOLAR_GM_AU3_DAY2 / radius
        along = float(base_velocity @ line)
        discriminant = along * along - (float(base_velocity @ base_velocity) - escape_speed2)
        if discriminant <= 0.0 or not math.isfinite(discriminant):
            audit.append(RangeSeedAudit(float(distance), None, "rejected", "no_bound_range_rate_interval", None))
            continue
        root = math.sqrt(discriminant)
        rates = np.linspace(-along - root, -along + root, config.range_rate_steps)
        for range_rate in rates:
            velocity = base_velocity + float(range_rate) * line
            energy = float(velocity @ velocity) / 2.0 - SOLAR_GM_AU3_DAY2 / radius
            if energy >= -1e-15:
                audit.append(RangeSeedAudit(float(distance), float(range_rate), "rejected", "unbound_endpoint", None))
                continue
            state = HeliocentricState(
                reference_jd_tdb=float(reference.jd_tdb),
                position_au=tuple(float(value) for value in position),
                velocity_au_per_day=tuple(float(value) for value in velocity),
            )
            try:
                elements = state_to_elements(state)
            except ValueError:
                audit.append(RangeSeedAudit(float(distance), float(range_rate), "rejected", "invalid_bound_elements", None))
                continue
            perihelion = elements.semimajor_axis_au * (1.0 - elements.eccentricity)
            aphelion = elements.semimajor_axis_au * (1.0 + elements.eccentricity)
            if perihelion < config.perihelion_min_au:
                reason = "solar_collision_or_low_perihelion"
            elif aphelion > config.aphelion_max_au:
                reason = "aphelion_above_v1_limit"
            else:
                reason = ""
            if reason:
                audit.append(RangeSeedAudit(float(distance), float(range_rate), "rejected", reason, state))
            else:
                seeds.append(state)
                audit.append(RangeSeedAudit(float(distance), float(range_rate), "accepted", "", state))
    return seeds, audit


def systematic_range_seeds(
    observations: Sequence[Observation],
    config: RangingConfig,
) -> list[HeliocentricState]:
    seeds, _ = systematic_range_seed_records(observations, config)
    return seeds
