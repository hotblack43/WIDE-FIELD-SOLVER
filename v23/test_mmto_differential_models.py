"""Candidate-model and simplest-winner regressions for v23."""
from __future__ import annotations

import math
from types import MappingProxyType
import unittest
from unittest.mock import patch

from v23.mmto_differential_features import FeatureRow, FeatureTable
from v23.mmto_differential_metrics import GateReport, PredictionRow
from v23.mmto_differential_models import (
    FittedCandidate,
    ValidationResult,
    candidate_specs,
    confirm_on_test,
    final_test_evaluation_count,
    fit_and_validate_candidates,
    local_ensemble_prediction,
    measure_signal_recovery,
    reset_final_test_evaluation_count,
    select_simplest_passing,
)


def _row(**changes) -> FeatureRow:
    values = dict(
        run_id="run",
        source_sha256="s" * 64,
        observed_utc="2026-01-01T00:00:00+00:00",
        night="2026-01-01",
        catalogue_sha256="c" * 64,
        star_id="star",
        channel="R",
        role="validation",
        night_role="validation",
        star_role="train",
        spatial_block="1:1",
        target_delta_magnitude=0.2,
        metric_target_magnitude=0.2,
        raw_control_magnitude=0.2,
        v21_control_magnitude=0.18,
        deployable_features=(0.0,),
        diagnostic_features=(0.0,),
        exposure_median_magnitude=0.4,
        exposure_mad_magnitude=0.1,
        exposure_count=40,
        local_median_128_px=0.1,
        local_mad_128_px=0.01,
        local_count_128_px=12,
        local_median_256_px=0.2,
        local_mad_256_px=0.02,
        local_count_256_px=20,
        local_median_512_px=0.3,
        local_mad_512_px=0.03,
        local_count_512_px=30,
    )
    values.update(changes)
    return FeatureRow(**values)


def _gate(passed: bool) -> GateReport:
    return GateReport(
        passed=passed,
        failures=() if passed else ("fixture_failure",),
        by_channel=MappingProxyType({}),
        trends=(),
        median_signal_attenuation=0.0,
    )


def _validation(name: str, passed: bool) -> ValidationResult:
    return ValidationResult(
        name=name,
        metrics=_gate(passed),
        gate_status="passed" if passed else "failed",
        fitted_pipeline=FittedCandidate(
            name=name,
            feature_names=("x",),
            estimators=MappingProxyType({}),
            support=MappingProxyType({}),
            prediction_intervals=MappingProxyType({}),
        ),
        validation_predictions=(),
    )


class DifferentialModelTests(unittest.TestCase):
    def test_signal_recovery_is_measured_from_candidate_predictions(self):
        rows = tuple(
            _row(
                observed_utc=f"2026-01-0{index + 1}T00:00:00+00:00",
                night=f"2026-01-0{index + 1}",
                target_delta_magnitude=0.1 * index,
            )
            for index in range(4)
        )
        table = FeatureTable(
            rows=rows,
            assignments=(),
            deployable_feature_names=("x",),
            diagnostic_feature_names=("diagnostic",),
            comparison_residuals=(),
            star_baselines=MappingProxyType({}),
            v21_baselines=MappingProxyType({}),
            data=None,
            control=None,
            config=MappingProxyType({}),
        )
        candidate = _validation("local_ensemble", True).fitted_pipeline

        def erase_signal(_candidate, measured, _config, _ranges=None):
            return tuple(
                PredictionRow(
                    row_index=index,
                    channel=row.channel,
                    target_group="group",
                    observed_magnitude=row.target_delta_magnitude,
                    raw_control_magnitude=row.raw_control_magnitude,
                    v21_control_magnitude=row.v21_control_magnitude,
                    predicted_nuisance=row.target_delta_magnitude,
                    corrected_magnitude=0.0,
                    status="corrected",
                    diagnostic_features=row.diagnostic_features,
                    planet_like=True,
                )
                for index, row in enumerate(measured)
            )

        with patch("v23.mmto_differential_models._predictions", side_effect=erase_signal):
            recovered = measure_signal_recovery(
                candidate, table, "validation", {"seed_signals": 2202}
            )
        attenuations = [
            row.attenuation_fraction
            for row in recovered
            if math.isfinite(row.attenuation_fraction)
        ]
        self.assertTrue(attenuations)
        self.assertTrue(all(value == 1.0 for value in attenuations))

    def test_local_ensemble_uses_smallest_supported_radius_then_exposure(self):
        self.assertEqual(local_ensemble_prediction(_row())[0], 0.1)
        row = _row(local_count_128_px=11)
        self.assertEqual(local_ensemble_prediction(row)[0], 0.2)
        row = _row(local_count_128_px=0, local_count_256_px=0, local_count_512_px=0)
        self.assertEqual(local_ensemble_prediction(row)[0], 0.4)
        row = _row(
            local_count_128_px=0,
            local_count_256_px=0,
            local_count_512_px=0,
            exposure_count=29,
        )
        prediction, status = local_ensemble_prediction(row)
        self.assertTrue(math.isnan(prediction))
        self.assertEqual(status, "insufficient_local_stars")

    def test_default_model_specs_match_the_frozen_comparison(self):
        specs = candidate_specs({})
        self.assertEqual([spec.name for spec in specs], [
            "local_ensemble", "random_forest", "gradient_boosting", "neural_network"
        ])
        self.assertEqual(specs[1].parameters["n_estimators"], 300)
        self.assertEqual(specs[1].parameters["max_features"], 0.7)
        self.assertEqual(specs[1].parameters["min_samples_leaf"], (8, 20))
        self.assertEqual(specs[2].parameters["max_iter"], 300)
        self.assertEqual(specs[2].parameters["learning_rate"], 0.05)
        self.assertEqual(specs[3].parameters["max_iter"], 500)
        self.assertTrue(specs[3].parameters["early_stopping"])

    def test_all_four_adapters_fit_without_opening_test_rows(self):
        rows = []
        for channel in "RGB":
            for night_index in range(6):
                role = "train" if night_index < 4 else "validation"
                for star_index in range(10):
                    nuisance = (night_index - 2.5) / 5.0 + (star_index - 4.5) / 50.0
                    rows.append(
                        _row(
                            run_id=f"run-{night_index}",
                            source_sha256=f"{night_index:064x}",
                            observed_utc=f"2026-01-{night_index + 1:02d}T00:00:00+00:00",
                            night=f"2026-01-{night_index + 1:02d}",
                            star_id=f"star-{star_index}",
                            channel=channel,
                            role=role,
                            night_role=role,
                            target_delta_magnitude=nuisance,
                            metric_target_magnitude=nuisance,
                            raw_control_magnitude=nuisance,
                            v21_control_magnitude=0.9 * nuisance,
                            deployable_features=(nuisance, float(star_index) / 10.0),
                            diagnostic_features=(nuisance,),
                            local_median_128_px=nuisance,
                        )
                    )
        table = FeatureTable(
            rows=tuple(rows),
            assignments=(),
            deployable_feature_names=("context", "position"),
            diagnostic_feature_names=("diagnostic",),
            comparison_residuals=(),
            star_baselines=MappingProxyType({}),
            v21_baselines=MappingProxyType({}),
            data=None,
            control=None,
            config=MappingProxyType({}),
        )
        results = fit_and_validate_candidates(
            table,
            {
                "random_forest_trees": 5,
                "random_forest_min_samples_leaf": [2],
                "gradient_boosting_iterations": 5,
                "gradient_boosting_leaf_counts": [3],
                "mlp_hidden_layers": [[4]],
                "mlp_alpha": [0.001],
                "mlp_max_iterations": 20,
                "maximum_tuning_rows_per_channel": 100,
                "maximum_training_rows_per_channel": 100,
                "bootstrap_resamples": 20,
            },
        )
        self.assertEqual([result.name for result in results], [
            "local_ensemble", "random_forest", "gradient_boosting", "neural_network"
        ])
        self.assertTrue(all(not result.fitted_pipeline.test_evaluated for result in results))
        for result in results[1:]:
            self.assertEqual(set(result.fitted_pipeline.estimators), set("RGB"))

    def test_simplest_passing_model_wins_without_test_reselection(self):
        reset_final_test_evaluation_count()
        results = (
            _validation("local_ensemble", False),
            _validation("random_forest", True),
            _validation("gradient_boosting", True),
        )
        selected = select_simplest_passing(results)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, "random_forest")
        self.assertIsNone(confirm_on_test(selected, None, {"force_test_failure": True}))
        self.assertEqual(final_test_evaluation_count(), 1)
        with self.assertRaisesRegex(RuntimeError, "already evaluated"):
            confirm_on_test(selected, None, {"force_test_failure": True})


if __name__ == "__main__":
    unittest.main()
