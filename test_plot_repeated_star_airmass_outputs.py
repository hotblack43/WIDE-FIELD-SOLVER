import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import plot_repeated_star_airmass as repeated


class RepeatedStarAirmassOutputTests(unittest.TestCase):
    def test_generate_writes_three_plots_and_one_provenance_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "stars.sqlite"
            with sqlite3.connect(database) as db:
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
                provenance = json.dumps(
                    {
                        "metadata_used": False,
                        "airmass_source": "blind_photometric_zenith",
                    }
                )
                for number in (1, 2):
                    run_id = f"s{number}"
                    db.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                        (
                            run_id,
                            f"2026-09-17T0{number}:00:00Z",
                            f"/images/subaru_{number}.jpg",
                            f"hash-{number}",
                            0,
                            "catalogue-a",
                        ),
                    )
                    db.execute(
                        "INSERT INTO products VALUES (?,?,?)",
                        (run_id, "photometry_summary.json", provenance),
                    )
                    row = dict(values, airmass=str(number))
                    db.execute(
                        "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                        (
                            run_id,
                            "stellar_photometry.csv",
                            1,
                            "STAR repeated",
                            "1",
                            json.dumps(row),
                        ),
                    )

            output = root / "plots"
            summary = repeated.generate(database, output)

            self.assertEqual(summary.star_counts, {"R": 1, "G": 1, "B": 1})
            self.assertEqual(
                summary.measurement_counts, {"R": 2, "G": 2, "B": 2}
            )
            for channel in ("R", "G", "B"):
                plot = output / f"subaru_repeated_stars_{channel}_vs_airmass.png"
                self.assertGreater(plot.stat().st_size, 1_000)
                self.assertEqual(plot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

            table = output / "subaru_repeated_star_airmass.csv"
            with table.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 6)
            self.assertEqual({row["channel"] for row in rows}, {"R", "G", "B"})
            self.assertEqual(
                {row["star_id"] for row in rows}, {"STAR repeated"}
            )
            self.assertEqual(
                {row["source_sha256"] for row in rows}, {"hash-1", "hash-2"}
            )
            self.assertEqual(
                {row["airmass_source"] for row in rows},
                {"blind_photometric_zenith"},
            )
            self.assertEqual(
                {row["catalogue_sha256"] for row in rows}, {"catalogue-a"}
            )
            self.assertEqual({row["metadata_used"] for row in rows}, {"False"})


if __name__ == "__main__":
    unittest.main()
