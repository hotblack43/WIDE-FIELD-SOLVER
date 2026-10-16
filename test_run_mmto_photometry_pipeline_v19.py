"""V19 adds one variable-star stage while retaining v16 pipeline behavior."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from scripts.run_mmto_photometry_pipeline_v16 import _stage_commands as v16_stage_commands
from scripts.run_mmto_photometry_pipeline_v19 import (
    SOLVER_LAUNCHER,
    SOLVER_VERSION,
    _stage_commands,
    build_processing_plan,
    main,
)


def _manifest(path: Path, rows: list[tuple[object, ...]]) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            """
            CREATE TABLE downloads (
                remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                observed_utc TEXT, local_path TEXT, observed_bytes INTEGER,
                sha256 TEXT, download_status TEXT, validation_status TEXT
            )
            """
        )
        database.executemany("INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)", rows)


def _results_database(path: Path, receipts: list[tuple[str, str]]) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TABLE runs (source_sha256 TEXT, solver_version TEXT, "
            "exit_code INTEGER, source_manifest_json TEXT)"
        )
        database.executemany(
            "INSERT INTO runs VALUES (?,?,0,?)",
            [(digest, version, json.dumps({"version": version})) for digest, version in receipts],
        )


def _fake_stage(path: Path, *, fail: int = 0, pdf: bool = False) -> None:
    body = """#!/usr/bin/env bash
set -euo pipefail
out=''
while [[ $# -gt 0 ]]; do
  if [[ "$1" == '--output' ]]; then out="$2"; shift 2; else shift; fi
done
mkdir -p "$out"
"""
    if pdf:
        body += "printf '%s' '%PDF-1.4 fake' > \"$out/variable_star_time_series.pdf\"\n"
    body += f"exit {fail}\n"
    path.write_text(body)
    path.chmod(0o755)


class MmtoV19PipelineTests(unittest.TestCase):
    def test_default_variable_star_stage_uses_catalogue_magnitude_below_five(self):
        stages = _stage_commands(
            Path("/repository"),
            Path("/results/stars.sqlite"),
            Path("/archive/manifest.sqlite"),
            Path("/output"),
        )

        variable = stages[2][1]
        self.assertEqual(
            variable[variable.index("--max-catalogue-magnitude") + 1], "5.0"
        )

    def test_only_added_stage_differs_from_v16_and_receives_controls(self):
        root = Path("/repository")
        database = Path("/results/stars.sqlite")
        manifest = Path("/archive/manifest.sqlite")
        output = Path("/output")
        stages = _stage_commands(
            root, database, manifest, output,
            variable_min_period_days=7.5,
            variable_max_period_days=23.5,
            variable_max_catalogue_magnitude=5.25,
            variable_start_utc="2026-07-01T00:00:00Z",
        )
        inherited = [stage for stage in stages if stage[0] != "variable_star_time_series"]

        self.assertEqual(inherited, list(v16_stage_commands(root, database, manifest, output)))
        self.assertEqual(
            [name for name, _ in stages],
            ["stellar_lightcurves", "nightly_extinction", "variable_star_time_series", "planet_photometry", "planet_empirical_extinction"],
        )
        variable = stages[2][1]
        self.assertEqual(variable[0], str(root / "plot_mmto_variable_stars_v19.sh"))
        self.assertEqual(variable[variable.index("--min-period-days") + 1], "7.5")
        self.assertEqual(variable[variable.index("--max-period-days") + 1], "23.5")
        self.assertEqual(
            variable[variable.index("--max-catalogue-magnitude") + 1], "5.25"
        )
        self.assertEqual(variable[variable.index("--start-utc") + 1], "2026-07-01T00:00:00Z")

    def test_processing_plan_accepts_only_v19_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            rows = []
            for index, name in enumerate(("v16", "v19"), 1):
                digest = hashlib.sha256(name.encode()).hexdigest()
                rows.append((
                    f"https://mmto/{name}", "mmto", "mmto-skycam",
                    f"2026-08-01T0{index}:00:00Z", f"night/{name}.fits",
                    index, digest, "downloaded", "verified",
                ))
            _manifest(archive / "manifest.sqlite", rows)
            results = root / "stars.sqlite"
            _results_database(results, [(rows[0][6], "0.16.0"), (rows[1][6], "0.19.0")])

            plan = build_processing_plan(archive, results)

        self.assertEqual(SOLVER_VERSION, "0.19.0")
        self.assertEqual(SOLVER_LAUNCHER, "go19.sh")
        self.assertEqual([row.local_path.name for row in plan.pending], ["v16.fits"])
        self.assertEqual(plan.skipped_solver_receipts, 1)

    def test_complete_run_records_added_output_and_lists_its_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            archive.mkdir()
            results.mkdir()
            _manifest(archive / "manifest.sqlite", [])
            _results_database(results / "stars.sqlite", [])
            for name in (
                "plot_mmto_lightcurves.sh", "calibrate_mmto_extinction.sh",
                "plot_ALL_planets.sh", "plot_planet_empirical_extinction.sh",
            ):
                _fake_stage(root / name)
            _fake_stage(root / "plot_mmto_variable_stars_v19.sh", pdf=True)
            output = root / "run"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "--repo-root", str(root), "--archive", str(archive),
                    "--results-dir", str(results), "--output", str(output),
                    "--lock-file", str(root / "lock"),
                ])
            summary = json.loads((output / "pipeline_summary.json").read_text())

        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["outputs"]["variable_star_time_series"], str(output / "variable-stars"))
        self.assertEqual([row["name"] for row in summary["stages"]][2], "variable_star_time_series")
        self.assertIn(str(output / "variable-stars" / "variable_star_time_series.pdf"), stdout.getvalue())

    def test_added_stage_failure_is_an_operational_pipeline_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            archive.mkdir()
            results.mkdir()
            _manifest(archive / "manifest.sqlite", [])
            _results_database(results / "stars.sqlite", [])
            for name in (
                "plot_mmto_lightcurves.sh", "calibrate_mmto_extinction.sh",
                "plot_ALL_planets.sh", "plot_planet_empirical_extinction.sh",
            ):
                _fake_stage(root / name)
            _fake_stage(root / "plot_mmto_variable_stars_v19.sh", fail=7)
            output = root / "run"
            code = main([
                "--repo-root", str(root), "--archive", str(archive),
                "--results-dir", str(results), "--output", str(output),
                "--lock-file", str(root / "lock"),
            ])
            summary = json.loads((output / "pipeline_summary.json").read_text())

        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "operational_failed")
        self.assertEqual(summary["stages"][-1], {"name": "variable_star_time_series", "exit_code": 7})

    def test_portable_launcher_help_exposes_v19_controls_and_backfill(self):
        launcher = Path(__file__).resolve().parent / "go_mmto_photometry_v19.sh"
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [str(launcher), "--help"], cwd=temporary,
                env=dict(os.environ, VIRTUAL_ENV="/tmp/wrong-environment"),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("--backfill-v19", completed.stdout)
        self.assertIn("--variable-min-period-days", completed.stdout)
        self.assertIn("--variable-max-period-days", completed.stdout)
        self.assertIn("--variable-max-catalogue-magnitude", completed.stdout)
        self.assertIn("--variable-start-utc", completed.stdout)
        self.assertNotIn("does not match the project environment", completed.stdout)


if __name__ == "__main__":
    unittest.main()
