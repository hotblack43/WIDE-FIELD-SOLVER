import csv
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

import matplotlib.pyplot as plt
import numpy as np

from point_star_barghini import BarghiniCamera


SCRIPT = Path(__file__).parent / "scripts" / "compare_integrated_refraction.py"
REPORT_SCRIPT = Path(__file__).parent / "scripts" / "build_integrated_refraction_report.py"


def load_script(path=SCRIPT):
    spec = importlib.util.spec_from_file_location(path.stem, path)
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

    def test_illustrated_pdf_report_has_four_pages_and_refuses_overwrite(self):
        self.assertTrue(REPORT_SCRIPT.is_file(), "illustrated PDF report builder is missing")
        report_module = load_script(REPORT_SCRIPT)
        rows = [
            {"family": "MMTO", "status": "rejected_zero", "fitted_count": 302,
             "angular_diameter_deg": 167.4, "baseline_rms_arcmin": 2.26,
             "candidate_rms_arcmin": 1.74, "selected_rms_arcmin": 2.26,
             "refraction_a_arcsec": 180.0, "failure_reason": "physical_checks_failed"},
            {"family": "APICAM", "status": "rejected_zero", "fitted_count": 4712,
             "angular_diameter_deg": 172.7, "baseline_rms_arcmin": 1.68,
             "candidate_rms_arcmin": 2.03, "selected_rms_arcmin": 1.68,
             "refraction_a_arcsec": 0.0, "failure_reason": "physical_checks_failed"},
            {"family": "small-field control", "status": "rejected_small_field",
             "fitted_count": 122, "failure_reason": "detector_too_small"},
        ]
        summary = {
            "ordinary_least_squares_used": False,
            "row_count": len(rows),
            "status_counts": {"rejected_small_field": 1, "rejected_zero": 2},
            "rows": rows,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path = root / "summary.json"
            summary_path.write_text(json.dumps(summary))
            images = []
            for name, colour in (("comparison.png", (0.2, 0.4, 0.8)),
                                 ("overlay.png", (0.1, 0.7, 0.3)),
                                 ("residuals.png", (0.8, 0.3, 0.2))):
                path = root / name
                array = np.zeros((120, 180, 3), dtype=float)
                array[:, :] = colour
                plt.imsave(path, array)
                images.append(path)
            output = root / "integrated_refraction_report.pdf"

            created = report_module.write_report(
                summary_path, images[0], images[1], images[2], output
            )
            data = created.read_bytes()

            self.assertEqual(created, output)
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertEqual(len(re.findall(rb"/Type /Page\b", data)), 4)
            self.assertGreater(len(data), 10_000)
            with self.assertRaises(FileExistsError):
                report_module.write_report(
                    summary_path, images[0], images[1], images[2], output
                )


if __name__ == "__main__":
    unittest.main()
