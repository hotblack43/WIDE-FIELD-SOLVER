from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from astropy.coordinates import solar_system_ephemeris
import erfa
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.observer import (
    build_observations,
    earth_heliocentric_state_epv00,
    mmto_heliocentric_state,
    utc_midpoint_to_tdb_jd,
)
from find_planet.types import AnonymousDirection


REFERENCE_EPOCHS = {
    "2026-09-12T11:00:08Z": 2461295.9592266493,
    "2026-10-01T06:20:00Z": 2461314.764689611,
    "2026-10-26T12:00:15Z": 2461340.0009743343,
}


def direction(timestamp: str, fit_rms: float = 2.5) -> AnonymousDirection:
    return AnonymousDirection(
        object_id="Object A",
        run_id=f"run-{timestamp}",
        source_sha256=f"sha-{timestamp}",
        source_path=f"/archive/{timestamp}.fits",
        night=timestamp[:10],
        observation_time_utc=timestamp,
        detection_id="7",
        x_px=100.0,
        y_px=200.0,
        icrs_unit=(0.6, 0.0, 0.8),
        stellar_fit_rms_arcmin=fit_rms,
        source_class="compact",
        saturated=False,
        integrated_refraction_status="rejected",
    )


class ObserverTimeTests(unittest.TestCase):
    def test_utc_midpoints_convert_to_pinned_tdb_julian_dates(self):
        for timestamp, expected in REFERENCE_EPOCHS.items():
            with self.subTest(timestamp=timestamp):
                self.assertAlmostEqual(utc_midpoint_to_tdb_jd(timestamp), expected, places=9)

    def test_earth_state_matches_direct_erfa_epv00(self):
        for jd in REFERENCE_EPOCHS.values():
            with self.subTest(jd=jd):
                position, velocity = earth_heliocentric_state_epv00(jd)
                split = jd - 2451545.0
                expected, _ = erfa.epv00(2451545.0, split)
                np.testing.assert_allclose(position, expected["p"], atol=1e-12, rtol=0.0)
                np.testing.assert_allclose(velocity, expected["v"], atol=1e-12, rtol=0.0)

    def test_mmto_topocentre_is_near_one_earth_radius(self):
        state = mmto_heliocentric_state(REFERENCE_EPOCHS["2026-10-01T06:20:00Z"])

        radius_au = np.linalg.norm(state.topocentre_position_au)
        self.assertGreater(radius_au, 4.1e-5)
        self.assertLess(radius_au, 4.4e-5)
        np.testing.assert_allclose(
            np.asarray(state.position_au) - np.asarray(state.earth_position_au),
            state.topocentre_position_au,
            atol=1e-15,
        )

    def test_observer_path_cannot_call_general_planet_ephemerides(self):
        self.assertIsNone(importlib.util.find_spec("astroquery"))
        timestamp = "2026-09-12T11:00:08Z"
        with (
            patch("astropy.coordinates.get_body", side_effect=AssertionError("get_body forbidden")),
            patch.object(
                solar_system_ephemeris,
                "set",
                side_effect=AssertionError("general ephemeris forbidden"),
            ),
        ):
            jd = utc_midpoint_to_tdb_jd(timestamp)
            earth_heliocentric_state_epv00(jd)
            mmto_heliocentric_state(jd)
            observations = build_observations([direction(timestamp)])

        self.assertEqual(len(observations), 1)


class ObservationConstructionTests(unittest.TestCase):
    def test_build_observations_preserves_rays_and_applies_sigma_floor(self):
        first = direction("2026-09-12T11:00:08Z", fit_rms=0.4)
        second = direction("2026-10-26T12:00:15Z", fit_rms=3.5)

        observations = build_observations([first, second])

        self.assertEqual([row.direction for row in observations], [first, second])
        self.assertEqual([row.sigma_arcmin for row in observations], [1.0, 3.5])
        self.assertEqual(observations[0].measured_unit, first.icrs_unit)
        self.assertAlmostEqual(observations[0].jd_tdb, REFERENCE_EPOCHS[first.observation_time_utc], places=9)


if __name__ == "__main__":
    unittest.main()
