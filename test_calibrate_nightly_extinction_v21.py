from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class CalibrateNightlyExtinctionV21Tests(unittest.TestCase):
    def _databases(self, root: Path):
        database = root / "stars.sqlite"
        manifest = root / "manifest.sqlite"
        with sqlite3.connect(database) as db:
            db.executescript(
                """
                CREATE TABLE runs (run_id TEXT PRIMARY KEY, recorded_at_utc TEXT,
                  source_sha256 TEXT, catalogue_sha256 TEXT, exit_code INTEGER,
                  solver_version TEXT);
                CREATE TABLE measurements (run_id TEXT, product TEXT, row_number INTEGER,
                  star_id TEXT, detection_id TEXT, values_json TEXT);
                """
            )
            for image in range(3):
                digest = str(image + 1) * 64
                db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (f"run-{image}", f"2026-09-19T0{image}:00:00Z", digest, "catalogue", 0, "0.21.0"))
                for star in range(4):
                    x = 1.05 + 0.3 * image + 0.08 * star + 0.04 * image * star
                    delta = -11 + 0.15 * star + 0.22 * x + (-0.1, 0.0, 0.1)[image]
                    machine = 2.0 + delta
                    rate = 10 ** (-machine / 2.5)
                    values = {"catalogue_magnitude": 2.0, "airmass": x, "saturation_known": True}
                    for channel in ("R", "G", "B"):
                        values[f"{channel}_count_rate_adu_per_s"] = rate
                        values[f"{channel}_saturated"] = False
                        values[f"{channel}_measurement_method"] = "aperture"
                    db.execute("INSERT INTO measurements VALUES (?,?,?,?,?,?)", (f"run-{image}", "stellar_photometry.csv", star + 1, f"star-{star}", str(star + 1), json.dumps(values)))
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", ("old", "2026-09-19T04:00:00Z", "9" * 64, "catalogue", 0, "0.20.0"))
        with sqlite3.connect(manifest) as db:
            db.execute("""CREATE TABLE mmto_v21_observations (
              source_sha256 TEXT PRIMARY KEY, remote_url TEXT, discovery_utc TEXT,
              header_start_utc TEXT, header_midpoint_utc TEXT, exposure_seconds REAL,
              header_schema TEXT, provenance TEXT, instrument TEXT, recorded_utc TEXT)""")
            for image in range(3):
                digest = str(image + 1) * 64
                db.execute("INSERT INTO mmto_v21_observations VALUES (?,?,?,?,?,?,?,?,?,?)", (digest, f"https://example/{image}", "2026-09-19T00:00:00Z", f"2026-09-19T0{image}:00:00Z", f"2026-09-19T0{image}:00:10Z", 20.0, "new_utc", "test", "MMTO", "2026-10-18T00:00:00Z"))
        return database, manifest

    def test_cli_writes_grey_terms_and_corrected_magnitudes_for_v21_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, manifest = self._databases(root)
            output = root / "output"
            completed = subprocess.run([
                "uv", "run", "--frozen", "python", "scripts/calibrate_nightly_extinction_v21.py",
                "--database", str(database), "--manifest", str(manifest),
                "--output", str(output), "--min-stars", "3", "--min-images", "3",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with (output / "image_grey_transparency.csv").open(newline="", encoding="utf-8") as stream:
                grey = list(csv.DictReader(stream))
            self.assertEqual(len(grey), 9)
            self.assertEqual({row["solver_version"] for row in grey}, {"0.21.0"})
            by_channel = {}
            for row in grey:
                by_channel.setdefault(row["channel"], 0.0)
                by_channel[row["channel"]] += float(row["grey_offset_magnitude"])
            for total in by_channel.values():
                self.assertAlmostEqual(total, 0.0, places=8)
            with (output / "corrected_stellar_photometry.csv").open(newline="", encoding="utf-8") as stream:
                corrected = list(csv.DictReader(stream))
            row = corrected[0]
            expected = float(row["machine_magnitude"]) - float(row["extinction_correction_magnitude"]) - float(row["grey_correction_magnitude"])
            self.assertAlmostEqual(float(row["corrected_magnitude"]), expected, places=10)
            provenance = json.loads((output / "calibration_provenance.json").read_text())
            self.assertEqual(provenance["formula"], "m(s,i) = a_s + k X(s,i) + Z_i; sum_i Z_i = 0")
            self.assertTrue((output / "grey_transparency.png").is_file())

    def test_pipeline_uses_v21_calibration_before_validation(self):
        from scripts.run_mmto_photometry_pipeline_v21 import _stage_commands
        stages = _stage_commands(ROOT, Path("db"), Path("manifest"), Path("output"))
        names = [name for name, _ in stages]
        self.assertIn("v21_grey_extinction", names)
        self.assertLess(names.index("v21_grey_extinction"), names.index("known_site_time_validation"))


if __name__ == "__main__":
    unittest.main()
