from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.dynamics import (
    SOLAR_GM_AU3_DAY2,
    elements_to_state,
    propagate_two_body,
    state_to_elements,
)
from find_planet.types import HeliocentricState, OrbitalElements


def angle_difference(first: float, second: float) -> float:
    return (first - second + 180.0) % 360.0 - 180.0


class TwoBodyPropagationTests(unittest.TestCase):
    def test_circular_quarter_orbit_and_reverse_propagation(self):
        epoch = 2461300.0
        speed = math.sqrt(SOLAR_GM_AU3_DAY2)
        period = 2.0 * math.pi / speed
        state = HeliocentricState(epoch, (1.0, 0.0, 0.0), (0.0, speed, 0.0))

        quarter = propagate_two_body(state, np.array([epoch + period / 4.0]))[0]
        np.testing.assert_allclose(quarter[0], [0.0, 1.0, 0.0], atol=2e-11)
        np.testing.assert_allclose(quarter[1], [-speed, 0.0, 0.0], atol=2e-12)
        quarter_state = HeliocentricState(
            epoch + period / 4.0,
            tuple(quarter[0]),
            tuple(quarter[1]),
        )
        recovered = propagate_two_body(quarter_state, np.array([epoch]))[0]
        np.testing.assert_allclose(recovered[0], state.position_au, atol=2e-11)
        np.testing.assert_allclose(recovered[1], state.velocity_au_per_day, atol=2e-12)

    def test_eccentric_propagation_conserves_energy_and_angular_momentum(self):
        epoch = 2461300.0
        radius = 1.2
        semimajor = 1.5
        speed = math.sqrt(SOLAR_GM_AU3_DAY2 * (2.0 / radius - 1.0 / semimajor))
        state = HeliocentricState(epoch, (radius, 0.0, 0.0), (0.0, speed, 0.0))

        propagated = propagate_two_body(state, epoch + np.linspace(-80.0, 80.0, 9))
        positions = propagated[:, 0]
        velocities = propagated[:, 1]
        energies = 0.5 * np.sum(velocities**2, axis=1) - SOLAR_GM_AU3_DAY2 / np.linalg.norm(positions, axis=1)
        momenta = np.cross(positions, velocities)

        self.assertLess(float(np.ptp(energies)), 2e-15)
        np.testing.assert_allclose(
            momenta,
            np.repeat(momenta[0][None, :], len(momenta), axis=0),
            atol=2e-13,
        )


class OrbitalElementTests(unittest.TestCase):
    def test_nonsingular_elements_round_trip_through_cartesian_state(self):
        elements = OrbitalElements(
            reference_jd_tdb=2461300.0,
            semimajor_axis_au=1.7,
            eccentricity=0.23,
            inclination_deg=17.0,
            longitude_ascending_node_deg=42.0,
            argument_perihelion_deg=73.0,
            mean_anomaly_deg=31.0,
            singular_flags=(),
        )

        state = elements_to_state(elements)
        recovered = state_to_elements(state)
        state_again = elements_to_state(recovered)

        self.assertAlmostEqual(recovered.semimajor_axis_au, 1.7, places=11)
        self.assertAlmostEqual(recovered.eccentricity, 0.23, places=11)
        self.assertAlmostEqual(recovered.inclination_deg, 17.0, places=10)
        self.assertAlmostEqual(angle_difference(recovered.longitude_ascending_node_deg, 42.0), 0.0, places=9)
        self.assertAlmostEqual(angle_difference(recovered.argument_perihelion_deg, 73.0), 0.0, places=9)
        self.assertAlmostEqual(angle_difference(recovered.mean_anomaly_deg, 31.0), 0.0, places=9)
        np.testing.assert_allclose(state_again.position_au, state.position_au, atol=1e-11)
        np.testing.assert_allclose(state_again.velocity_au_per_day, state.velocity_au_per_day, atol=1e-12)

    def test_circular_equatorial_orbit_flags_undefined_angles(self):
        speed = math.sqrt(SOLAR_GM_AU3_DAY2)
        state = HeliocentricState(2461300.0, (1.0, 0.0, 0.0), (0.0, speed, 0.0))

        elements = state_to_elements(state)

        self.assertIn("circular", elements.singular_flags)
        self.assertIn("equatorial", elements.singular_flags)
        self.assertIsNone(elements.longitude_ascending_node_deg)
        self.assertIsNone(elements.argument_perihelion_deg)
        self.assertIsNone(elements.mean_anomaly_deg)


if __name__ == "__main__":
    unittest.main()
