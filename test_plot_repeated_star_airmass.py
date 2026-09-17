import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import plot_repeated_star_airmass as repeated


class RepeatedStarAirmassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / "stars.sqlite"
        with sqlite3.connect(self.database) as db:
            db.executescript(
                """
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY, recorded_at_utc TEXT NOT NULL,
                    source_path TEXT NOT NULL, source_sha256 TEXT,
                    exit_code INTEGER NOT NULL, catalogue_sha256 TEXT
                );
                CREATE TABLE products (
                    run_id TEXT NOT NULL, product TEXT NOT NULL, content BLOB
                );
                CREATE TABLE measurements (
                    run_id TEXT NOT NULL, product TEXT NOT NULL,
                    row_number INTEGER NOT NULL, star_id TEXT,
                    detection_id TEXT, values_json TEXT NOT NULL
                );
                """
            )

    def add_run(
        self,
        run_id,
        source,
        image_hash,
        *,
        exit_code=0,
        recorded="2026-09-17T00:00:00Z",
    ):
        with sqlite3.connect(self.database) as db:
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                (run_id, recorded, source, image_hash, exit_code, "catalogue-a"),
            )
            db.execute(
                "INSERT INTO products VALUES (?,?,?)",
                (
                    run_id,
                    "photometry_summary.json",
                    json.dumps(
                        {
                            "metadata_used": False,
                            "airmass_source": "blind_photometric_zenith",
                        }
                    ),
                ),
            )

    def add_measurement(self, run_id, row_number, star_id, **overrides):
        values = {
            "R_mag": "-10.0",
            "G_mag": "-10.1",
            "B_mag": "-10.2",
            "R_minus_catalogue_mag": "-15.0",
            "G_minus_catalogue_mag": "-15.1",
            "B_minus_catalogue_mag": "-15.2",
            "catalogue_magnitude": "5.0",
            "airmass": "1.5",
            "altitude_deg": "41.8",
            "source_class": "compact",
            "photometry_usable": "True",
        }
        values.update(overrides)
        with sqlite3.connect(self.database) as db:
            db.execute(
                "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    "stellar_photometry.csv",
                    row_number,
                    star_id,
                    str(row_number),
                    json.dumps(values),
                ),
            )

    def test_channel_rows_require_two_distinct_successful_subaru_images(self):
        self.add_run("s1", "/images/subaru_one.jpg", "hash-one")
        self.add_run("s2", "/images/subaru_two.jpg", "hash-two")
        self.add_run(
            "rerun",
            "/images/subaru_one_copy.jpg",
            "hash-one",
            recorded="2026-09-17T01:00:00Z",
        )
        self.add_run(
            "failed", "/images/subaru_failed.jpg", "hash-failed", exit_code=1
        )
        self.add_run("espenak", "/images/FishEye_Espenak.jpg", "hash-espenak")

        self.add_measurement(
            "s1", 1, "STAR repeated", airmass="1.25", R_minus_catalogue_mag="-14.5"
        )
        self.add_measurement(
            "s2", 1, "STAR repeated", airmass="2.5", R_minus_catalogue_mag="-14.0"
        )
        self.add_measurement("rerun", 1, "STAR duplicate-only")
        self.add_measurement("s1", 2, "STAR duplicate-only")
        self.add_measurement("s1", 3, "STAR singleton")
        self.add_measurement(
            "s1", 4, "STAR nonfinite", R_minus_catalogue_mag="nan"
        )
        self.add_measurement(
            "s2", 2, "STAR nonfinite", R_minus_catalogue_mag="-13.0"
        )
        self.add_measurement("failed", 1, "STAR failed-only")
        self.add_measurement("s1", 5, "STAR failed-only")
        self.add_measurement("espenak", 1, "STAR repeated")

        rows = repeated.load_repeated_channel_rows(self.database, "R")

        self.assertEqual(
            [row.star_id for row in rows], ["STAR repeated", "STAR repeated"]
        )
        self.assertEqual(
            [row.source_sha256 for row in rows], ["hash-one", "hash-two"]
        )
        self.assertEqual([row.airmass for row in rows], [1.25, 2.5])
        self.assertEqual(
            [row.machine_minus_catalogue_mag for row in rows], [-14.5, -14.0]
        )


if __name__ == "__main__":
    unittest.main()
