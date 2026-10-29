from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.controlled_cli import main
from find_planet.extract_controlled import ControlledExtractionError
from test_report_and_seal import sample_payload


class ControlledCliTests(unittest.TestCase):
    def test_help_and_required_input_validation(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        with tempfile.TemporaryDirectory() as directory:
            code = main([
                "--results-root", directory,
                "--run-id", "missing-inputs",
                "--audit", str(Path(directory) / "missing.csv"),
                "--database", str(Path(directory) / "missing.sqlite"),
            ])
            self.assertNotEqual(code, 0)
            self.assertFalse((Path(directory) / "missing-inputs" / "seal.json").exists())

    def test_fresh_run_separates_answer_key_and_anonymous_fit_input(self):
        extraction, fit, evaluation = sample_payload()
        observations = list(extraction["observations"])
        centroids = [row.direction for row in observations]
        audit_rows = [{"planet": "Mars", "answer_key_selection_status": "selected"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "audit.csv"
            database = root / "runs.sqlite"
            audit.write_text("fixture\n")
            database.write_bytes(b"fixture")
            arguments = [
                "--results-root", str(root / "results"), "--run-id", "controlled-test",
                "--audit", str(audit), "--audit-sha256", "fixture-hash",
                "--database", str(database), "--bootstrap-replicates", "1",
                "--maximum-seeds", "1",
            ]
            with (
                patch("find_planet.controlled_cli.select_answer_key_rows", return_value=(centroids, audit_rows)),
                patch("find_planet.controlled_cli.load_exact_receipts", return_value={}),
                patch("find_planet.controlled_cli.anonymous_direction_rows", return_value=[row.direction for row in observations]),
                patch("find_planet.controlled_cli.build_observations", return_value=observations),
                patch("find_planet.controlled_cli.evaluate_controlled", return_value=evaluation),
            ):
                self.assertEqual(main(arguments), 0)
            output = root / "results" / "controlled-test"
            self.assertTrue((output / "answer_key_selection.csv").exists())
            self.assertTrue((output / "observations.csv").exists())
            self.assertTrue((output / "seal.json").exists())
            summary = json.loads((output / "fit_summary.json").read_text())
            self.assertEqual(summary["scientific_status"], "not_predictive")
            manifest_text = (output / "fit_input_manifest.json").read_text().lower()
            self.assertNotIn("mars", manifest_text)
            self.assertNotIn("planet", manifest_text)
            self.assertNotIn("predicted", manifest_text)
            self.assertIn("object a", manifest_text)
            self.assertNotEqual(main(arguments), 0)

    def test_operational_error_is_nonzero_and_never_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "audit.csv"
            database = root / "runs.sqlite"
            audit.write_text("fixture\n")
            database.write_bytes(b"fixture")
            with patch(
                "find_planet.controlled_cli.select_answer_key_rows",
                side_effect=ControlledExtractionError("corrupt audit"),
            ):
                code = main([
                    "--results-root", str(root), "--run-id", "broken",
                    "--audit", str(audit), "--audit-sha256", "wrong",
                    "--database", str(database),
                ])
            self.assertNotEqual(code, 0)
            self.assertFalse((root / "broken" / "seal.json").exists())


if __name__ == "__main__":
    unittest.main()
