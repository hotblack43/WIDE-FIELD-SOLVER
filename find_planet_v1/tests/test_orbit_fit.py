from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.dynamics import elements_to_state, state_to_elements
from find_planet.fitting import FitConfig, fit_orbit_families
from find_planet.geometry import predict_topocentric_unit, tangent_residuals_arcmin
from find_planet.observer import mmto_heliocentric_state
from find_planet.ranging import RangingConfig, systematic_range_seed_records, systematic_range_seeds
from find_planet.types import AnonymousDirection, HeliocentricState, Observation, OrbitalElements


REAL_NIGHT_OFFSETS = np.array(
    [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 12, 13, 15, 18, 19, 20, 21,
     22, 23, 24, 25, 26, 27, 32, 33, 34, 35, 36, 38, 39, 40, 41, 43, 44],
    dtype=float,
)


def true_state(epoch: float, variant: int = 0) -> HeliocentricState:
    elements = OrbitalElements(
        reference_jd_tdb=epoch,
        semimajor_axis_au=1.52 + 0.35 * variant,
        eccentricity=0.08 + 0.04 * variant,
        inclination_deg=5.0 + 7.0 * variant,
        longitude_ascending_node_deg=30.0 + 40.0 * variant,
        argument_perihelion_deg=45.0 + 10.0 * variant,
        mean_anomaly_deg=20.0 + 55.0 * variant,
        singular_flags=(),
    )
    return elements_to_state(elements)


def placeholder_observation(jd: float, index: int) -> Observation:
    direction = AnonymousDirection(
        object_id="Object A",
        run_id=f"run-{index:03d}",
        source_sha256=f"sha-{index:03d}",
        source_path=f"/archive/{index:03d}.fits",
        night=f"night-{index:03d}",
        observation_time_utc="2026-09-12T11:00:08Z",
        detection_id=str(index),
        x_px=100.0,
        y_px=200.0,
        icrs_unit=(1.0, 0.0, 0.0),
        stellar_fit_rms_arcmin=2.0,
        source_class="compact",
        saturated=False,
        integrated_refraction_status="rejected",
    )
    return Observation(direction, jd, (1.0, 0.0, 0.0), 2.0, mmto_heliocentric_state(jd))


def rotate_tangent(unit: np.ndarray, east_arcmin: float, north_arcmin: float) -> np.ndarray:
    pole = np.array([0.0, 0.0, 1.0]) if abs(unit[2]) <= 0.9 else np.array([1.0, 0.0, 0.0])
    east = np.cross(pole, unit)
    east /= np.linalg.norm(east)
    north = np.cross(unit, east)
    shifted = unit + math.radians(east_arcmin / 60.0) * east + math.radians(north_arcmin / 60.0) * north
    return shifted / np.linalg.norm(shifted)


def synthetic_observations(
    state: HeliocentricState,
    offsets: np.ndarray = REAL_NIGHT_OFFSETS,
    noise_arcmin: float = 0.0,
    outlier_index: int | None = None,
) -> list[Observation]:
    placeholders = [placeholder_observation(state.reference_jd_tdb + float(offset), i) for i, offset in enumerate(offsets)]
    exact = predict_topocentric_unit(state, placeholders)
    rows: list[Observation] = []
    for index, (template, measured) in enumerate(zip(placeholders, exact)):
        if noise_arcmin:
            measured = rotate_tangent(
                measured,
                noise_arcmin * math.sin(index * 1.7),
                noise_arcmin * math.cos(index * 1.3),
            )
        if outlier_index == index:
            measured = rotate_tangent(measured, 45.0, -30.0)
        direction = AnonymousDirection(
            **{
                **template.direction.__dict__,
                "icrs_unit": tuple(float(value) for value in measured),
            }
        )
        rows.append(
            Observation(
                direction=direction,
                jd_tdb=template.jd_tdb,
                measured_unit=direction.icrs_unit,
                sigma_arcmin=2.0,
                observer=template.observer,
            )
        )
    return rows


class SystematicRangingTests(unittest.TestCase):
    def test_seeds_are_deterministic_bound_and_inside_declared_admissible_region(self):
        state = true_state(2461295.9592266493)
        observations = synthetic_observations(state)
        config = RangingConfig(
            distance_min_au=0.2,
            distance_max_au=4.0,
            distance_steps=7,
            range_rate_steps=5,
        )

        first, first_audit = systematic_range_seed_records(observations, config)
        second = systematic_range_seeds(observations, config)

        self.assertEqual(first, second)
        self.assertGreater(len(first), 0)
        self.assertGreater(len(first_audit), len(first))
        self.assertTrue(any(row.status == "rejected" for row in first_audit))
        for seed in first:
            elements = state_to_elements(seed)
            self.assertGreaterEqual(elements.semimajor_axis_au * (1.0 - elements.eccentricity), 0.05 - 1e-12)
            self.assertLessEqual(elements.semimajor_axis_au * (1.0 + elements.eccentricity), 50.0 + 1e-10)


class OrbitFitTests(unittest.TestCase):
    def test_noiseless_real_cadence_recovers_directions_for_two_orbits(self):
        for variant in (0, 1):
            with self.subTest(variant=variant):
                state = true_state(2461295.9592266493, variant)
                observations = synthetic_observations(state)
                seeds = systematic_range_seeds(
                    observations,
                    RangingConfig(0.2, 5.0, 7, 5),
                )
                result = fit_orbit_families(
                    observations,
                    seeds,
                    FitConfig(max_nfev=180, maximum_seed_count=35),
                )
                self.assertGreater(len(result.solutions), 0)
                best = result.solutions[0]
                residuals = np.asarray([[row.east_arcmin, row.north_arcmin] for row in best.observation_fits])
                self.assertLess(float(np.sqrt(np.mean(residuals**2))), 1e-3)
                self.assertEqual(len(best.observation_fits), len(observations))
                self.assertTrue(all(row.status == "used" and row.reason == "" for row in best.observation_fits))

    def test_soft_l1_fit_limits_one_severe_outlier(self):
        state = true_state(2461295.9592266493)
        observations = synthetic_observations(state, noise_arcmin=0.7, outlier_index=17)
        displaced = HeliocentricState(
            state.reference_jd_tdb,
            tuple(np.asarray(state.position_au) + [0.01, -0.01, 0.005]),
            tuple(np.asarray(state.velocity_au_per_day) + [1e-4, -1e-4, 5e-5]),
        )
        initial = predict_topocentric_unit(displaced, observations)
        measured = np.asarray([row.measured_unit for row in observations])
        initial_median = float(np.median(np.linalg.norm(tangent_residuals_arcmin(measured, initial), axis=1)))

        result = fit_orbit_families(observations, [displaced], FitConfig(max_nfev=300))

        self.assertGreater(len(result.solutions), 0)
        best = result.solutions[0]
        final_norms = np.array([row.norm_arcmin for row in best.observation_fits])
        self.assertLess(float(np.median(final_norms)), initial_median)
        self.assertLess(best.observation_fits[17].robust_weight, np.median([row.robust_weight for row in best.observation_fits]))
        self.assertEqual(len(best.observation_fits), len(observations))

    def test_one_direction_retains_multiple_distinct_compatible_families(self):
        state = true_state(2461295.9592266493)
        observations = synthetic_observations(state, offsets=np.array([0.0]))
        seeds = systematic_range_seeds(
            observations,
            RangingConfig(0.2, 4.0, 7, 3),
        )

        result = fit_orbit_families(
            observations,
            seeds,
            FitConfig(max_nfev=30, maximum_seed_count=21, light_time=False),
        )

        self.assertGreaterEqual(len(result.solutions), 2)
        positions = np.asarray([solution.state.position_au for solution in result.solutions])
        self.assertGreater(float(np.max(np.linalg.norm(positions[:, None] - positions[None, :], axis=2))), 0.1)
        self.assertEqual(len(result.seed_audit), len(seeds))


if __name__ == "__main__":
    unittest.main()
