import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import plot_repeated_star_airmass as repeated


class RepeatedStarProvenanceTests(unittest.TestCase):
    def test_loader_accepts_only_verified_blind_airmass_and_same_catalogue(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "stars.sqlite"
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
                runs = (
                    ("p", "subaru_photometric.jpg", "image-p", 0, "catalogue-a", False, "blind_photometric_zenith"),
                    ("g", "subaru_geometry.jpg", "image-g", 0, "catalogue-a", False, "blind_centred_full_horizon_geometry"),
                    ("m", "subaru_metadata.jpg", "image-m", 0, "catalogue-a", True, "blind_photometric_zenith"),
                    ("u", "subaru_unknown.jpg", "image-u", 0, "catalogue-a", False, "metadata_site_airmass"),
                    ("x", "subaru_other_catalogue.jpg", "image-x", 0, "catalogue-b", False, "blind_photometric_zenith"),
                    ("n", "subaru_missing_provenance.jpg", "image-n", 0, "catalogue-a", None, None),
                )
                for number, (run_id, source, image_hash, exit_code, catalogue, metadata_used, airmass_source) in enumerate(runs, 1):
                    db.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                        (run_id, f"2026-09-17T0{number}:00:00Z", source, image_hash, exit_code, catalogue),
                    )
                    if metadata_used is not None:
                        db.execute(
                            "INSERT INTO products VALUES (?,?,?)",
                            (
                                run_id,
                                "photometry_summary.json",
                                json.dumps({
                                    "metadata_used": metadata_used,
                                    "airmass_source": airmass_source,
                                }),
                            ),
                        )

                values = {
                    "R_mag": "-10", "G_mag": "-10", "B_mag": "-10",
                    "R_minus_catalogue_mag": "-15",
                    "G_minus_catalogue_mag": "-15",
                    "B_minus_catalogue_mag": "-15",
                    "catalogue_magnitude": "5", "airmass": "1.5",
                    "altitude_deg": "42", "source_class": "compact",
                    "photometry_usable": "True",
                }
                memberships = {
                    "p": ("STAR accepted", "STAR metadata", "STAR unknown", "STAR missing", "STAR mixed catalogue"),
                    "g": ("STAR accepted",),
                    "m": ("STAR metadata",),
                    "u": ("STAR unknown",),
                    "n": ("STAR missing",),
                    "x": ("STAR mixed catalogue",),
                }
                for run_id, stars in memberships.items():
                    for row_number, star_id in enumerate(stars, 1):
                        db.execute(
                            "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                            (
                                run_id, "stellar_photometry.csv", row_number,
                                star_id, str(row_number), json.dumps(values),
                            ),
                        )

            rows = repeated.load_repeated_channel_rows(database, "R")

            self.assertEqual([row.star_id for row in rows], ["STAR accepted", "STAR accepted"])
            self.assertEqual(
                {row.airmass_source for row in rows},
                {"blind_photometric_zenith", "blind_centred_full_horizon_geometry"},
            )
            self.assertEqual({row.catalogue_sha256 for row in rows}, {"catalogue-a"})

    def test_dense_limits_clip_both_tails_without_losing_full_range(self):
        dense_limits = getattr(repeated, "dense_limits", None)
        self.assertIsNotNone(dense_limits, "dense_limits() is not implemented")

        lower, upper = dense_limits(list(range(100)))

        self.assertAlmostEqual(lower, 0.99)
        self.assertAlmostEqual(upper, 98.01)

    def test_catalogue_label_is_derived_from_committed_catalogue_checksum(self):
        gaia = Path("v6/data/stars_gaia_dr3_g75.csv")
        checksum = hashlib.sha256(gaia.read_bytes()).hexdigest()

        self.assertEqual(
            repeated.catalogue_label(checksum),
            "Gaia DR3 G + bright Tycho-2 VT/Hipparcos V supplement",
        )
        self.assertIn("unrecognized", repeated.catalogue_label("unknown").lower())


if __name__ == "__main__":
    unittest.main()
