import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


def load_module():
    try:
        from scripts import plot_repeated_star_colours
    except ImportError as exc:
        raise AssertionError("repeated-star colour plotting module is missing") from exc
    return plot_repeated_star_colours


class RepeatedStarColourTests(unittest.TestCase):
    def test_loader_computes_camera_and_gaia_colours_for_repeated_blind_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalogue = root / "gaia.csv"
            with catalogue.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "source_id",
                        "phot_g_mean_mag",
                        "phot_bp_mean_mag",
                        "phot_rp_mean_mag",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "source_id": "123",
                        "phot_g_mean_mag": "5.0",
                        "phot_bp_mean_mag": "5.8",
                        "phot_rp_mean_mag": "4.4",
                    }
                )

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
                provenance = json.dumps(
                    {
                        "metadata_used": False,
                        "airmass_source": "blind_photometric_zenith",
                    }
                )
                for number in (1, 2):
                    run_id = f"run-{number}"
                    db.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                        (
                            run_id,
                            f"2026-09-17T0{number}:00:00Z",
                            f"/images/subaru_{number}.jpg",
                            f"image-{number}",
                            0,
                            "catalogue",
                        ),
                    )
                    db.execute(
                        "INSERT INTO products VALUES (?,?,?)",
                        (run_id, "photometry_summary.json", provenance),
                    )
                    values = {
                        "R_mag": str(10.0 + number),
                        "G_mag": str(10.5 + number),
                        "B_mag": str(11.5 + number),
                        "airmass": str(1.0 + number / 10),
                        "photometry_usable": "True",
                    }
                    db.execute(
                        "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                        (
                            run_id,
                            "stellar_photometry.csv",
                            1,
                            "Gaia DR3 123",
                            "1",
                            json.dumps(values),
                        ),
                    )
                    db.execute(
                        "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                        (
                            run_id,
                            "stellar_photometry.csv",
                            2,
                            f"HIP {number}",
                            "2",
                            json.dumps(values),
                        ),
                    )

            module = load_module()
            rows = module.load_repeated_colour_rows(database, catalogue)

            self.assertEqual(len(rows), 2)
            self.assertEqual({row.star_id for row in rows}, {"Gaia DR3 123"})
            self.assertEqual({row.machine_b_minus_g for row in rows}, {1.0})
            self.assertEqual({row.machine_g_minus_r for row in rows}, {0.5})
            self.assertEqual({row.machine_b_minus_r for row in rows}, {1.5})
            self.assertEqual(
                {getattr(row, "machine_r_mag", None) for row in rows},
                {11.0, 12.0},
            )
            self.assertEqual(
                {getattr(row, "machine_g_mag", None) for row in rows},
                {11.5, 12.5},
            )
            self.assertEqual(
                {getattr(row, "machine_b_mag", None) for row in rows},
                {12.5, 13.5},
            )
            self.assertEqual({row.gaia_bp_minus_g for row in rows}, {0.8})
            self.assertEqual({row.gaia_g_minus_rp for row in rows}, {0.6})
            self.assertEqual({row.gaia_bp_minus_rp for row in rows}, {1.4})


if __name__ == "__main__":
    unittest.main()
