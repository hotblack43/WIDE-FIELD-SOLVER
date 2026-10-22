"""Planet application status and preservation regressions."""
from __future__ import annotations

from dataclasses import replace
import math
from types import MappingProxyType
import unittest

import numpy as np

from v22.mmto_differential_data import (
    MeasurementSet,
    PlanetMeasurement,
    RunRecord,
    V21Control,
)
from v22.mmto_differential_features import ComparisonResidual, FeatureTable
from v22.mmto_differential_metrics import GateReport
from v22.mmto_differential_models import ConfirmedModel, FittedCandidate
from v22.mmto_planet_relative_photometry import apply_to_planets


class _Predictor:
    def predict(self, values):
        return np.full(len(values), 0.2)


class _OutOfDomain:
    def status(self, values):
        return tuple("out_of_domain" for _ in values)


def _run() -> RunRecord:
    return RunRecord(
        run_id="run",
        recorded_at_utc="2026-01-01T08:00:00+00:00",
        source_path="/image.fits",
        source_sha256="s" * 64,
        analysis_path="/analysis",
        solver_version="0.21.0",
        catalogue_sha256="c" * 64,
        observed_utc="2026-01-01T08:00:00+00:00",
        night="2025-12-31",
        width_px=1000,
        height_px=800,
        global_noise_adu=2.0,
        exposure_seconds=20.0,
    )


def _planet(**changes) -> PlanetMeasurement:
    values = dict(
        run_id="run",
        source_sha256="s" * 64,
        observed_utc="2026-01-01T08:00:00+00:00",
        night="2025-12-31",
        identity_type="major_planet",
        identity_name="Jupiter",
        identity_status="planet_candidate",
        candidate_rank=1,
        epoch_tdb="2026-01-01T00:00:00 TDB",
        detection_id="planet",
        channel="R",
        count_rate_adu_per_s=100.0,
        machine_magnitude=-5.0,
        x_px=500.0,
        y_px=400.0,
        image_width_px=1000,
        image_height_px=800,
        source_class="compact",
        exposure_seconds=20.0,
        flux_adu=2000.0,
        saturation_known=True,
        saturated=False,
        measurement_method="ordinary_aperture",
        area_px=20.0,
        major_sigma_px=1.5,
        axis_ratio=1.1,
        peak_snr=30.0,
        aperture_radius_px=3.75,
        aperture_background_adu=None,
        global_noise_adu=2.0,
        valid_measurement=True,
        exclusion_reasons=(),
    )
    values.update(changes)
    return PlanetMeasurement(**values)


def _context(comparison_count: int = 12) -> FeatureTable:
    run = _run()
    planet = _planet()
    data = MeasurementSet(
        runs=(run,),
        stellar=(),
        planets=(planet,),
        audit=(),
        database_path="/database",
        manifest_path="/manifest",
        database_sha256="d" * 64,
        manifest_sha256="m" * 64,
        input_solver_version="0.21.0",
    )
    control = V21Control(
        selected_run_ids=frozenset({"run"}),
        adopted_model="fixture",
        corrected_magnitudes=MappingProxyType({}),
        extinction_coefficients=MappingProxyType(
            {("2025-12-31", "R", "c" * 64): 0.2}
        ),
        manifest_sha256="1" * 64,
        corrected_photometry_sha256="2" * 64,
        coefficients_sha256="3" * 64,
    )
    residuals = tuple(
        ComparisonResidual(
            source_sha256=run.source_sha256,
            catalogue_sha256=run.catalogue_sha256,
            star_id=f"star-{index}",
            channel="R",
            x_px=490.0 + index,
            y_px=400.0,
            residual_magnitude=0.2,
        )
        for index in range(comparison_count)
    )
    return FeatureTable(
        rows=(),
        assignments=(),
        deployable_feature_names=("x_normalized",),
        diagnostic_feature_names=(),
        comparison_residuals=residuals,
        star_baselines=MappingProxyType({}),
        v21_baselines=MappingProxyType({}),
        data=data,
        control=control,
        config=MappingProxyType(
            {"minimum_local_comparisons": 12, "minimum_exposure_comparisons": 30}
        ),
    )


def _confirmed(name: str = "local_ensemble", *, out_of_domain: bool = False):
    candidate = FittedCandidate(
        name=name,
        feature_names=("x_normalized",),
        estimators=MappingProxyType({"R": _Predictor()} if name != "local_ensemble" else {}),
        support=MappingProxyType({"R": _OutOfDomain()} if out_of_domain else {}),
        prediction_intervals=MappingProxyType({}),
        support_medians=MappingProxyType({"R": np.array([0.0])} if name != "local_ensemble" else {}),
    )
    gate = GateReport(True, (), MappingProxyType({}), (), 0.0)
    return ConfirmedModel(name, candidate, gate, ())


class PlanetRelativePhotometryTests(unittest.TestCase):
    def test_corrected_local_planet_keeps_raw_and_v21_controls(self):
        result = apply_to_planets(
            _confirmed(), (_planet(),), _context()
        )[0]
        self.assertEqual(result.correction_status, "corrected")
        self.assertAlmostEqual(result.raw_machine_magnitude, -5.0)
        self.assertIsNotNone(result.v21_control_magnitude)
        self.assertAlmostEqual(result.v22_relative_magnitude, -5.2)
        self.assertEqual(result.distance_status, "distance_unavailable")

    def test_every_failure_status_retains_raw_and_v21_values(self):
        cases = (
            (None, _planet(), _context(), "model_unavailable"),
            (_confirmed(), _planet(), _context(comparison_count=3), "insufficient_local_stars"),
            (
                _confirmed(),
                _planet(
                    saturated=True,
                    valid_measurement=False,
                    exclusion_reasons=("channel_saturated",),
                ),
                _context(),
                "invalid_measurement",
            ),
            (
                _confirmed("random_forest", out_of_domain=True),
                _planet(),
                _context(),
                "out_of_domain",
            ),
        )
        for model, planet, context, expected in cases:
            with self.subTest(expected):
                result = apply_to_planets(model, (planet,), context)[0]
                self.assertEqual(result.correction_status, expected)
                self.assertEqual(result.raw_machine_magnitude, planet.machine_magnitude)
                self.assertIsNotNone(result.v21_control_magnitude)
                self.assertIsNone(result.v22_relative_magnitude)


if __name__ == "__main__":
    unittest.main()
