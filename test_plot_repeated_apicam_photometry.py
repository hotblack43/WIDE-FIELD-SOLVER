import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


class APICAMRepeatedPhotometryTests(unittest.TestCase):
    def test_loader_uses_only_repeated_monochrome_apicam_fits_rows(self):
        from scripts import plot_repeated_apicam_photometry as apicam

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalogue = root / "gaia.csv"
            with catalogue.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=("source_id", "phot_g_mean_mag",
                                "phot_bp_mean_mag", "phot_rp_mean_mag"),
                )
                writer.writeheader()
                writer.writerow(dict(source_id="123", phot_g_mean_mag="5.0",
                                     phot_bp_mean_mag="5.8",
                                     phot_rp_mean_mag="4.4"))

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
                provenance = json.dumps({
                    "metadata_used": False,
                    "airmass_source": "blind_photometric_zenith",
                })
                mono_input = json.dumps({"format": "fits", "plane_names": ["L"]})
                for number, source in enumerate(
                    ("APICAM.2018-09-13T00:00:00.fits",
                     "APICAM.2018-09-13T00:03:00.fits",
                     "subaru_ignored.jpg"), 1
                ):
                    run_id = f"run-{number}"
                    db.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                        (run_id, f"2026-09-17T0{number}:00:00Z",
                         f"/images/{source}", f"image-{number}", 0, "catalogue"),
                    )
                    db.execute("INSERT INTO products VALUES (?,?,?)",
                               (run_id, "photometry_summary.json", provenance))
                    db.execute("INSERT INTO products VALUES (?,?,?)",
                               (run_id, "input_image.json", mono_input))
                    magnitude = 10.0 + number
                    values = json.dumps({
                        "R_mag": magnitude, "G_mag": magnitude,
                        "B_mag": magnitude, "airmass": 1.0 + number / 10,
                        "photometry_usable": "True",
                    })
                    db.execute(
                        "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                        (run_id, "stellar_photometry.csv", 1,
                         "Gaia DR3 123", "1", values),
                    )

            rows = apicam.load_repeated_apicam_rows(database, catalogue)

            self.assertEqual(len(rows), 2)
            self.assertEqual({row.source_sha256 for row in rows},
                             {"image-1", "image-2"})
            self.assertEqual({row.machine_l_mag for row in rows}, {11.0, 12.0})
            self.assertEqual({row.machine_l_minus_gaia_g for row in rows},
                             {6.0, 7.0})
            self.assertEqual({row.gaia_bp_minus_rp for row in rows}, {1.4})

    def test_writer_creates_apicam_luminance_outputs_without_rgb_claims(self):
        from scripts import plot_repeated_apicam_photometry as apicam

        rows = []
        for star_number in range(1, 13):
            for image_number in range(1, 5):
                gaia_g = 4.0 + star_number / 10
                rows.append(apicam.APICAMMeasurement(
                    run_id=f"run-{image_number}", source_path="/images/APICAM.fits",
                    source_sha256=f"image-{image_number}",
                    catalogue_sha256="catalogue", star_id=f"Gaia DR3 {star_number}",
                    detection_id=str(star_number), airmass=1 + image_number / 5,
                    machine_l_mag=10 + star_number / 10 + image_number / 20,
                    gaia_g_mag=gaia_g, gaia_bp_mag=gaia_g + .7,
                    gaia_rp_mag=gaia_g - .5,
                    gaia_bp_minus_rp=1.2,
                    machine_l_minus_gaia_g=6 + image_number / 20,
                ))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = apicam.write_outputs(rows, output)
            self.assertEqual(summary.star_count, 12)
            self.assertEqual(summary.measurement_count, 48)
            expected = (
                "apicam_repeated_star_photometry.csv",
                "apicam_repeated_stars_L_minus_gaia_G_vs_gaia_BPRP.png",
                "apicam_four_well_observed_stars_L_airmass.png",
                "apicam_nine_well_observed_stars_L_airmass.png",
                "apicam_nine_bright_well_observed_stars_L_airmass_shared_ranges_le5.png",
            )
            for name in expected:
                self.assertGreater((output / name).stat().st_size, 100)
            self.assertFalse(any("RGB" in path.name for path in output.iterdir()))


if __name__ == "__main__":
    unittest.main()
