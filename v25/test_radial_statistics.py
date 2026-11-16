"""Statistical tests for nested radial camera comparisons."""
from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import numpy as np

from point_star_barghini import BarghiniCamera
from radial_model import ExtendedBarghiniCamera
from radial_statistics import (
    akaike_weights,
    classify_order,
    cross_validate_orders,
    fit_extended_camera,
    information_criteria,
    select_supported_order,
    spatial_folds,
)


class InformationCriterionTests(unittest.TestCase):
    def test_literal_information_criteria(self):
        rss = 37.5
        n = 120
        k = 9
        expected_aic = n * math.log(rss / n) + 2 * k
        expected_aicc = expected_aic + 2 * k * (k + 1) / (n - k - 1)
        expected_bic = n * math.log(rss / n) + k * math.log(n)

        answer = information_criteria(rss, n, k)

        self.assertTrue(answer["valid"])
        self.assertIsNone(answer["reason"])
        self.assertAlmostEqual(answer["aic"], expected_aic, places=14)
        self.assertAlmostEqual(answer["aicc"], expected_aicc, places=14)
        self.assertAlmostEqual(answer["bic"], expected_bic, places=14)

    def test_undefined_inputs_report_reasons_without_invented_values(self):
        cases = (
            (0.0, 100, 8, "non_positive_rss"),
            (float("nan"), 100, 8, "non_finite_input"),
            (10.0, 9, 8, "insufficient_sample"),
            (10.0, 100, -1, "invalid_parameter_count"),
        )
        for rss, n, k, reason in cases:
            with self.subTest(reason=reason):
                answer = information_criteria(rss, n, k)
                self.assertFalse(answer["valid"])
                self.assertEqual(answer["reason"], reason)
                self.assertIsNone(answer["aic"])
                self.assertIsNone(answer["aicc"])
                self.assertIsNone(answer["bic"])

    def test_akaike_weights_exclude_failed_rows_and_sum_to_one(self):
        rows = [
            {"aicc": 10.0, "valid": True},
            {"aicc": 12.0, "valid": True},
            {"aicc": None, "valid": False},
            {"aicc": float("nan"), "valid": True},
        ]
        weights = akaike_weights(rows)
        expected_first = 1.0 / (1.0 + math.exp(-1.0))
        self.assertAlmostEqual(weights[0], expected_first)
        self.assertAlmostEqual(weights[1], 1.0 - expected_first)
        self.assertIsNone(weights[2])
        self.assertIsNone(weights[3])
        self.assertAlmostEqual(sum(value for value in weights if value is not None), 1.0)
        self.assertTrue(all(isinstance(value, float) for value in weights[:2]))


class ExtendedFitTests(unittest.TestCase):
    def setUp(self):
        baseline = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        p = baseline.p.copy()
        p[0] = 0.08
        p[1:3] += [0.025, -0.018]
        p[3:5] += [-0.014, 0.021]
        p[6] = 0.07
        p[7] = 1.15
        baseline.p = p
        self.truth = ExtendedBarghiniCamera.from_camera(
            baseline, coefficients=[0.035, -0.014]
        )
        x = np.linspace(55.0, 945.0, 11)
        y = np.linspace(45.0, 755.0, 9)
        self.xy = np.array([(xx, yy) for yy in y for xx in x])
        self.sky = self.truth.to_sky(self.xy)

    def test_m2_fit_reduces_rss_and_recovers_held_out_pixels(self):
        train = np.arange(len(self.xy)) % 4 != 0
        initial_baseline = BarghiniCamera(
            self.truth.shape,
            self.truth.reference_rotation,
            self.truth.p.copy(),
            self.truth.detector_parity,
        )
        m0 = ExtendedBarghiniCamera.from_camera(initial_baseline, coefficients=[])
        m2 = ExtendedBarghiniCamera.from_camera(initial_baseline, coefficients=[0.0, 0.0])

        fit0 = fit_extended_camera(
            m0, self.xy[train], self.sky[train], robust=False, max_nfev=1200
        )
        fit2 = fit_extended_camera(
            m2, self.xy[train], self.sky[train], robust=False, max_nfev=1200
        )

        self.assertTrue(fit0.success, fit0.failure_reason)
        self.assertTrue(fit2.success, fit2.failure_reason)
        self.assertLess(fit2.rss_arcmin2, fit0.rss_arcmin2 * 1e-5)
        error0 = np.linalg.norm(fit0.camera.project(self.sky[~train]) - self.xy[~train], axis=1)
        error2 = np.linalg.norm(fit2.camera.project(self.sky[~train]) - self.xy[~train], axis=1)
        self.assertLess(np.sqrt(np.mean(error2**2)), np.sqrt(np.mean(error0**2)) * 0.02)
        self.assertEqual(fit2.k, 10)
        self.assertEqual(fit2.jacobian_rank, 10)
        self.assertTrue(np.isfinite(fit2.jacobian_condition))
        self.assertGreater(fit2.nfev, 0)
        self.assertGreater(fit2.minimum_derivative, 0.0)
        self.assertLess(fit2.rms_arcmin, 1e-5)
        self.assertLess(fit2.rms_px, 1e-5)

    def test_degenerate_geometry_is_reported_as_rank_failure(self):
        xy = np.repeat([[500.0, 400.0]], 30, axis=0)
        sky = self.truth.to_sky(xy)
        camera = ExtendedBarghiniCamera.from_camera(
            BarghiniCamera(
                self.truth.shape,
                self.truth.reference_rotation,
                self.truth.p.copy(),
                self.truth.detector_parity,
            ),
            coefficients=[0.0],
        )

        result = fit_extended_camera(camera, xy, sky, robust=False, max_nfev=100)

        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "rank_deficient")
        self.assertLess(result.jacobian_rank, result.k)


class SpatialValidationTests(unittest.TestCase):
    def setUp(self):
        self.baseline = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        centre = np.array([499.5, 399.5])
        points = []
        for sector in range(8):
            angle = (sector + 0.35) * 2.0 * np.pi / 8.0
            for radius in np.linspace(70.0, 490.0, 8):
                direction = np.array([np.cos(angle), np.sin(angle)])
                points.append(centre + radius * direction)
        self.xy = np.asarray(points)

    def test_spatial_folds_are_deterministic_contiguous_annular_wedges(self):
        centre = np.array([499.5, 399.5])
        first = spatial_folds(self.xy, centre, fold_count=8)
        second = spatial_folds(self.xy, centre, fold_count=8)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(set(first), set(range(8)))
        self.assertTrue(all(np.count_nonzero(first == fold) == 8 for fold in range(8)))
        radii = np.linalg.norm(self.xy - centre, axis=1)
        angles = np.mod(np.arctan2(self.xy[:, 1] - centre[1], self.xy[:, 0] - centre[0]), 2 * np.pi)
        median_radius = np.median(radii)
        for fold in range(8):
            held = first == fold
            # Each block stays wholly in one radial half and occupies one
            # compact angular sector rather than sampling all directions.
            self.assertTrue(np.all(radii[held] <= median_radius) or np.all(radii[held] >= median_radius))
            ordered = np.sort(angles[held])
            self.assertLessEqual(float(ordered[-1] - ordered[0]), np.pi / 2)

    def test_model_rows_count_fitted_variance_in_information_criteria(self):
        camera = ExtendedBarghiniCamera.from_camera(self.baseline, [])
        sky = camera.to_sky(self.xy)
        models, _ = cross_validate_orders(
            camera, self.xy, sky, orders=[0], fold_count=8,
            bootstrap_replicates=20, max_nfev=100,
        )
        self.assertEqual(models[0]["camera_parameter_count"], 8)
        self.assertEqual(models[0]["information_parameter_count"], 9)
        self.assertEqual(models[0]["k"], 9)

    def test_cross_validation_never_fits_a_held_out_row(self):
        camera = ExtendedBarghiniCamera.from_camera(self.baseline, [])
        sky = camera.to_sky(self.xy)
        rng = np.random.default_rng(20260924)
        sky += rng.normal(0.0, 1.0e-7, sky.shape)
        sky /= np.linalg.norm(sky, axis=1)[:, None]
        calls = []

        def recording_fit(model, xy, sky, **kwargs):
            calls.append(np.asarray(xy).copy())
            return fit_extended_camera(model, xy, sky, **kwargs)

        with patch("radial_statistics.fit_extended_camera", side_effect=recording_fit):
            _, fold_rows = cross_validate_orders(
                camera,
                self.xy,
                sky,
                orders=[0],
                fold_count=8,
                bootstrap_replicates=200,
                max_nfev=300,
                include_indices=True,
            )

        # First call is the all-data fit. The remaining calls correspond to the
        # deterministic fold rows in order.
        self.assertEqual(len(calls), 9)
        for fitted_xy, row in zip(calls[1:], fold_rows, strict=True):
            held = self.xy[np.asarray(row["holdout_indices"], dtype=int)]
            self.assertFalse(any(np.all(point == held, axis=1).any() for point in fitted_xy))
            self.assertEqual(len(fitted_xy), row["training_count"])

    def test_production_fold_rows_hash_membership_without_copying_index_lists(self):
        camera = ExtendedBarghiniCamera.from_camera(self.baseline, [])
        sky = camera.to_sky(self.xy)
        _, fold_rows = cross_validate_orders(
            camera,
            self.xy,
            sky,
            orders=[0],
            fold_count=2,
            bootstrap_replicates=20,
            max_nfev=100,
        )
        for row in fold_rows:
            self.assertNotIn("training_indices", row)
            self.assertNotIn("holdout_indices", row)
            self.assertRegex(row["training_index_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["holdout_index_sha256"], r"^[0-9a-f]{64}$")

    def test_invalid_full_baseline_records_unevaluable_folds_without_refitting(self):
        camera = ExtendedBarghiniCamera.from_camera(self.baseline, [])
        sky = camera.to_sky(self.xy)
        calls = []

        def invalid_full_fit(model, xy, sky, **kwargs):
            calls.append(np.asarray(xy).copy())
            result = fit_extended_camera(model, xy, sky, **kwargs)
            result.success = False
            result.failure_reason = "inverse_domain"
            return result

        with patch("radial_statistics.fit_extended_camera", side_effect=invalid_full_fit):
            rows, fold_rows = cross_validate_orders(
                camera,
                self.xy,
                sky,
                orders=[0, 1],
                fold_count=2,
                bootstrap_replicates=20,
                max_nfev=100,
            )

        self.assertEqual(len(calls), 2)  # The two required all-data model fits only.
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(fold_rows), 4)
        self.assertTrue(all(not row["fit_valid"] for row in fold_rows))
        self.assertTrue(
            all(row["failure_reason"] == "baseline_full_fit_invalid" for row in fold_rows)
        )

    def test_known_m1_structure_is_supported_by_aic_and_blocked_validation(self):
        truth = ExtendedBarghiniCamera.from_camera(self.baseline, [0.04])
        sky = truth.to_sky(self.xy)
        rng = np.random.default_rng(122)
        sky += rng.normal(0.0, 2.0e-7, sky.shape)
        sky /= np.linalg.norm(sky, axis=1)[:, None]
        initial = ExtendedBarghiniCamera.from_camera(self.baseline, [])

        rows, _ = cross_validate_orders(
            initial,
            self.xy,
            sky,
            orders=[0, 1],
            fold_count=8,
            bootstrap_replicates=1000,
            seed=77,
            max_nfev=700,
        )

        by_order = {row["order"]: row for row in rows}
        self.assertLess(by_order[1]["delta_aicc"], -10.0)
        self.assertLess(by_order[1]["validation_delta_rms_arcmin"], 0.0)
        self.assertEqual(by_order[1]["classification"], "supported")
        self.assertEqual(select_supported_order(rows), 1)

    def test_baseline_noise_does_not_earn_an_extra_degree_of_freedom(self):
        truth = ExtendedBarghiniCamera.from_camera(self.baseline, [])
        sky = truth.to_sky(self.xy)
        rng = np.random.default_rng(814)
        sky += rng.normal(0.0, 2.0e-6, sky.shape)
        sky /= np.linalg.norm(sky, axis=1)[:, None]

        rows, fold_rows = cross_validate_orders(
            truth,
            self.xy,
            sky,
            orders=[0, 1],
            fold_count=8,
            bootstrap_replicates=500,
            seed=19,
            max_nfev=600,
        )

        extension = next(row for row in rows if row["order"] == 1)
        self.assertEqual(extension["classification"], "unsupported")
        extension_folds = [row for row in fold_rows if row["order"] == 1]
        self.assertTrue(
            all(
                row["failure_reason"] == "penalised_criteria_not_supported"
                for row in extension_folds
            )
        )
        self.assertIsNone(select_supported_order(rows))

    def test_classification_exposes_spatial_overfit(self):
        in_sample_only = classify_order(
            fit_valid=True,
            delta_aicc=-14.0,
            delta_bic=-3.0,
            validation_delta_rms_arcmin=-0.01,
            validation_ci_high=0.03,
        )
        worse = classify_order(
            fit_valid=True,
            delta_aicc=-14.0,
            delta_bic=-3.0,
            validation_delta_rms_arcmin=0.04,
            validation_ci_high=0.08,
        )
        self.assertEqual(in_sample_only, "in_sample_only")
        self.assertEqual(worse, "worse_prediction")

    def test_selection_prefers_smallest_supported_order_within_two_aicc(self):
        rows = [
            {"order": 1, "aicc": 92.0, "classification": "supported"},
            {"order": 2, "aicc": 90.5, "classification": "supported"},
            {"order": 3, "aicc": 88.0, "classification": "unsupported"},
        ]
        self.assertEqual(select_supported_order(rows), 1)


if __name__ == "__main__":
    unittest.main()
