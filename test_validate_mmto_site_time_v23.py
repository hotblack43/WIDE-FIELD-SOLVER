from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent


class ValidateMMTOSiteTimeV23Tests(unittest.TestCase):
    def test_cli_batches_large_exposure_and_preserves_read_only_inputs(self):
        coordinate_count = 1200
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "stars.sqlite"
            manifest = root / "manifest.sqlite"
            output = root / "validation"
            digest = "1" * 64
            with sqlite3.connect(results) as db:
                db.executescript(
                    """
                    CREATE TABLE runs (
                        run_id TEXT PRIMARY KEY, source_sha256 TEXT,
                        exit_code INTEGER, solver_version TEXT
                    );
                    CREATE TABLE products (
                        run_id TEXT, product TEXT, content BLOB
                    );
                    """
                )
                zenith = json.dumps({
                    "status": "conditional_zenith",
                    "zenith_unit_vector": [0, 0, 1],
                    "metadata_used": False,
                })
                science = json.dumps({
                    "stellar_epoch": {
                        "status": "conditional_epoch",
                        "epoch_jyear": 1937.3238904472876,
                    }
                })
                planets = json.dumps({
                    "status": "planet_epoch_ambiguous",
                    "metadata_used": False,
                    "candidates": [],
                })
                coordinate_lines = [
                    "detection_id,measured_ra_deg,measured_dec_deg"
                ]
                photometry_lines = ["detection_id,altitude_deg,airmass"]
                for index in range(coordinate_count):
                    coordinate_lines.append(
                        f"{index},{index * 0.25 % 360.0},{-60.0 + index % 120}"
                    )
                    photometry_lines.append(f"{index},45,1.4")
                products = (
                    ("photometric_zenith.json", zenith),
                    ("science_summary.json", science),
                    ("planet_epoch.json", planets),
                    ("star_coordinates.csv", "\n".join(coordinate_lines) + "\n"),
                    ("stellar_photometry.csv", "\n".join(photometry_lines) + "\n"),
                )
                db.execute(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    ("good", digest, 0, "0.23.0"),
                )
                for name, content in products:
                    db.execute(
                        "INSERT INTO products VALUES (?,?,?)",
                        ("good", name, content),
                    )
            with sqlite3.connect(manifest) as db:
                db.execute(
                    """CREATE TABLE mmto_v23_observations (
                    source_sha256 TEXT PRIMARY KEY, remote_url TEXT,
                    discovery_utc TEXT, header_start_utc TEXT,
                    header_midpoint_utc TEXT, exposure_seconds REAL,
                    header_schema TEXT, provenance TEXT, instrument TEXT,
                    recorded_utc TEXT)"""
                )
                db.execute(
                    "INSERT INTO mmto_v23_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        digest, "https://example/mmto.fits.bz2",
                        "2026-09-19T03:00:00Z", "2026-09-19T02:19:50Z",
                        "2026-09-19T02:20:00Z", 20.0, "old_local",
                        "test header", "MMTO camera", "2026-10-18T00:00:00Z",
                    ),
                )
            before = {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (results, manifest)
            }

            started = time.monotonic()
            completed = subprocess.run(
                [
                    "uv", "run", "--frozen", "python",
                    "scripts/validate_mmto_site_time_v23.py",
                    "--database", str(results),
                    "--manifest", str(manifest),
                    "--output", str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertLess(elapsed, 3.0)
            self.assertNotIn("dubious year", completed.stderr)
            after = {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (results, manifest)
            }
            self.assertEqual(before, after)
            with (output / "mmto_airmass_validation.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), coordinate_count)


if __name__ == "__main__":
    unittest.main()
