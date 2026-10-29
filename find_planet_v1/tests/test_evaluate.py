from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.dynamics import elements_to_state
from find_planet.evaluate import (
    BaselineModel,
    evaluate_controlled,
    fit_angular_velocity,
    fit_fixed_direction,
    local_covariance,
    score_predictions,
    split_nights,
)
from find_planet.fitting import FitConfig
from find_planet.geometry import predict_topocentric_unit
from find_planet.observer import mmto_heliocentric_state
from find_planet.types import AnonymousDirection, Observation, OrbitalElements


def observations_by_night(count: int = 12, rows_per_night: int = 2) -> list[Observation]:
    epoch = 2461000.0
    state = elements_to_state(OrbitalElements(epoch, 1.7, 0.2, 7.0, 30.0, 55.0, 80.0, ()))
    rows: list[Observation] = []
    for night_index in range(count):
        for within in range(rows_per_night):
            jd = epoch + night_index * 1.7 + within * 0.01
            observer = mmto_heliocentric_state(jd)
            placeholder = AnonymousDirection(
                "Object A", f"run-{night_index}-{within}", f"sha-{night_index}-{within}",
                f"image-{night_index}-{within}.fits", f"2026-10-{night_index + 1:02d}",
                "2026-10-01T00:00:00Z", f"d-{night_index}-{within}", 1.0, 2.0,
                (1.0, 0.0, 0.0), 0.8, "large", False, "integrated",
            )
            row = Observation(placeholder, jd, (1.0, 0.0, 0.0), 1.0, observer)
            unit = tuple(predict_topocentric_unit(state, [row], light_time=True)[0])
            rows.append(replace(row, measured_unit=unit, direction=replace(placeholder, icrs_unit=unit)))
    return rows


class SplitAndBaselineTests(unittest.TestCase):
    def test_every_fifth_chronological_night_is_wholly_withheld(self):
        rows = list(reversed(observations_by_night()))
        split = split_nights(rows)
        self.assertEqual(split.withheld_nights, ("2026-10-05", "2026-10-10"))
        self.assertEqual({row.direction.night for row in split.withheld}, set(split.withheld_nights))
        self.assertFalse({row.direction.night for row in split.train} & set(split.withheld_nights))
        self.assertEqual(len(split.train) + len(split.withheld), len(rows))

    def test_baselines_are_fit_only_from_the_rows_passed_to_them(self):
        split = split_nights(observations_by_night())
        fixed = fit_fixed_direction(split.train)
        moving = fit_angular_velocity(split.train)
        poisoned = [replace(row, measured_unit=(-1.0, 0.0, 0.0)) for row in split.withheld]
        self.assertEqual(fixed, fit_fixed_direction(split.train))
        self.assertEqual(moving, fit_angular_velocity(split.train))
        self.assertNotEqual(fixed, fit_fixed_direction([*split.train, *poisoned]))

    def test_score_reports_declared_statistics_on_identical_rows(self):
        split = split_nights(observations_by_night())
        fixed_score = score_predictions(fit_fixed_direction(split.train), split.withheld)
        moving_score = score_predictions(fit_angular_velocity(split.train), split.withheld)
        self.assertEqual(fixed_score.run_ids, moving_score.run_ids)
        self.assertEqual(fixed_score.sigmas_arcmin, moving_score.sigmas_arcmin)
        for score in (fixed_score, moving_score):
            self.assertGreaterEqual(score.median_arcmin, 0.0)
            self.assertGreaterEqual(score.rms_arcmin, score.median_arcmin)
            self.assertGreaterEqual(score.p90_arcmin, score.median_arcmin)
            self.assertGreaterEqual(score.weighted_chi_square, 0.0)


class UncertaintyAndEvaluationTests(unittest.TestCase):
    def test_rank_deficient_jacobian_is_explicitly_unresolved(self):
        result = local_covariance(np.ones((4, 6)))
        self.assertFalse(result.supported)
        self.assertLess(result.rank, 6)
        self.assertIsNone(result.covariance)
        full = local_covariance(np.eye(6))
        self.assertTrue(full.supported)
        np.testing.assert_allclose(full.covariance, np.eye(6))

    def test_primary_weighting_cannot_be_replaced_by_sensitivity_runs(self):
        rows = observations_by_night(10, 1)
        result = evaluate_controlled(
            rows,
            FitConfig(max_nfev=80, maximum_seed_count=3),
            bootstrap_replicates=3,
            bootstrap_seed=17,
        )
        self.assertEqual(result.primary_sigma_scale, 1.0)
        self.assertEqual(set(result.sensitivity.keys()), {0.5, 2.0})
        self.assertIsNot(result.primary_fit, result.sensitivity[0.5])
        self.assertIsNot(result.primary_fit, result.sensitivity[2.0])
        self.assertEqual(result.bootstrap.seed, 17)
        again = evaluate_controlled(
            rows,
            FitConfig(max_nfev=80, maximum_seed_count=3),
            bootstrap_replicates=3,
            bootstrap_seed=17,
        )
        self.assertEqual(result.bootstrap.sampled_nights, again.bootstrap.sampled_nights)
        self.assertEqual(result.bootstrap.statuses, again.bootstrap.statuses)


if __name__ == "__main__":
    unittest.main()
