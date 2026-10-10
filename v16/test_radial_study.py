"""Saved-solution and edge-yield tests for the radial comparison study."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from point_star_barghini import BarghiniCamera
from radial_model import ExtendedBarghiniCamera
from radial_study import (
    AssociationCatalogue,
    SolutionData,
    SolutionRecord,
    StudyConfig,
    _load_checkpoint,
    _write_checkpoint,
    compare_associations,
    compare_planet_residuals,
    compare_solution,
    discover_solutions,
    load_solution,
)
from radial_statistics import cross_validate_orders as real_cross_validate_orders


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def coordinate_rows(*, propagated: bool = True) -> list[dict[str, object]]:
    rows = []
    for index in range(24):
        row = {
            "detection_id": str(index),
            "star_id": f"star-{index}",
            "catalog_ra_deg": 20.0 + index * 0.01,
            "catalog_dec_deg": -5.0 + index * 0.005,
            "x_px": 100.0 + index * 7.0,
            "y_px": 120.0 + index * 5.0,
            "usage": "fitted",
        }
        if propagated:
            row["propagated_ra_deg"] = 20.001 + index * 0.01
            row["propagated_dec_deg"] = -4.999 + index * 0.005
        rows.append(row)
    return rows


class SolutionDiscoveryTests(unittest.TestCase):
    def make_solution(
        self,
        root: Path,
        name: str,
        *,
        source_hash: str,
        version: str,
        status: str = "point_star_fit_converged",
        propagated: bool = True,
        mtime: int = 100,
    ) -> Path:
        folder = root / name
        folder.mkdir()
        camera = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        result = {
            "status": status,
            "solver_version": version,
            "source": f"/archive/night/image_{source_hash[-2:]}.fits",
            "source_sha256": source_hash,
            "catalogue_sha256": "c" * 64,
            "camera": camera.serialise(),
            "fit": {"count": 24, "rms_px": 0.4},
            "stellar_epoch": {"applied_epoch_jyear": 2018.5},
            "association": {"final_gate_arcmin": 8.1},
        }
        path = folder / "result.json"
        path.write_text(json.dumps(result))
        write_csv(folder / "star_coordinates.csv", coordinate_rows(propagated=propagated))
        os.utime(path, (mtime, mtime))
        return path

    def test_selects_one_success_per_source_and_audits_every_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_a = "a" * 64
            source_b = "b" * 64
            old = self.make_solution(
                root, "a-old", source_hash=source_a, version="0.10.0", mtime=400
            )
            chosen_a = self.make_solution(
                root, "a-new", source_hash=source_a, version="0.11.0", mtime=200
            )
            self.make_solution(
                root,
                "a-failed-newer",
                source_hash=source_a,
                version="0.13.0",
                status="failed",
                mtime=900,
            )
            tie_a = self.make_solution(
                root, "b-tie-a", source_hash=source_b, version="0.11.0", mtime=300
            )
            tie_z = self.make_solution(
                root, "b-tie-z", source_hash=source_b, version="0.11.0", mtime=300
            )
            malformed = root / "malformed"
            malformed.mkdir()
            (malformed / "result.json").write_text("{bad json")

            selected, inventory = discover_solutions([root])

            self.assertEqual(len(inventory), 6)
            self.assertEqual(len(selected), 2)
            chosen = {record.source_sha256: record.path for record in selected}
            self.assertEqual(chosen[source_a], chosen_a.resolve())
            self.assertEqual(chosen[source_b], max(tie_a.resolve(), tie_z.resolve()))
            reasons = {Path(row["path"]).parent.name: row["reason"] for row in inventory}
            self.assertEqual(reasons[old.parent.name], "shadowed_duplicate")
            self.assertEqual(reasons["a-failed-newer"], "unsuccessful_status")
            self.assertEqual(reasons["malformed"], "malformed_json")
            self.assertEqual(sum(row["selected"] for row in inventory), 2)

    def test_load_uses_propagated_coordinates_and_labels_catalogue_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            propagated = self.make_solution(
                root,
                "propagated",
                source_hash="1" * 64,
                version="0.11.0",
                propagated=True,
            )
            fallback = self.make_solution(
                root,
                "fallback",
                source_hash="2" * 64,
                version="0.11.0",
                propagated=False,
            )
            selected, _ = discover_solutions([propagated, fallback])
            loaded = {item.record.source_sha256: item for item in map(load_solution, selected)}

            self.assertEqual(loaded["1" * 64].coordinate_source, "propagated")
            self.assertEqual(loaded["2" * 64].coordinate_source, "catalogue_fallback")
            self.assertEqual(loaded["1" * 64].xy.shape, (24, 2))
            self.assertEqual(loaded["1" * 64].sky.shape, (24, 3))
            self.assertEqual(loaded["1" * 64].epoch_jyear, 2018.5)
            self.assertEqual(loaded["1" * 64].association_gate_arcmin, 8.1)
            self.assertTrue(loaded["1" * 64].source_group.startswith("800x1000|"))

    def test_missing_saved_association_gate_is_not_replaced_by_a_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.make_solution(
                root, "missing-gate", source_hash="3" * 64, version="0.11.0"
            )
            record = json.loads(path.read_text())
            record.pop("association")
            path.write_text(json.dumps(record))
            selected, _ = discover_solutions([path])
            loaded = load_solution(selected[0])
            self.assertIsNone(loaded.association_gate_arcmin)


class AssociationYieldTests(unittest.TestCase):
    def setUp(self):
        base = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        self.baseline = ExtendedBarghiniCamera.from_camera(base, [])
        self.selected = ExtendedBarghiniCamera.from_camera(base, [0.012])
        self.detections = [
            {"detection_id": "common", "x_px": 499.5, "y_px": 399.5},
            {"detection_id": "gain", "x_px": 900.0, "y_px": 400.0},
            {"detection_id": "loss", "x_px": 100.0, "y_px": 400.0},
            {"detection_id": "change", "x_px": 500.0, "y_px": 730.0},
            {"detection_id": "unmatched", "x_px": 500.0, "y_px": 100.0},
        ]
        xy = np.array([[row["x_px"], row["y_px"]] for row in self.detections])
        base_sky = self.baseline.to_sky(xy)
        selected_sky = self.selected.to_sky(xy)
        rows = [
            {"star_id": "same"},
            {"star_id": "new-edge"},
            {"star_id": "old-edge"},
            {"star_id": "old-identity"},
            {"star_id": "new-identity"},
        ]
        sky = np.array(
            [base_sky[0], selected_sky[1], base_sky[2], base_sky[3], selected_sky[3]]
        )
        self.catalogue = AssociationCatalogue(
            rows=rows,
            sky=sky,
            sha256="c" * 64,
            epoch_jyear=2018.5,
        )

    def test_classifies_gain_loss_identity_change_and_common_matches(self):
        rows = compare_associations(
            self.baseline,
            self.selected,
            self.detections,
            self.catalogue,
            5.0,
            expected_catalogue_sha256="c" * 64,
            saved_gate_arcmin=5.0,
        )

        self.assertEqual(len(rows), len(self.detections))
        outcome = {row["detection_id"]: row for row in rows}
        self.assertEqual(outcome["common"]["outcome"], "common")
        self.assertEqual(outcome["gain"]["outcome"], "gained")
        self.assertEqual(outcome["loss"]["outcome"], "lost")
        self.assertEqual(outcome["change"]["outcome"], "changed")
        self.assertEqual(outcome["unmatched"]["outcome"], "unmatched")
        self.assertEqual(outcome["change"]["baseline_star_id"], "old-identity")
        self.assertEqual(outcome["change"]["selected_star_id"], "new-identity")
        self.assertGreater(outcome["gain"]["normalised_radius"], 0.5)
        self.assertEqual(outcome["gain"]["radial_bin"], "0.50-0.75")
        self.assertEqual({row["detection_count"] for row in rows}, {5})
        self.assertEqual({row["gate_arcmin"] for row in rows}, {5.0})

    def test_requires_exact_catalogue_checksum_and_saved_gate(self):
        with self.assertRaisesRegex(ValueError, "catalogue checksum"):
            compare_associations(
                self.baseline,
                self.selected,
                self.detections,
                self.catalogue,
                5.0,
                expected_catalogue_sha256="d" * 64,
                saved_gate_arcmin=5.0,
            )
        with self.assertRaisesRegex(ValueError, "saved association gate"):
            compare_associations(
                self.baseline,
                self.selected,
                self.detections,
                self.catalogue,
                4.9,
                expected_catalogue_sha256="c" * 64,
                saved_gate_arcmin=5.0,
            )


class SolutionComparisonTests(unittest.TestCase):
    def test_orchestration_keeps_failed_orders_and_runs_robust_edge_comparison(self):
        base = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        base.p[6] = 0.06
        base.p[7] = 1.1
        truth = ExtendedBarghiniCamera.from_camera(base, [0.04])
        centre = np.array([499.5, 399.5])
        xy = []
        for sector in range(8):
            angle = (sector + 0.2) * np.pi / 4.0
            for radius in np.linspace(70.0, 490.0, 8):
                xy.append(centre + radius * np.array([np.cos(angle), np.sin(angle)]))
        xy = np.asarray(xy)
        sky = truth.to_sky(xy)
        detections = [
            {"detection_id": str(index), "x_px": point[0], "y_px": point[1]}
            for index, point in enumerate(xy)
        ]
        catalogue = AssociationCatalogue(
            rows=[{"star_id": f"star-{index}"} for index in range(len(xy))],
            sky=sky,
            sha256="c" * 64,
            epoch_jyear=2018.5,
        )
        saved = {
            "source": "/archive/night/image_001.fits",
            "source_sha256": "a" * 64,
            "catalogue_sha256": "c" * 64,
            "association": {"final_gate_arcmin": 8.1},
            "camera": base.serialise(),
        }
        record = SolutionRecord(
            path=Path("/synthetic/result.json"),
            source_sha256="a" * 64,
            solver_version="0.11.0",
            version_key=(0, 11, 0),
            mtime_ns=0,
            result=saved,
        )
        solution = SolutionData(
            record=record,
            camera=base,
            xy=xy,
            sky=sky,
            coordinate_rows=[],
            coordinate_source="propagated",
            epoch_jyear=2018.5,
            association_gate_arcmin=8.1,
            source_group="800x1000|synthetic",
            detections=detections,
            association_catalogue=catalogue,
        )

        def comparison_with_failed_m2(*args, **kwargs):
            kwargs["orders"] = [0, 1]
            models, folds = real_cross_validate_orders(*args, **kwargs)
            failed = dict(models[-1])
            failed.update(
                order=2,
                fit_valid=False,
                valid=False,
                failure_reason="injected_high_order_failure",
                reason="injected_high_order_failure",
                classification="failed",
                aic=None,
                aicc=None,
                bic=None,
                delta_aicc=None,
                delta_bic=None,
                akaike_weight=None,
            )
            models.append(failed)
            for fold in range(8):
                folds.append(
                    {
                        "order": 2,
                        "fold": fold,
                        "fit_valid": False,
                        "failure_reason": "injected_high_order_failure",
                        "training_count": 56,
                        "holdout_count": 8,
                    }
                )
            return models, folds

        with patch("radial_study.cross_validate_orders", side_effect=comparison_with_failed_m2):
            result = compare_solution(
                solution,
                StudyConfig(
                    max_order=2,
                    fold_count=8,
                    bootstrap_replicates=500,
                    seed=12,
                    max_nfev=700,
                ),
            )

        self.assertEqual([row["order"] for row in result.model_rows], [0, 1, 2])
        self.assertEqual(len(result.fold_rows), 24)
        self.assertEqual(result.model_rows[2]["classification"], "failed")
        self.assertEqual(result.selected_order, 1)
        self.assertTrue(result.robust_baseline.success)
        self.assertTrue(result.robust_selected.success)
        self.assertEqual(len(result.association_rows), len(detections))
        self.assertIsNone(result.association_failure_reason)
        self.assertEqual(result.operational_row["selected_order"], 1)
        self.assertIn("robust_baseline_camera", result.operational_row)
        self.assertIn("robust_selected_radial_coefficients", result.operational_row)


class PlanetEdgeTests(unittest.TestCase):
    def test_fixed_major_and_minor_candidates_keep_identity_epoch_and_failures_visible(self):
        base = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        baseline = ExtendedBarghiniCamera.from_camera(base, [])
        selected = ExtendedBarghiniCamera.from_camera(base, [0.012])
        mars_xy = np.array([[900.0, 400.0]])
        ceres_xy = np.array([[100.0, 400.0]])
        expected_vectors = {
            "mars": selected.to_sky(mars_xy),
            "ceres": baseline.to_sky(ceres_xy),
        }
        candidates = [
            {
                "planet": "Mars",
                "epoch_tdb": "2020-01-02T03:04:05.353 TDB",
                "detection_id": "major-edge",
                "measured_x_px": 900.0,
                "measured_y_px": 400.0,
            },
            {
                "planet": "Ceres",
                "epoch_tdb": "2021-06-07T08:09:10",
                "detection_id": "minor-edge",
                "measured_x_px": 100.0,
                "measured_y_px": 400.0,
            },
        ]
        calls = []

        def fixed_vectors(name, jd_tdb):
            calls.append((name, np.asarray(jd_tdb).copy()))
            return expected_vectors[name]

        with patch("radial_study.planet_vectors", side_effect=fixed_vectors):
            rows = compare_planet_residuals(
                baseline, selected, candidates, gate=5.0
            )

        self.assertEqual(len(rows), 2)
        by_id = {row["detection_id"]: row for row in rows}
        mars = by_id["major-edge"]
        ceres = by_id["minor-edge"]
        self.assertEqual(mars["planet"], "Mars")
        self.assertEqual(mars["epoch_tdb"], "2020-01-02T03:04:05.353 TDB")
        self.assertEqual(mars["identity_type"], "major_planet")
        self.assertEqual(mars["classification"], "improved")
        self.assertEqual(mars["gate_crossing"], "outside_to_inside")
        self.assertGreater(mars["normalised_radius"], 0.5)
        self.assertLess(mars["selected_separation_px"], 1e-7)
        self.assertEqual(ceres["planet"], "Ceres")
        self.assertEqual(ceres["epoch_tdb"], "2021-06-07T08:09:10")
        self.assertEqual(ceres["identity_type"], "minor_planet")
        self.assertEqual(ceres["classification"], "worsened")
        self.assertEqual(ceres["gate_crossing"], "inside_to_outside")
        self.assertGreater(ceres["selected_separation_arcmin"], 5.0)
        self.assertEqual([name for name, _ in calls], ["mars", "ceres"])
        self.assertTrue(all(values.shape == () for _, values in calls))

    def test_missing_planet_gate_keeps_residuals_but_not_gate_classification(self):
        base = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        baseline = ExtendedBarghiniCamera.from_camera(base, [])
        selected = ExtendedBarghiniCamera.from_camera(base, [0.012])
        xy = np.array([[900.0, 400.0]])
        candidate = [{
            "planet": "Mars", "epoch_tdb": "2020-01-02T03:04:05",
            "detection_id": "edge", "measured_x_px": 900.0,
            "measured_y_px": 400.0,
        }]
        with patch("radial_study.planet_vectors", return_value=selected.to_sky(xy)):
            rows = compare_planet_residuals(baseline, selected, candidate, gate=None)
        self.assertEqual(rows[0]["gate_crossing"], "gate_unavailable")
        self.assertIsNone(rows[0]["gate_arcmin"])
        self.assertIsNone(rows[0]["baseline_inside_gate"])
        self.assertIsNone(rows[0]["selected_inside_gate"])


class RadialStudyCliTests(unittest.TestCase):
    def test_cli_publishes_complete_stable_auditable_outputs(self):
        from scripts.compare_radial_models import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            solutions = root / "solutions"
            valid = solutions / "valid"
            malformed = solutions / "malformed"
            (valid / "dots").mkdir(parents=True)
            malformed.mkdir(parents=True)
            (malformed / "result.json").write_text("{broken")

            base = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
            base.p[6] = 0.06
            base.p[7] = 1.1
            truth = ExtendedBarghiniCamera.from_camera(base, [0.04])
            centre = np.array([499.5, 399.5])
            xy = []
            for sector in range(8):
                angle = (sector + 0.2) * np.pi / 4.0
                for radius in np.linspace(70.0, 490.0, 8):
                    xy.append(centre + radius * np.array([np.cos(angle), np.sin(angle)]))
            xy = np.asarray(xy)
            sky = truth.to_sky(xy)
            ra = np.rad2deg(np.mod(np.arctan2(sky[:, 1], sky[:, 0]), 2 * np.pi))
            dec = np.rad2deg(np.arcsin(sky[:, 2]))
            catalogue_rows = [
                {
                    "star_id": f"star-{index:03d}",
                    "ra_deg": ra[index],
                    "dec_deg": dec[index],
                    "mag": 5.0,
                    "reference_epoch_jyear": 2018.5,
                    "pm_ra_cosdec_mas_per_year": 0.0,
                    "pm_dec_mas_per_year": 0.0,
                }
                for index in range(len(xy))
            ]
            catalogue_path = root / "catalogue.csv"
            write_csv(catalogue_path, catalogue_rows)
            catalogue_hash = hashlib.sha256(catalogue_path.read_bytes()).hexdigest()
            coordinates = [
                {
                    "detection_id": str(index),
                    "star_id": f"star-{index:03d}",
                    "catalog_ra_deg": ra[index],
                    "catalog_dec_deg": dec[index],
                    "propagated_ra_deg": ra[index],
                    "propagated_dec_deg": dec[index],
                    "x_px": xy[index, 0],
                    "y_px": xy[index, 1],
                    "usage": "fitted",
                }
                for index in range(len(xy))
            ]
            write_csv(valid / "star_coordinates.csv", coordinates)
            detections = [
                {
                    "detection_id": str(index),
                    "x_px": xy[index, 0],
                    "y_px": xy[index, 1],
                }
                for index in range(len(xy))
            ]
            write_csv(valid / "dots/star_candidates.csv", detections)
            planet_rows = [
                {
                    "planet": "Mars",
                    "epoch_tdb": "2020-01-02T03:04:05",
                    "detection_id": "8",
                    "measured_x_px": xy[8, 0],
                    "measured_y_px": xy[8, 1],
                },
                {
                    "planet": "Ceres",
                    "epoch_tdb": "2021-06-07T08:09:10",
                    "detection_id": "56",
                    "measured_x_px": xy[56, 0],
                    "measured_y_px": xy[56, 1],
                },
            ]
            write_csv(valid / "planet_candidates.csv", planet_rows)
            (valid / "planet_epoch.json").write_text(json.dumps({"gate_arcmin": 5.0}))
            source_hash = "a" * 64
            result = {
                "status": "point_star_fit_converged",
                "solver_version": "0.11.0",
                "source": "/archive/night/image_001.fits",
                "source_sha256": source_hash,
                "catalogue_sha256": catalogue_hash,
                "camera": base.serialise(),
                "fit": {"count": len(xy), "rms_px": 1.0},
                "stellar_epoch": {"applied_epoch_jyear": 2018.5},
                "association": {"final_gate_arcmin": 8.1},
            }
            (valid / "result.json").write_text(json.dumps(result))
            expected_planets = {
                "mars": truth.to_sky(xy[8:9]),
                "ceres": ExtendedBarghiniCamera.from_camera(base, []).to_sky(xy[56:57]),
            }
            output = root / "study"

            with patch(
                "radial_study.planet_vectors",
                side_effect=lambda name, epoch: expected_planets[name],
            ):
                status = main(
                    [
                        str(solutions),
                        "--catalogue",
                        str(catalogue_path),
                        "--output",
                        str(output),
                        "--workers",
                        "1",
                        "--max-order",
                        "1",
                        "--fold-count",
                        "4",
                        "--bootstrap-replicates",
                        "300",
                        "--seed",
                        "27",
                    ]
                )

            self.assertEqual(status, 0)
            required = {
                "solution_inventory.csv",
                "model_comparison.csv",
                "validation_folds.csv",
                "association_yield.csv",
                "planet_residual_comparison.csv",
                "operational_comparison.csv",
                "radial_model_study.json",
                "summary.md",
                "radial_profiles.png",
                "fit_vs_validation.png",
                "information_criteria.png",
                "failure_counts.png",
            }
            self.assertTrue(required <= {path.name for path in output.iterdir()})
            with (output / "solution_inventory.csv").open() as stream:
                inventory = list(csv.DictReader(stream))
            self.assertEqual([row["path"] for row in inventory], sorted(row["path"] for row in inventory))
            self.assertEqual(len(inventory), 2)
            self.assertEqual(
                next(row for row in inventory if "malformed" in row["path"])["reason"],
                "malformed_json",
            )
            with (output / "model_comparison.csv").open() as stream:
                models = list(csv.DictReader(stream))
            self.assertEqual([row["order"] for row in models], ["0", "1"])
            self.assertTrue(
                {"source_sha256", "source_group", "order", "aicc", "bic", "classification"}
                <= set(models[0])
            )
            with (output / "planet_residual_comparison.csv").open() as stream:
                planets = list(csv.DictReader(stream))
            self.assertEqual(len(planets), 2)
            self.assertEqual({row["classification"] for row in planets}, {"improved", "worsened"})
            with (output / "operational_comparison.csv").open() as stream:
                operational = list(csv.DictReader(stream))
            self.assertEqual(len(operational), 1)
            self.assertEqual(operational[0]["association_gate_arcmin"], "8.1")
            self.assertTrue(operational[0]["robust_selected_camera"])
            payload = json.loads((output / "radial_model_study.json").read_text())
            self.assertEqual(payload["configuration"]["seed"], 27)
            self.assertEqual(payload["provenance"]["solver_version"], "0.16.0")
            summary = (output / "summary.md").read_text()
            self.assertIn("already-detected sources", summary)
            self.assertIn("not newly detected", summary)
            for name in required:
                path = output / name
                self.assertGreater(path.stat().st_size, 0, name)


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_round_trip_is_signature_guarded_and_json_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.json"
            payload = {
                "source_sha256": "a" * 64,
                "model_rows": [{"order": 0, "score": float("inf")}],
            }
            _write_checkpoint(path, "signature-one", payload=payload, failure=None)

            restored = _load_checkpoint(path, "signature-one")

            self.assertEqual(restored["payload"]["source_sha256"], "a" * 64)
            self.assertIsNone(restored["payload"]["model_rows"][0]["score"])
            self.assertIsNone(restored["failure"])
            self.assertIsNone(_load_checkpoint(path, "signature-two"))
            path.write_text("{broken")
            self.assertIsNone(_load_checkpoint(path, "signature-one"))


if __name__ == "__main__":
    unittest.main()
