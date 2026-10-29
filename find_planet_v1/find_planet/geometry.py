"""Topocentric apparent directions and signed tangent-plane residuals."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .dynamics import propagate_two_body
from .types import HeliocentricState, Observation


ARCMIN_PER_RADIAN = 180.0 * 60.0 / math.pi
LIGHT_SPEED_AU_PER_DAY = 173.144632674240


def _normalise_rows(values: np.ndarray) -> np.ndarray:
    vectors = np.asarray(values, dtype=float)
    if vectors.ndim != 2 or vectors.shape[1] != 3 or not np.isfinite(vectors).all():
        raise ValueError("directions must be a finite Nx3 array")
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms <= 0.0):
        raise ValueError("directions must be nonzero")
    return vectors / norms[:, None]


def tangent_residuals_arcmin(measured: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    measured_units = _normalise_rows(measured)
    predicted_units = _normalise_rows(predicted)
    if measured_units.shape != predicted_units.shape:
        raise ValueError("measured and predicted directions must be paired")
    dot = np.clip(np.sum(predicted_units * measured_units, axis=1), -1.0, 1.0)
    pole = np.zeros_like(measured_units)
    pole[:, 2] = 1.0
    near_pole = np.abs(measured_units[:, 2]) > 0.9
    pole[near_pole] = [1.0, 0.0, 0.0]
    axis_one = np.cross(pole, measured_units)
    axis_one /= np.linalg.norm(axis_one, axis=1)[:, None]
    axis_two = np.cross(measured_units, axis_one)
    components = np.column_stack(
        [
            np.sum(predicted_units * axis_one, axis=1),
            np.sum(predicted_units * axis_two, axis=1),
        ]
    )
    sine = np.linalg.norm(components, axis=1)
    angles = np.arctan2(sine, dot)
    nonzero = sine > 1e-15
    components[nonzero] *= (angles[nonzero] / sine[nonzero])[:, None]
    antipodal = ~nonzero & (dot < 0.0)
    components[antipodal, 0] = math.pi
    return components * ARCMIN_PER_RADIAN


def predict_topocentric_unit(
    state: HeliocentricState,
    observations: Sequence[Observation],
    light_time: bool = True,
) -> np.ndarray:
    predicted = np.empty((len(observations), 3), dtype=float)
    for index, observation in enumerate(observations):
        observer_position = np.asarray(observation.observer.position_au, dtype=float)
        emission_jd = float(observation.jd_tdb)
        if light_time:
            for _ in range(20):
                object_position = propagate_two_body(state, np.array([emission_jd]))[0, 0]
                distance = float(np.linalg.norm(object_position - observer_position))
                if not math.isfinite(distance) or distance <= 0.0:
                    raise RuntimeError("light-time iteration produced an invalid distance")
                updated = float(observation.jd_tdb) - distance / LIGHT_SPEED_AU_PER_DAY
                if abs(updated - emission_jd) < 1e-10:
                    emission_jd = updated
                    break
                emission_jd = updated
            else:
                raise RuntimeError("one-way light-time iteration did not converge")
        object_position = propagate_two_body(state, np.array([emission_jd]))[0, 0]
        line_of_sight = object_position - observer_position
        norm = float(np.linalg.norm(line_of_sight))
        if norm <= 0.0 or not math.isfinite(norm):
            raise RuntimeError("topocentric prediction produced an invalid direction")
        predicted[index] = line_of_sight / norm
    return predicted
