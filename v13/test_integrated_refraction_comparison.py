import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np

from point_star_barghini import BarghiniCamera


SCRIPT = Path(__file__).parent / "scripts" / "compare_integrated_refraction.py"


def load_script():
    spec = importlib.util.spec_from_file_location("compare_integrated_refraction", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntegratedRefractionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.module = load_script()

    def test_full_fisheye_selector_uses_geometry_not_filename_metadata(self):
        rotation = np.eye(3)
        fisheye = BarghiniCamera.initial((1200, 1300), 320.0, rotation)
        narrow = BarghiniCamera.initial((1200, 1300), 1800.0, rotation)
        small = BarghiniCamera.initial((488, 652), 150.0, rotation)

        accepted = self.module.classify_fisheye_geometry(fisheye)
        rejected_narrow = self.module.classify_fisheye_geometry(narrow)
        rejected_small = self.module.classify_fisheye_geometry(small)

        self.assertTrue(accepted["accepted"])
        self.assertEqual(rejected_narrow["reason"], "insufficient_angular_coverage")
        self.assertEqual(rejected_small["reason"], "detector_too_small")

    def test_angular_blocks_are_deterministic_and_spatial(self):
        xy = np.array([[90., 50.], [50., 90.], [10., 50.], [50., 10.]])
        first = self.module.angular_block_ids(xy, (101, 101), 4)
        second = self.module.angular_block_ids(xy[::-1], (101, 101), 4)[::-1]
        np.testing.assert_array_equal(first, second)
        self.assertEqual(set(first), {0, 1, 2, 3})

    def test_compacted_database_products_are_exact_replay_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "stars.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE runs (run_id TEXT, result_json TEXT, source_path TEXT)"
                )
                connection.execute(
                    "CREATE TABLE products (run_id TEXT, product TEXT, content BLOB)"
                )
                connection.execute(
                    "INSERT INTO runs VALUES (?,?,?)",
                    ("run-1", '{"status":"point_star_fit_converged"}', "/input.fits"),
                )
                connection.execute(
                    "INSERT INTO products VALUES (?,?,?)",
                    ("run-1", "star_coordinates.csv", b"x_px,y_px\n1,2\n"),
                )
            result, coordinates, source = self.module._solution_bytes(
                f"sqlite:{database}#run-1"
            )
            self.assertEqual(result, b'{"status":"point_star_fit_converged"}')
            self.assertEqual(coordinates, b"x_px,y_px\n1,2\n")
            self.assertEqual(source, "/input.fits")

    def test_reports_rejections_and_failures_without_dropping_rows(self):
        rows = [
            {"family": "MMTO", "source_sha256": "a" * 64,
             "status": "adopted", "validation_improvement_fraction": .1,
             "baseline_rms_arcmin": 2., "selected_rms_arcmin": 1.8,
             "refraction_a_arcsec": 44., "refraction_b_arcsec": .1,
             "fitted_count": 100},
            {"family": "APICAM", "source_sha256": "b" * 64,
             "status": "rejected_small_field", "failure_reason": "detector_too_small"},
            {"family": "Subaru", "source_sha256": "c" * 64,
             "status": "failed", "failure_reason": "optimizer_failed"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            products = self.module.write_products(rows, output)
            with (output / "comparison.csv").open() as stream:
                saved = list(csv.DictReader(stream))
            summary = json.loads((output / "summary.json").read_text())
            report = (output / "report.md").read_text()

            self.assertEqual(len(saved), 3)
            self.assertEqual(summary["status_counts"]["failed"], 1)
            self.assertIn("optimizer_failed", report)
            self.assertIn("rejected_small_field", report)
            self.assertEqual(
                {path.name for path in products},
                {"comparison.csv", "summary.json", "report.md",
                 "integrated_refraction_comparison.png"},
            )
            self.assertTrue(all(path.is_file() for path in products))


if __name__ == "__main__":
    unittest.main()
