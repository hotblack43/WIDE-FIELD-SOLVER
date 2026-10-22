from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class SiderealTransmissionCLITests(unittest.TestCase):
    def test_cli_writes_pair_audit_measured_rows_and_uninterpolated_maps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "stars.sqlite"
            manifest = root / "manifest.sqlite"
            calibration = root / "calibration"
            output = root / "output"
            calibration.mkdir()
            digests = ("1" * 64, "2" * 64)
            times = ("2026-09-19T02:20:00Z", "2026-09-20T02:16:04Z")
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE measurements (run_id TEXT, product TEXT, row_number INTEGER, star_id TEXT, detection_id TEXT, values_json TEXT)")
                for image in range(2):
                    for star in range(3):
                        values = {"x_px": 100.25 + star, "y_px": 200.75 + star}
                        db.execute("INSERT INTO measurements VALUES (?,?,?,?,?,?)", (f"run-{image}", "star_coordinates.csv", star + 1, f"star-{star}", str(star + 1), json.dumps(values)))
            with sqlite3.connect(manifest) as db:
                db.execute("CREATE TABLE mmto_v22_observations (source_sha256 TEXT PRIMARY KEY, header_midpoint_utc TEXT)")
                for digest, midpoint in zip(digests, times, strict=True):
                    db.execute("INSERT INTO mmto_v22_observations VALUES (?,?)", (digest, midpoint))
            fields = ("night", "header_midpoint_utc", "run_id", "source_sha256", "catalogue_sha256", "star_id", "channel", "corrected_magnitude")
            with (calibration / "corrected_stellar_photometry.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
                for image in range(2):
                    for channel in ("R", "G"):
                        for star in range(3):
                            writer.writerow({"night": f"night-{image}", "header_midpoint_utc": times[image], "run_id": f"run-{image}", "source_sha256": digests[image], "catalogue_sha256": "cat", "star_id": f"star-{star}", "channel": channel, "corrected_magnitude": 10 + star + image * (0.1 * star)})
            completed = subprocess.run([
                "uv", "run", "--frozen", "python", "scripts/map_mmto_sidereal_transmission_v22.py",
                "--database", str(database), "--manifest", str(manifest),
                "--nightly-calibration", str(calibration), "--output", str(output),
                "--tolerance-minutes", "5", "--min-common-stars", "3",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with (output / "sidereal_pair_summary.csv").open(newline="", encoding="utf-8") as stream:
                pairs = list(csv.DictReader(stream))
            self.assertEqual({row["pair_id"] for row in pairs}, {"pair-0001"})
            self.assertEqual({row["same_night"] for row in pairs}, {"False"})
            with (output / "sidereal_transmission_measurements.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 6)
            self.assertEqual({float(row["x_px"]) for row in rows}, {100.25, 101.25, 102.25})
            self.assertEqual({row["channel"] for row in rows}, {"R", "G"})
            maps = sorted((output / "maps").glob("*.png"))
            self.assertEqual(len(maps), 2)
            manifest_json = json.loads((output / "sidereal_transmission_manifest.json").read_text())
            self.assertFalse(manifest_json["interpolation_used"])

    def test_pipeline_maps_after_v22_grey_calibration(self):
        from scripts.run_mmto_photometry_pipeline_v22 import _stage_commands
        stages = _stage_commands(
            ROOT, Path("db"), Path("manifest"), Path("output"),
            v21_control=Path("v21-control"),
        )
        names = [name for name, _ in stages]
        self.assertLess(names.index("v22_grey_extinction"), names.index("same_sidereal_transmission"))


if __name__ == "__main__":
    unittest.main()
