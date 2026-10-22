"""Focused integration tests for the v22 MMTO pipeline."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_mmto_photometry_pipeline_v22 as pipeline


class V22PipelineTest(unittest.TestCase):
    def test_differential_benchmark_runs_after_raw_planet_products(self):
        root = Path("/repo")
        database = Path("/results/stars.sqlite")
        manifest = Path("/archive/manifest.sqlite")
        output = Path("/output")

        stages = pipeline._stage_commands(root, database, manifest, output)
        names = [name for name, _ in stages]
        self.assertGreater(
            names.index("differential_photometry"), names.index("planet_photometry")
        )
        command = dict(stages)["differential_photometry"]
        self.assertEqual(command[0], "/repo/run_v22_photometry_benchmark.sh")
        self.assertEqual(command[command.index("--database") + 1], str(database))
        self.assertEqual(command[command.index("--manifest") + 1], str(manifest))
        self.assertEqual(
            command[command.index("--v21-control") + 1],
            "/output/nightly-extinction",
        )
        self.assertEqual(
            command[command.index("--output") + 1],
            "/output/differential-photometry",
        )

    def test_failed_scientific_gate_is_recorded_without_operational_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            benchmark = output / "differential-photometry"
            benchmark.mkdir()
            figure = benchmark / "model_comparison.pdf"
            figure.write_bytes(b"%PDF-1.4\n")
            (benchmark / "benchmark_summary.json").write_text(
                json.dumps(
                    {
                        "selected_method": "raw_baseline",
                        "correction_available": False,
                        "validation_gate": {"passed": False},
                        "final_test_gate": {"passed": False},
                        "figures": [figure.name],
                    }
                ),
                encoding="utf-8",
            )
            summary = {"status": "running", "outputs": {}}

            pipeline._record_differential_benchmark(output, summary)

        self.assertEqual(summary["status"], "running")
        recorded = summary["differential_photometry"]
        self.assertEqual(recorded["selected_method"], "raw_baseline")
        self.assertFalse(recorded["correction_available"])
        self.assertFalse(recorded["validation_gate"]["passed"])
        self.assertEqual(recorded["figures"], [str(figure.resolve())])


if __name__ == "__main__":
    unittest.main()
