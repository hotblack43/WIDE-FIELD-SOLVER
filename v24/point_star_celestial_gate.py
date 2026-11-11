"""Cheap Sun/Moon horizon compatibility before exact planet refinement."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


MOON_HORIZON_GUARD_DEG = 5.0


def _unit(vector):
    value = np.asarray(vector, dtype=float)
    norm = np.linalg.norm(value)
    if value.shape != (3,) or not np.isfinite(value).all() or norm <= 0:
        raise ValueError("Celestial direction must be a finite nonzero three-vector")
    return value / norm


@dataclass
class CelestialHorizonGate:
    """Require night and agreement with the image's binary Moon state."""

    solar_constraint: object
    zenith_unit_vector: object
    observed_moon_present: bool
    moon_prediction_function: object
    moon_horizon_guard_deg: float = MOON_HORIZON_GUARD_DEG

    def __post_init__(self):
        self.zenith_unit_vector = _unit(self.zenith_unit_vector)
        self.observed_moon_present = bool(self.observed_moon_present)
        self.moon_horizon_guard_deg = float(self.moon_horizon_guard_deg)
        if (not np.isfinite(self.moon_horizon_guard_deg)
                or self.moon_horizon_guard_deg < 0):
            raise ValueError("Moon horizon guard must be finite and nonnegative")

    def assess(self, date, positional_interval=None):
        """Return a conservative binary compatibility decision at one date."""
        solar = self.solar_constraint.assess(float(date), positional_interval)
        solar_compatible = solar.get("status") != "solar_inconsistent"
        try:
            prediction = self.moon_prediction_function(
                float(date), self.zenith_unit_vector.copy())
            vector = _unit(prediction["unit_vector"])
            altitude = float(np.rad2deg(np.arcsin(np.clip(
                vector @ self.zenith_unit_vector, -1.0, 1.0))))
            guard = self.moon_horizon_guard_deg
            if altitude > guard:
                predicted_state = "above_horizon"
            elif altitude < -guard:
                predicted_state = "below_horizon"
            else:
                predicted_state = "horizon_guard"
            contradiction = (
                (self.observed_moon_present and predicted_state == "below_horizon")
                or (not self.observed_moon_present
                    and predicted_state == "above_horizon")
            )
            lunar = {
                "status": ("moon_horizon_contradiction" if contradiction else
                           "moon_horizon_unresolved" if predicted_state == "horizon_guard"
                           else "moon_horizon_compatible"),
                "selection_effect": "contradict" if contradiction else "neutral",
                "observed_moon_present": self.observed_moon_present,
                "predicted_altitude_deg": altitude,
                "predicted_horizon_state": predicted_state,
                "minimum_altitude_deg": guard,
                "metadata_used": False,
            }
        except (KeyError, TypeError, ValueError, RuntimeError):
            contradiction = False
            lunar = {
                "status": "moon_horizon_unresolved",
                "selection_effect": "neutral",
                "observed_moon_present": self.observed_moon_present,
                "minimum_altitude_deg": self.moon_horizon_guard_deg,
                "metadata_used": False,
            }
        return {
            "eligible": bool(solar_compatible and not contradiction),
            "solar": solar,
            "lunar": lunar,
            "metadata_used": False,
        }
