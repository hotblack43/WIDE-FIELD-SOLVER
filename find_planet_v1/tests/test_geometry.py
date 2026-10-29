from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.geometry import predict_topocentric_unit, tangent_residuals_arcmin
from find_planet.types import (
    AnonymousDirection,
    HeliocentricState,
    Observation,
    ObserverState,
)


def unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    return np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])


def zero_observation(jd: float) -> Observation:
    direction = AnonymousDirection(
        object_id="Object A",
        run_id="run-a",
        source_sha256="sha-a",
        source_path="/archive/a.fits",
        night="2026-09-01",
        observation_time_utc="2026-09-02T03:00:00Z",
        detection_id="1",
        x_px=1.0,
        y_px=1.0,
        icrs_unit=(1.0, 0.0, 0.0),
        stellar_fit_rms_arcmin=1.0,
        source_class="compact",
        saturated=False,
        integrated_refraction_status="rejected",
    )
    zero = (0.0, 0.0, 0.0)
    observer = ObserverState(jd, zero, zero, zero, zero, zero, zero)
    return Observation(direction, jd, (1.0, 0.0, 0.0), 1.0, observer)


class TangentResidualTests(unittest.TestCase):
    def test_ra_wrap_has_small_positive_eastward_residual(self):
        measured = unit(359.9, 0.0)[None, :]
        predicted = unit(0.1, 0.0)[None, :]

        residual = tangent_residuals_arcmin(measured, predicted)[0]

        self.assertAlmostEqual(residual[0], 12.0, places=6)
        self.assertAlmostEqual(residual[1], 0.0, places=9)

    def test_near_pole_residual_is_finite_with_deterministic_sign(self):
        measured = unit(0.0, 89.0)[None, :]
        predicted = unit(0.0, 89.1)[None, :]

        residual = tangent_residuals_arcmin(measured, predicted)[0]

        self.assertTrue(np.isfinite(residual).all())
        self.assertAlmostEqual(float(np.linalg.norm(residual)), 6.0, places=6)
        self.assertLess(residual[1], 0.0)

    def test_antipode_cannot_appear_as_zero_residual(self):
        residual = tangent_residuals_arcmin(
            np.array([[1.0, 0.0, 0.0]]),
            np.array([[-1.0, 0.0, 0.0]]),
        )[0]
        self.assertAlmostEqual(float(np.linalg.norm(residual)), 180.0 * 60.0, places=8)


class LightTimeTests(unittest.TestCase):
    def test_iterative_light_time_changes_direction_and_converges(self):
        epoch = 2461300.0
        state = HeliocentricState(epoch, (1.5, 0.0, 0.0), (0.0, 0.012, 0.0))
        observation = zero_observation(epoch)

        instantaneous = predict_topocentric_unit(state, [observation], light_time=False)[0]
        delayed = predict_topocentric_unit(state, [observation], light_time=True)[0]
        repeated = predict_topocentric_unit(state, [observation], light_time=True)[0]

        np.testing.assert_allclose(instantaneous, [1.0, 0.0, 0.0], atol=1e-14)
        self.assertLess(delayed[1], 0.0)
        self.assertGreater(float(np.linalg.norm(delayed - instantaneous)), 1e-7)
        np.testing.assert_allclose(repeated, delayed, atol=1e-15)
        self.assertAlmostEqual(float(np.linalg.norm(delayed)), 1.0, places=14)


if __name__ == "__main__":
    unittest.main()
