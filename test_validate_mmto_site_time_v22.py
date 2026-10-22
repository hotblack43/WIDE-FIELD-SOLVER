from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class ValidateMMTOSiteTimeV22Tests(unittest.TestCase):
    def _databases(self, root: Path):
        digest = "1" * 64
        results = root / "stars.sqlite"
        manifest = root / "manifest.sqlite"
        with sqlite3.connect(results) as db:
            db.executescript(
                """
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY, source_sha256 TEXT,
                    exit_code INTEGER, solver_version TEXT
                );
                CREATE TABLE products (run_id TEXT, product TEXT, content BLOB);
                """
            )
            zenith = json.dumps({"status": "conditional_zenith", "zenith_unit_vector": [0, 0, 1], "metadata_used": False})
            science = json.dumps({"stellar_epoch": {"status": "conditional_epoch", "epoch_jyear": 2026.5}})
            planets = json.dumps({"status": "planet_epoch_ambiguous", "metadata_used": False, "candidates": [{"jd_tdb": 2461302.598, "epoch_tdb": "2026-09-19T02:21:00 TDB"}]})
            coordinates = "detection_id,measured_ra_deg,measured_dec_deg\n1,0,31.6866666667\n"
            photometry = "detection_id,altitude_deg,airmass\n1,45,1.4\n"
            for run_id, version, exit_code in (("good", "0.22.0", 0), ("old", "0.20.0", 0), ("failed", "0.22.0", 1)):
                db.execute("INSERT INTO runs VALUES (?,?,?,?)", (run_id, digest, exit_code, version))
                for name, content in (("photometric_zenith.json", zenith), ("science_summary.json", science), ("planet_epoch.json", planets), ("star_coordinates.csv", coordinates), ("stellar_photometry.csv", photometry)):
                    db.execute("INSERT INTO products VALUES (?,?,?)", (run_id, name, content))
        with sqlite3.connect(manifest) as db:
            db.execute(
                """CREATE TABLE mmto_v22_observations (
                source_sha256 TEXT PRIMARY KEY, remote_url TEXT, discovery_utc TEXT,
                header_start_utc TEXT, header_midpoint_utc TEXT,
                exposure_seconds REAL, header_schema TEXT, provenance TEXT,
                instrument TEXT, recorded_utc TEXT)"""
            )
            db.execute(
                "INSERT INTO mmto_v22_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                (digest, "https://example/mmto.fits.bz2", "2026-09-19T03:00:00Z", "2026-09-19T02:19:50Z", "2026-09-19T02:20:00Z", 20.0, "old_local", "test header", "MMTO camera", "2026-10-18T00:00:00Z"),
            )
        return results, manifest

    def test_cli_reads_only_successful_v22_runs_and_does_not_mutate_databases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results, manifest = self._databases(root)
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (results, manifest)}
            output = root / "validation"
            completed = subprocess.run(
                ["uv", "run", "--frozen", "python", "scripts/validate_mmto_site_time_v22.py", "--database", str(results), "--manifest", str(manifest), "--output", str(output)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (results, manifest)}
            self.assertEqual(before, after)
            with (output / "mmto_site_time_validation.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["run_id"] for row in rows], ["good"])
            self.assertTrue((output / "mmto_airmass_validation.csv").is_file())
            self.assertTrue((output / "mmto_planet_epoch_validation.csv").is_file())
            self.assertTrue((output / "mmto_validation_provenance.json").is_file())
            self.assertTrue((output / "mmto_site_time_validation.png").is_file())
            self.assertTrue((output / "mmto_planet_epoch_validation.png").is_file())

    def test_pipeline_places_validation_after_blind_solver(self):
        from scripts.run_mmto_photometry_pipeline_v22 import _stage_commands

        commands = _stage_commands(
            ROOT, Path("db"), Path("manifest"), Path("output"),
            v21_control=Path("v21-control"),
        )
        names = [name for name, _ in commands]
        self.assertIn("known_site_time_validation", names)
        command = dict(commands)["known_site_time_validation"]
        self.assertNotIn("--observation-time", command)
        self.assertNotIn("--latitude", command)
        self.assertNotIn("--longitude", command)


if __name__ == "__main__":
    unittest.main()
