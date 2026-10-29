from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.evaluate import (
    BaselineModel,
    BootstrapResult,
    CovarianceResult,
    EvaluationResult,
    NightSplit,
    PredictionScore,
)
from find_planet.report import write_controlled_report
from find_planet.seal import seal_output, verify_seal
from find_planet.types import (
    AnonymousDirection,
    FitSeedAudit,
    HeliocentricState,
    Observation,
    ObservationFit,
    ObserverState,
    OrbitFitResult,
    OrbitSolution,
    OrbitalElements,
)


def sample_payload():
    epoch = 2461000.0
    state = HeliocentricState(epoch, (1.5, 0.2, 0.1), (-0.002, 0.013, 0.001))
    elements = OrbitalElements(epoch, 1.7, 0.2, 7.0, 30.0, 55.0, 80.0, ())
    observations = []
    residual_rows = []
    for index in range(5):
        unit = np.array([0.8, 0.2 + index * 0.002, 0.56])
        unit /= np.linalg.norm(unit)
        direction = AnonymousDirection(
            "Object A", f"run-{index}", f"sha-{index}", f"image-{index}.fits",
            f"2026-10-{index + 1:02d}", f"2026-10-{index + 1:02d}T02:00:00Z",
            f"d-{index}", 500.0 + index, 600.0 - index, tuple(unit), 1.2,
            "large", False, "accepted",
        )
        observer = ObserverState(epoch + index, (1.0, 0.0, 0.0), (0.0, 0.017, 0.0),
                                 (1.0, 0.0, 0.0), (0.0, 0.017, 0.0),
                                 (0.00004, 0.0, 0.0), (0.0, 0.0002, 0.0))
        observations.append(Observation(direction, epoch + index, tuple(unit), 1.2, observer))
        residual_rows.append(ObservationFit(f"run-{index}", 0.1 * index, -0.05 * index,
                                            0.12 * index, 1.2, 0.9, "used", ""))
    solution = OrbitSolution(state, elements, 1.5, True, tuple(residual_rows), 0,
                             tuple(tuple(float(v) for v in row) for row in np.eye(6)))
    fit = OrbitFitResult(epoch, (solution,), (FitSeedAudit(0, "accepted", "", 1.5),))
    split = NightSplit(tuple(observations[:4]), tuple(observations[4:]),
                       tuple(row.direction.night for row in observations[:4]),
                       (observations[4].direction.night,), 5)
    score = PredictionScore(("run-4",), (1.2,), (0.5,), 0.5, 0.5, 0.5, 0.2)
    baseline = BaselineModel("fixed_direction", epoch, tuple(observations[0].measured_unit))
    evaluation = EvaluationResult(
        split, 1.0, fit, {0.5: fit, 2.0: fit}, baseline,
        BaselineModel("angular_velocity", epoch, tuple(observations[0].measured_unit), 0.001, 0.0),
        {"orbit": score, "fixed_direction": score, "angular_velocity": score},
        CovarianceResult(True, 6, 6, np.eye(6), ""),
        BootstrapResult(17, 1, (("2026-10-01",),), ("accepted",), (state,)),
        "not_predictive", "held_out_orbit_did_not_beat_both_baselines",
    )
    extraction = {"observations": tuple(observations), "audit_rows": ({"status": "selected"},)}
    return extraction, fit, evaluation


class ReportAndSealTests(unittest.TestCase):
    def test_report_writes_declared_tables_figures_and_exact_plot_data(self):
        extraction, fit, evaluation = sample_payload()
        original_units = [row.measured_unit for row in extraction["observations"]]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            products = write_controlled_report(output, extraction, fit, evaluation)
            names = {path.name for path in products}
            required = {
                "orbit_sky_track.png", "orbit_residuals.png", "heliocentric_orbit.png",
                "observations.csv", "observation_audit.csv", "candidate_orbits.csv",
                "orbital_elements.csv", "covariance.csv", "bootstrap_elements.csv",
                "fit_summary.json", "fit_input_manifest.json", "figure_metadata.json",
                "orbit_sky_track_data.csv", "orbit_residuals_data.csv",
                "heliocentric_orbit_data.csv",
            }
            self.assertTrue(required <= names)
            self.assertTrue(all((output / name).stat().st_size > 0 for name in required))
            with (output / "observations.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            exported = [tuple(float(row[key]) for key in ("unit_x", "unit_y", "unit_z")) for row in rows]
            np.testing.assert_allclose(exported, original_units, atol=0.0)
            self.assertEqual([row.measured_unit for row in extraction["observations"]], original_units)
            metadata = json.loads((output / "figure_metadata.json").read_text())
            self.assertIn("ICRS", metadata["orbit_sky_track"]["frame"])
            self.assertIn("arcmin", metadata["orbit_residuals"]["y_units"])
            self.assertEqual(metadata["orbit_residuals"]["residual_magnification"], 1.0)
            summary = json.loads((output / "fit_summary.json").read_text())
            self.assertEqual(summary["scientific_status"], "not_predictive")

    def test_seal_hashes_every_product_and_detects_mutation(self):
        extraction, fit, evaluation = sample_payload()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            products = write_controlled_report(output, extraction, fit, evaluation)
            seal = seal_output(output, products, {"audit_sha256": "abc", "run_ids": "run-0"})
            verified = verify_seal(seal)
            self.assertTrue(verified.valid, verified.errors)
            manifest = json.loads(seal.read_text())
            self.assertEqual(set(manifest["products"]), {path.name for path in products})
            products[0].write_bytes(products[0].read_bytes() + b"changed")
            broken = verify_seal(seal)
            self.assertFalse(broken.valid)
            self.assertTrue(any("hash" in error for error in broken.errors))

    def test_unresolved_fit_remains_explicit_in_tables_and_figures(self):
        extraction, fit, evaluation = sample_payload()
        unresolved_fit = OrbitFitResult(fit.reference_jd_tdb, (), fit.seed_audit)
        unresolved = replace(
            evaluation,
            primary_fit=unresolved_fit,
            scores={**evaluation.scores, "orbit": None},
            covariance=CovarianceResult(False, 2, 6, None, "rank_deficient_jacobian"),
            scientific_status="unresolved",
            status_reason="no_admissible_orbit_family",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            products = write_controlled_report(output, extraction, unresolved_fit, unresolved)
            self.assertIn(output / "orbit_sky_track.png", products)
            self.assertIn(output / "orbit_residuals.png", products)
            self.assertIn(output / "heliocentric_orbit.png", products)
            summary = json.loads((output / "fit_summary.json").read_text())
            self.assertEqual(summary["scientific_status"], "unresolved")
            self.assertEqual(summary["orbit_family_count"], 0)
            covariance = (output / "covariance.csv").read_text()
            self.assertIn("rank_deficient_jacobian", covariance)


if __name__ == "__main__":
    unittest.main()
