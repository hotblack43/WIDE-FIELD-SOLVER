"""Validation-gate regressions for v22 differential photometry."""
from __future__ import annotations

import unittest

import numpy as np

from v22.mmto_differential_metrics import (
    PredictionRow,
    TrainingSupport,
    _bootstrap_slope_interval,
    empirical_prediction_interval,
    evaluate_gate,
)


def _predictions(*, weak_channel: str | None = None, trend: bool = False):
    rows = []
    for channel_index, channel in enumerate("RGB"):
        for group in range(30):
            nuisance = (group - 14.5) / 10.0
            raw = nuisance
            v21 = nuisance * 0.8
            corrected = nuisance * (0.79 if channel == weak_channel else 0.1)
            diagnostic = nuisance if trend else (group % 5) - 2.0
            rows.append(
                PredictionRow(
                    row_index=len(rows),
                    channel=channel,
                    target_group=f"{channel}-{group}",
                    observed_magnitude=raw,
                    raw_control_magnitude=raw,
                    v21_control_magnitude=v21,
                    predicted_nuisance=raw - corrected,
                    corrected_magnitude=corrected,
                    status="corrected",
                    diagnostic_features=(diagnostic,),
                    planet_like=True,
                )
            )
    return tuple(rows)


class DifferentialMetricTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "improvement_fraction": 0.05,
            "maximum_planet_stratum_degradation_fraction": 0.02,
            "maximum_signal_attenuation_fraction": 0.05,
            "bootstrap_resamples": 300,
            "bootstrap_seed": 2203,
        }

    def test_every_channel_must_improve_over_both_controls(self):
        passed = evaluate_gate(
            _predictions(),
            self.config,
            diagnostic_feature_names=("diagnostic",),
            signal_attenuations=(0.0, 0.01),
        )
        self.assertTrue(passed.passed, passed.failures)
        failed = evaluate_gate(
            _predictions(weak_channel="G"),
            self.config,
            diagnostic_feature_names=("diagnostic",),
            signal_attenuations=(0.0,),
        )
        self.assertFalse(failed.passed)
        self.assertTrue(any("G" in reason for reason in failed.failures))

    def test_bootstrap_improvement_is_positive_and_signal_loss_is_bounded(self):
        report = evaluate_gate(
            _predictions(),
            self.config,
            diagnostic_feature_names=("diagnostic",),
            signal_attenuations=(0.0, 0.02, 0.04),
        )
        for channel in "RGB":
            self.assertGreater(report.by_channel[channel].bootstrap_lower_improvement, 0.0)
        attenuated = evaluate_gate(
            _predictions(),
            self.config,
            diagnostic_feature_names=("diagnostic",),
            signal_attenuations=(0.01, 0.08, 0.09),
        )
        self.assertIn("signal_attenuation", attenuated.failures)

    def test_significant_control_trend_must_be_reduced(self):
        report = evaluate_gate(
            _predictions(trend=True),
            self.config,
            diagnostic_feature_names=("airmass",),
            signal_attenuations=(0.0,),
        )
        self.assertTrue(report.passed, report.failures)
        self.assertLess(
            abs(report.trends[0].corrected_slope),
            0.95 * abs(report.trends[0].v21_slope),
        )

    def test_training_support_rejects_univariate_and_multivariate_extrapolation(self):
        rng = np.random.default_rng(1)
        training = rng.normal(size=(500, 2))
        support = TrainingSupport.fit(training)
        statuses = support.status(np.array([[0.0, 0.0], [20.0, 0.0], [3.0, 3.0]]))
        self.assertEqual(statuses[0], "supported")
        self.assertEqual(statuses[1], "out_of_domain")
        self.assertEqual(statuses[2], "out_of_domain")

    def test_empirical_interval_uses_grouped_validation_residuals(self):
        interval = empirical_prediction_interval(
            residuals=np.array([-2.0, -1.0, 0.0, 1.0, 2.0]),
            groups=np.array(["a", "a", "b", "c", "c"]),
            coverage=0.90,
        )
        self.assertLess(interval[0], 0.0)
        self.assertGreater(interval[1], 0.0)

    def test_grouped_slope_bootstrap_preserves_reference_result(self):
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        y = np.array([1.0, 1.5, 2.2, 2.9, 4.1, 5.2, 5.8])
        groups = np.array(["a", "a", "b", "b", "c", "c", "c"])
        interval = _bootstrap_slope_interval(
            x, y, groups, resamples=50, seed=17
        )
        self.assertAlmostEqual(interval[0], 0.6317073170731708)
        self.assertAlmostEqual(interval[1], 0.9510416666666672)


if __name__ == "__main__":
    unittest.main()
