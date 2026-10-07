"""The versioned MMTO pipeline selects v14 without changing the v11 pipeline."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout

from scripts.run_mmto_photometry_pipeline_v14 import (
    SOLVER_LAUNCHER,
    SOLVER_VERSION,
    build_processing_plan,
    main,
)


class MmtoV14PipelineTests(unittest.TestCase):
    def test_normal_plan_uses_newest_incomplete_v14_night_then_moves_backward(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                        observed_utc TEXT, local_path TEXT, observed_bytes INTEGER,
                        sha256 TEXT, download_status TEXT, validation_status TEXT
                    )
                    """
                )
                rows = []
                for index, name in enumerate(("old", "v11", "v14", "new"), 1):
                    digest = hashlib.sha256(name.encode()).hexdigest()
                    night = "2026-07-31" if name == "old" else "2026-08-01"
                    rows.append((
                        f"https://mmto/{name}", "mmto", "mmto-skycam",
                        f"{night}T0{index}:00:00Z",
                        f"mmto/mmto-skycam/{night}/{name}.fits", index,
                        digest, "downloaded", "verified",
                    ))
                database.executemany("INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)", rows)
            results = root / "stars.sqlite"
            with sqlite3.connect(results) as database:
                database.execute(
                    "CREATE TABLE runs (source_sha256 TEXT, solver_version TEXT, "
                    "exit_code INTEGER, source_manifest_json TEXT)"
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    [
                        (rows[1][6], "0.11.0", 0, '{"version":"0.11.0"}'),
                        (rows[2][6], "0.14.0", 0, '{"version":"0.14.0"}'),
                    ],
                )

            plan = build_processing_plan(archive, results)

            self.assertEqual(SOLVER_VERSION, "0.14.0")
            self.assertEqual(SOLVER_LAUNCHER, "go14.sh")
            self.assertEqual(plan.skipped_solver_receipts, 1)
            self.assertEqual(
                [row.local_path.name for row in plan.pending],
                ["v11.fits", "new.fits"],
            )
            self.assertEqual(
                plan.selected_night.as_posix(), "mmto/mmto-skycam/2026-08-01"
            )

            with sqlite3.connect(results) as database:
                database.executemany(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    [
                        (rows[1][6], "0.14.0", 0, '{"version":"0.14.0"}'),
                        (rows[3][6], "0.14.0", 0, '{"version":"0.14.0"}'),
                    ],
                )

            next_plan = build_processing_plan(archive, results)
            self.assertEqual(
                next_plan.selected_night.as_posix(),
                "mmto/mmto-skycam/2026-07-31",
            )
            self.assertEqual(
                [row.local_path.name for row in next_plan.pending], ["old.fits"]
            )

    def test_versioned_launcher_is_portable_and_keeps_old_launcher(self):
        root = Path(__file__).resolve().parent
        old = root / "go_mmto_photometry.sh"
        launcher = root / "go_mmto_photometry_v14.sh"
        self.assertTrue(old.is_file())
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [str(launcher), "--help"],
                cwd=temporary,
                env=dict(os.environ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("v14", completed.stdout)
        self.assertIn("--dry-run", completed.stdout)

    def test_backfill_flag_requires_v14_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                        observed_utc TEXT, local_path TEXT, observed_bytes INTEGER,
                        sha256 TEXT, download_status TEXT, validation_status TEXT
                    )
                    """
                )
                rows = []
                for index, name in enumerate(("old", "v11", "v14", "new"), 1):
                    digest = hashlib.sha256(name.encode()).hexdigest()
                    night = "2026-07-31" if name == "old" else "2026-08-01"
                    rows.append((
                        f"https://mmto/{name}", "mmto", "mmto-skycam",
                        f"{night}T0{index}:00:00Z",
                        f"mmto/mmto-skycam/{night}/{name}.fits", index,
                        digest, "downloaded", "verified",
                    ))
                database.executemany("INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)", rows)
            results_dir = root / "results"
            results_dir.mkdir()
            with sqlite3.connect(results_dir / "stars.sqlite") as database:
                database.execute(
                    "CREATE TABLE runs (source_sha256 TEXT, solver_version TEXT, "
                    "exit_code INTEGER, source_manifest_json TEXT)"
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    [
                        (rows[1][6], "0.11.0", 0, '{"version":"0.11.0"}'),
                        (rows[2][6], "0.14.0", 0, '{"version":"0.14.0"}'),
                    ],
                )

            output = io.StringIO()
            with redirect_stdout(output):
                return_code = main([
                    "--archive", str(archive),
                    "--results-dir", str(results_dir),
                    "--dry-run",
                    "--backfill-v14",
                ])

            self.assertEqual(return_code, 0)
            self.assertIn("verified=4 skipped_v14=1 pending=3", output.getvalue())
            self.assertIn("2026-07-31/old.fits", output.getvalue())
            self.assertIn("2026-08-01/v11.fits", output.getvalue())
            self.assertIn("2026-08-01/new.fits", output.getvalue())


if __name__ == "__main__":
    unittest.main()
