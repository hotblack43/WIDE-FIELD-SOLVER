"""Behavioral tests for the v23 aperture-radius experiment."""
from __future__ import annotations

import unittest
from pathlib import Path
import subprocess
import csv
import json
import tempfile


class ApertureGeometryTests(unittest.TestCase):
    def test_annulus_summary_keeps_control_and_best_of_each_family(self):
        from v23.mmto_aperture_radius_benchmark import annulus_summary_names

        metrics = []
        for name, values in (
            ("scaled_4.00_gap_3_width_4", (0.31, 0.22, 0.33)),
            ("scaled_4.00_gap_3_width_3", (0.30, 0.21, 0.32)),
            ("scaled_4.00_gap_5_width_8", (0.34, 0.24, 0.36)),
            ("scaled_4.00_gap_2.0sigma_width_3.0sigma", (0.29, 0.20, 0.31)),
            ("scaled_4.00_gap_3.0sigma_width_4.0sigma", (0.35, 0.25, 0.37)),
        ):
            metrics.extend(
                {"geometry": name, "channel": channel,
                 "robust_sigma_mag": value}
                for channel, value in zip("RGB", values)
            )
        self.assertEqual(
            annulus_summary_names(metrics, "scaled_4.00_gap_3_width_4"),
            (
                "scaled_4.00_gap_3_width_4",
                "scaled_4.00_gap_3_width_3",
                "scaled_4.00_gap_2.0sigma_width_3.0sigma",
            ),
        )

    def test_final_comparison_keeps_rejected_candidate_visible(self):
        from v23.mmto_aperture_radius_benchmark import final_comparison_names

        metrics = [
            {"geometry": "current_scaled_2.50"},
            {"geometry": "scaled_4.00_gap_3_width_4"},
        ]
        self.assertEqual(
            final_comparison_names(metrics),
            ("current_scaled_2.50", "scaled_4.00_gap_3_width_4"),
        )

    def test_current_geometry_reproduces_v22_radius_and_annulus(self):
        from v23.mmto_aperture_radius_benchmark import current_geometry

        geometry = current_geometry()
        self.assertEqual(geometry.aperture_radius(1.0), 3.0)
        self.assertEqual(geometry.aperture_radius(2.0), 5.0)
        self.assertEqual(geometry.aperture_radius(8.0), 9.0)
        self.assertEqual(geometry.annulus_radii(2.0), (8.0, 12.0))

    def test_grid_compares_fixed_and_scaled_apertures_without_duplicates(self):
        from v23.mmto_aperture_radius_benchmark import candidate_geometries

        geometries = candidate_geometries()
        names = [geometry.name for geometry in geometries]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("current_scaled_2.50", names)
        self.assertIn("fixed_4.00", names)
        self.assertIn("scaled_3.00", names)
        self.assertTrue(all(outer > inner > 0 for geometry in geometries
                            for inner, outer in [geometry.annulus_radii(1.5)]))

    def test_scaled_annulus_moves_farther_from_larger_blobs(self):
        from v23.mmto_aperture_radius_benchmark import (
            annulus_geometries, current_geometry,
        )

        geometry = next(
            item for item in annulus_geometries(current_geometry())
            if "gap_2.0sigma_width_3.0sigma" in item.name
        )
        small_aperture = geometry.aperture_radius(1.0)
        large_aperture = geometry.aperture_radius(3.0)
        small_inner, small_outer = geometry.annulus_radii(1.0)
        large_inner, large_outer = geometry.annulus_radii(3.0)
        self.assertEqual(small_inner - small_aperture, 2.0)
        self.assertEqual(large_inner - large_aperture, 6.0)
        self.assertEqual(small_outer - small_inner, 3.0)
        self.assertEqual(large_outer - large_inner, 9.0)


class RadiusSelectionTests(unittest.TestCase):
    def test_followup_on_opened_test_nights_cannot_adopt_candidate(self):
        from v23.mmto_aperture_radius_benchmark import adoption_decision

        selection = {
            "status": "selected",
            "selected_geometry": "scaled_4.00_gap_2.0sigma_width_3.0sigma",
            "control_geometry": "current_scaled_2.50",
        }
        guarded = adoption_decision(selection, reused_opened_test_nights=True)
        self.assertEqual(guarded["status"],
                         "requires_new_independent_confirmation")
        self.assertEqual(guarded["proposed_geometry"],
                         selection["selected_geometry"])
        self.assertEqual(guarded["adopted_geometry"],
                         "current_scaled_2.50")

    def test_selector_requires_improvement_in_every_channel(self):
        from v23.mmto_aperture_radius_benchmark import select_geometry

        metrics = [
            {"geometry": "current_scaled_2.50", "channel": channel,
             "robust_sigma_mag": 0.100, "trend_gate_passed": True,
             "usable_rows": 1000}
            for channel in "RGB"
        ]
        metrics += [
            {"geometry": "fixed_4.00", "channel": channel,
             "robust_sigma_mag": sigma, "trend_gate_passed": True,
             "usable_rows": 1000}
            for channel, sigma in zip("RGB", (0.070, 0.070, 0.110))
        ]
        selection = select_geometry(metrics, minimum_gain_fraction=0.02)
        self.assertEqual(selection["selected_geometry"], "current_scaled_2.50")
        self.assertEqual(selection["status"], "no_candidate_passed")

    def test_selector_chooses_simplest_rule_with_equivalent_scatter(self):
        from v23.mmto_aperture_radius_benchmark import select_geometry

        metrics = []
        for name, sigma in (("current_scaled_2.50", 0.100),
                            ("scaled_3.00", 0.0795),
                            ("fixed_4.00", 0.0800)):
            metrics.extend(
                {"geometry": name, "channel": channel,
                 "robust_sigma_mag": sigma, "trend_gate_passed": True,
                 "usable_rows": 1000}
                for channel in "RGB"
            )
        selection = select_geometry(
            metrics, minimum_gain_fraction=0.02, equivalence_fraction=0.01)
        self.assertEqual(selection["status"], "selected")
        self.assertEqual(selection["selected_geometry"], "fixed_4.00")

    def test_selector_rejects_new_residual_trend(self):
        from v23.mmto_aperture_radius_benchmark import select_geometry

        metrics = []
        for channel in "RGB":
            metrics.append(
                {"geometry": "current_scaled_2.50", "channel": channel,
                 "robust_sigma_mag": 0.100, "trend_gate_passed": True,
                 "usable_rows": 1000})
            metrics.append(
                {"geometry": "fixed_4.00", "channel": channel,
                 "robust_sigma_mag": 0.070,
                 "trend_gate_passed": channel != "B", "usable_rows": 1000})
        selection = select_geometry(metrics, minimum_gain_fraction=0.02)
        self.assertEqual(selection["selected_geometry"], "current_scaled_2.50")


class HeldOutScoringTests(unittest.TestCase):
    def test_sampled_night_count_uses_measurement_rows(self):
        from v23.mmto_aperture_radius_benchmark import sampled_night_count

        rows = [
            {"night": "2026-01-01", "run_id": "one"},
            {"night": "2026-01-01", "run_id": "two"},
            {"night": "2026-01-02", "run_id": "three"},
        ]
        self.assertEqual(sampled_night_count(rows), 2)

    def test_night_roles_are_deterministic_and_disjoint(self):
        from v23.mmto_aperture_radius_benchmark import assign_night_roles

        nights = [f"2026-07-{day:02d}" for day in range(1, 11)]
        first = assign_night_roles(nights)
        second = assign_night_roles(reversed(nights))
        self.assertEqual(first, second)
        self.assertEqual(list(first.values()).count("train"), 6)
        self.assertEqual(list(first.values()).count("validation"), 2)
        self.assertEqual(list(first.values()).count("test"), 2)

    def test_scoring_removes_grey_image_terms_but_retains_star_specific_error(self):
        from v23.mmto_aperture_radius_benchmark import score_geometry

        rows = []
        for role, run_id, grey, differential in (
                ("train", "train-1", 0.0, 0.0),
                ("train", "train-2", 0.3, 0.0),
                ("validation", "valid-1", 1.0, 0.2),
                ("validation", "valid-2", -0.5, -0.2)):
            for star_id, baseline in (("A", 10.0), ("B", 11.0), ("C", 12.0)):
                star_error = differential if star_id == "A" else 0.0
                rows.append({
                    "role": role, "run_id": run_id, "star_id": star_id,
                    "channel": "R", "catalogue_magnitude": 5.0,
                    "major_sigma_px": 1.5, "field_radius_fraction": 0.4,
                    "airmass": 1.2, "geometry": baseline + grey + star_error,
                })
        score = score_geometry(rows, "geometry", evaluation_role="validation")
        self.assertEqual(score["usable_rows"], 6)
        self.assertGreater(score["robust_sigma_mag"], 0.0)
        self.assertLess(score["robust_sigma_mag"], 0.25)

    def test_scoring_never_learns_a_star_baseline_from_validation(self):
        from v23.mmto_aperture_radius_benchmark import score_geometry

        rows = [
            {"role": "train", "run_id": "t", "star_id": "A", "channel": "R",
             "catalogue_magnitude": 5.0, "major_sigma_px": 1.0,
             "field_radius_fraction": 0.2, "airmass": 1.0, "geometry": 10.0},
            {"role": "validation", "run_id": "v", "star_id": "A", "channel": "R",
             "catalogue_magnitude": 5.0, "major_sigma_px": 1.0,
             "field_radius_fraction": 0.2, "airmass": 1.0, "geometry": 10.0},
            {"role": "validation", "run_id": "v", "star_id": "B", "channel": "R",
             "catalogue_magnitude": 5.0, "major_sigma_px": 1.0,
             "field_radius_fraction": 0.2, "airmass": 1.0, "geometry": 20.0},
        ]
        score = score_geometry(rows, "geometry", evaluation_role="validation")
        self.assertEqual(score["usable_rows"], 1)
        self.assertEqual(score["stars_without_train_baseline"], 1)

    def test_trend_gate_compares_candidate_to_control(self):
        from v23.mmto_aperture_radius_benchmark import apply_trend_gates

        metrics = []
        for name, trend in (("current_scaled_2.50", 0.010),
                            ("fixed_4.00", 0.030)):
            for channel in "RGB":
                metrics.append({
                    "geometry": name, "channel": channel,
                    "robust_sigma_mag": 0.1, "usable_rows": 100,
                    "magnitude_trend_mag": 0.005,
                    "psf_width_trend_mag": trend,
                    "field_radius_trend_mag": 0.005,
                    "airmass_trend_mag": 0.005,
                })
        gated = apply_trend_gates(metrics, control_name="current_scaled_2.50")
        candidate = [row for row in gated if row["geometry"] == "fixed_4.00"]
        self.assertTrue(candidate)
        self.assertTrue(all(not row["trend_gate_passed"] for row in candidate))


class PhotometryMeasurementTests(unittest.TestCase):
    def test_annulus_geometry_changes_background_without_changing_aperture(self):
        import numpy as np
        from v23.point_star_photometry import measure_channel

        yy, xx = np.mgrid[:41, :41]
        radius = np.hypot(xx - 20.0, yy - 20.0)
        pixels = np.full((41, 41), 100.0)
        pixels[radius <= 2.0] += 1000.0
        pixels[(radius >= 5.0) & (radius <= 7.0)] += 30.0
        valid = np.ones_like(pixels, dtype=bool)
        saturated = np.zeros_like(pixels, dtype=bool)

        contaminated = measure_channel(
            pixels, valid, saturated, x=20.0, y=20.0,
            aperture_radius=2.0, annulus_inner_radius=5.0,
            annulus_outer_radius=7.0)
        clean = measure_channel(
            pixels, valid, saturated, x=20.0, y=20.0,
            aperture_radius=2.0, annulus_inner_radius=9.0,
            annulus_outer_radius=12.0)
        self.assertLess(contaminated["aperture_counts_adu"],
                        clean["aperture_counts_adu"])
        self.assertEqual(clean["annulus_inner_radius_px"], 9.0)
        self.assertEqual(clean["annulus_outer_radius_px"], 12.0)


class ApertureBenchmarkCliTests(unittest.TestCase):
    def test_launcher_exposes_bounded_native_fits_sweep(self):
        root = Path(__file__).resolve().parent
        completed = subprocess.run(
            [str(root / "run_v23_aperture_radius_benchmark.sh"), "--help"],
            cwd=Path("/tmp"), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("--maximum-runs-per-night", completed.stdout)
        self.assertIn("--maximum-stars", completed.stdout)
        self.assertIn("--reuse-aperture-run", completed.stdout)

    def test_reuse_loader_requires_matching_input_paths_and_aperture_columns(self):
        from v23.mmto_aperture_radius_benchmark import load_reused_aperture_rows

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "benchmark_summary.json").write_text(json.dumps({
                "database": "/data/stars.sqlite",
                "manifest": "/data/manifest.sqlite",
                "v21_control": "/data/control",
            }))
            with (directory / "radius_measurements.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=(
                    "role", "night", "run_id", "source_sha256", "star_id",
                    "detection_id", "channel", "catalogue_magnitude",
                    "major_sigma_px", "field_radius_fraction", "airmass",
                    "x_px", "y_px", "exposure_seconds", "saved_machine_magnitude",
                    "current_scaled_2.50",
                ))
                writer.writeheader()
                writer.writerow({
                    "role": "train", "night": "2026-01-01", "run_id": "run-1",
                    "source_sha256": "a" * 64, "star_id": "star", "detection_id": "1",
                    "channel": "R", "catalogue_magnitude": "2.0",
                    "major_sigma_px": "1.5", "field_radius_fraction": "0.4",
                    "airmass": "1.2", "x_px": "10", "y_px": "11",
                    "exposure_seconds": "20", "saved_machine_magnitude": "-4",
                    "current_scaled_2.50": "-4.1",
                })
            rows = load_reused_aperture_rows(
                directory,
                database=Path("/data/stars.sqlite"),
                manifest=Path("/data/manifest.sqlite"),
                v21_control=Path("/data/control"),
                aperture_names=("current_scaled_2.50",),
            )
            self.assertEqual(rows[0]["major_sigma_px"], 1.5)
            self.assertEqual(rows[0]["current_scaled_2.50"], -4.1)


if __name__ == "__main__":
    unittest.main()
