"""Planet-only nightly airmass corrections use no stellar measurements."""
from __future__ import annotations

import csv
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


class PlanetOnlyAirmassCorrectionTests(unittest.TestCase):
    @staticmethod
    def sequence(count=10):
        rows = []
        for index in range(count):
            airmass = 1.0 + index / max(count - 1, 1)
            rows.append({
                "night": "2026-09-19",
                "channel": "G",
                "planet": "Saturn",
                "camera_label": "MMTO skycam",
                "source_sha256": f"source-{index}",
                "planet_airmass": airmass,
                "distance_corrected_magnitude": 4.0 + 0.2 * airmass,
                "machine_magnitude_uncertainty": 0.01,
            })
        return rows

    def test_accepted_sequence_recovers_planet_slope_and_flattens_at_airmass_one(self):
        from scripts import plot_planet_only_airmass_correction as correction

        rows = self.sequence()
        for row in rows:
            row["nightly_extinction_mag_per_airmass"] = 99.0
            row["stellar_extinction_mag_per_airmass"] = -99.0

        corrected, fits, audited = correction.fit_planet_only_sequences(rows)

        self.assertEqual(len(fits), 1)
        self.assertEqual(fits[0]["status"], "accepted")
        self.assertAlmostEqual(
            fits[0][
                "planet_empirical_extinction_coefficient_mag_per_airmass"
            ],
            0.2,
            12,
        )
        self.assertEqual(len(corrected), 10)
        for row in corrected:
            self.assertAlmostEqual(
                row[
                    "planet_empirical_extinction_corrected_distance_magnitude"
                ],
                4.2,
                12,
            )
            self.assertEqual(row["planet_only_airmass_correction_status"], "available")
        self.assertEqual(len(audited), 10)

    def test_sequence_with_fewer_than_ten_points_is_not_corrected(self):
        from scripts import plot_planet_only_airmass_correction as correction

        corrected, fits, audited = correction.fit_planet_only_sequences(
            self.sequence(count=9)
        )

        self.assertEqual(corrected, [])
        self.assertEqual(fits[0]["status"], "insufficient_measurements")
        self.assertEqual(
            {row["planet_only_airmass_correction_status"] for row in audited},
            {"insufficient_measurements"},
        )

    def test_airmass_above_five_is_audited_and_does_not_change_fit(self):
        from scripts import plot_planet_only_airmass_correction as correction

        rows = self.sequence()
        rows.append({
            **rows[-1],
            "source_sha256": "above-limit",
            "planet_airmass": 8.0,
            "distance_corrected_magnitude": -50.0,
        })

        corrected, fits, audited = correction.fit_planet_only_sequences(rows)

        self.assertEqual(len(corrected), 10)
        self.assertEqual(fits[0]["measurement_count"], 10)
        self.assertEqual(fits[0]["measurements_above_maximum_airmass"], 1)
        self.assertAlmostEqual(
            fits[0][
                "planet_empirical_extinction_coefficient_mag_per_airmass"
            ],
            0.2,
            12,
        )
        above = next(row for row in audited if row["source_sha256"] == "above-limit")
        self.assertEqual(
            above["planet_only_airmass_correction_status"],
            "airmass_above_maximum",
        )

    def test_invalid_measurement_is_not_counted_as_above_maximum_airmass(self):
        from scripts import plot_planet_only_airmass_correction as correction

        rows = self.sequence()
        rows.append({
            **rows[-1],
            "source_sha256": "invalid",
            "planet_airmass": "not-a-number",
        })

        corrected, fits, audited = correction.fit_planet_only_sequences(rows)

        self.assertEqual(len(corrected), 10)
        self.assertEqual(fits[0]["invalid_measurement_count"], 1)
        self.assertEqual(fits[0]["measurements_above_maximum_airmass"], 0)
        invalid = next(row for row in audited if row["source_sha256"] == "invalid")
        self.assertEqual(
            invalid["planet_only_airmass_correction_status"],
            "invalid_measurement",
        )

    def test_writer_creates_direct_before_after_figure_and_auditable_tables(self):
        from scripts import plot_planet_only_airmass_correction as correction

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            rows = self.sequence()
            rows[0].update({
                "catalogue_sha256": "catalogue-digest",
                "camera_provenance": "test camera",
                "planet_measured_altitude_deg": 42.0,
                "metadata_association_method": "test ephemeris association",
                "association_predicted_x_px": 50.25,
                "association_predicted_y_px": 40.5,
                "association_measured_x_px": 50.0,
                "association_measured_y_px": 40.0,
                "association_separation_arcmin": 1.25,
            })
            summary = correction.write_channel_outputs(
                rows, output, channel="G"
            )

            self.assertTrue(
                (output / "planet_only_airmass_before_after.pdf").is_file()
            )
            self.assertTrue(
                (
                    output
                    / "planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf"
                ).is_file()
            )
            with (
                output / "planet_nightly_empirical_extinction_coefficients.csv"
            ).open(
                newline="", encoding="utf-8"
            ) as stream:
                fit = next(csv.DictReader(stream))
            self.assertEqual(fit["status"], "accepted")
            self.assertAlmostEqual(
                float(
                    fit[
                        "planet_empirical_extinction_coefficient_mag_per_airmass"
                    ]
                ),
                0.2,
                12,
            )
            with (output / "planet_only_airmass_corrected_measurements.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                measurements = list(csv.DictReader(stream))
            self.assertEqual(len(measurements), 10)
            self.assertEqual(measurements[0]["catalogue_sha256"], "catalogue-digest")
            self.assertEqual(
                measurements[0]["metadata_association_method"],
                "test ephemeris association",
            )
            self.assertEqual(
                float(measurements[0]["association_separation_arcmin"]),
                1.25,
            )
            self.assertEqual(summary["accepted_sequence_count"], 1)
            self.assertEqual(summary["corrected_measurement_count"], 10)

    def test_preparation_uses_metadata_planet_rows_without_stellar_calibration(self):
        from scripts import plot_planet_only_airmass_correction as correction

        row = {
            "run_id": "run-1",
            "detection_id": "7",
            "identity_status": "metadata_time_match",
            "photometry_usable": True,
            "observation_time_utc": "2026-09-20T01:00:00Z",
            "channel": "G",
            "planet": "Mars",
            "camera_label": "MMTO skycam",
            "planet_airmass": 2.0,
            "machine_magnitude": 5.0,
            "stellar_extinction_mag_per_airmass": 123.0,
        }
        distances = {
            ("Mars", "2026-09-20T01:00:00Z"): {
                "sun_planet_distance_au": 2.0,
                "earth_planet_distance_au": 3.0,
                "distance_ephemeris_source": "test",
            }
        }

        prepared, audited = correction.prepare_planet_measurements(
            [row], distances, uncertainty_lookup={}
        )

        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["night"], "2026-09-19")
        self.assertAlmostEqual(prepared[0]["hours_past_local_noon"], 6.0, 12)
        self.assertAlmostEqual(
            prepared[0]["distance_corrected_magnitude"],
            5.0 - 5.0 * __import__("math").log10(6.0),
            12,
        )
        self.assertNotIn(
            "stellar_extinction_mag_per_airmass",
            correction.MEASUREMENT_FIELDS,
        )
        self.assertEqual(audited[0]["planet_only_input_status"], "ready")

    def test_local_noon_figure_plots_final_corrected_magnitude_by_sequence(self):
        import matplotlib.pyplot as plt
        from scripts import plot_planet_only_airmass_correction as correction

        builder = getattr(correction, "_build_local_noon_figure", None)
        self.assertTrue(callable(builder))
        if not callable(builder):
            return
        rows = self.sequence()
        corrected, _, _ = correction.fit_planet_only_sequences(rows)
        for index, row in enumerate(corrected):
            row["hours_past_local_noon"] = 6.0 + index

        figure, axis = builder(corrected, channel="G")
        self.addCleanup(plt.close, figure)

        self.assertEqual(len(axis.lines), 1)
        self.assertEqual(list(axis.lines[0].get_xdata()), list(range(6, 16)))
        for magnitude in axis.lines[0].get_ydata():
            self.assertAlmostEqual(float(magnitude), 4.2, 12)
        self.assertIn("Hours past 12:00", axis.get_xlabel())

    @staticmethod
    def database_fit(*, coefficient=0.2, status="accepted"):
        return {
            "night": "2026-09-19",
            "channel": "G",
            "planet": "Saturn",
            "camera_label": "MMTO skycam",
            "status": status,
            "input_measurement_count": 12,
            "measurement_count": 12,
            "invalid_measurement_count": 0,
            "measurements_above_maximum_airmass": 0,
            "airmass_min": 1.0,
            "airmass_max": 2.0,
            "airmass_span": 1.0,
            "planet_empirical_extinction_coefficient_mag_per_airmass": (
                coefficient if status == "accepted" else None
            ),
            "planet_empirical_extinction_intercept_magnitude": (
                4.0 if status == "accepted" else None
            ),
            "planet_empirical_extinction_coefficient_low_95": (
                coefficient - 0.02 if status == "accepted" else None
            ),
            "planet_empirical_extinction_coefficient_high_95": (
                coefficient + 0.02 if status == "accepted" else None
            ),
            "planet_empirical_extinction_reference_airmass": 1.0,
        }

    def test_database_keeps_generations_and_latest_view_does_not_expose_stale_fit(self):
        from scripts import plot_planet_only_airmass_correction as correction

        writer = getattr(
            correction, "write_planet_empirical_extinction_generation", None
        )
        self.assertTrue(callable(writer))
        if not callable(writer):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "stars.sqlite"
            manifest = root / "manifest.sqlite"
            manifest.write_bytes(b"verified manifest fixture")
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE runs (run_id TEXT)")

            first = writer(
                database,
                manifest,
                root / "first-output",
                {"G": [self.database_fit(coefficient=0.2)]},
                {"G": {"verified_manifest_images": 12}},
                producer_version="0.16.0",
            )
            second = writer(
                database,
                manifest,
                root / "second-output",
                {"G": [self.database_fit(coefficient=0.3)]},
                {"G": {"verified_manifest_images": 12}},
                producer_version="0.16.0",
            )

            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM planet_empirical_extinction_generations"
                    ).fetchone()[0],
                    2,
                )
                rows = connection.execute(
                    """
                    SELECT generation_id,
                           planet_empirical_extinction_coefficient_mag_per_airmass
                    FROM latest_accepted_planet_empirical_extinction_coefficients
                    """
                ).fetchall()
            self.assertNotEqual(first, second)
            self.assertEqual(rows, [(second, 0.3)])

            rejected = self.database_fit(status="insufficient_airmass_span")
            third = writer(
                database,
                manifest,
                root / "third-output",
                {"G": [rejected]},
                {"G": {"verified_manifest_images": 12}},
                producer_version="0.16.0",
            )
            with sqlite3.connect(database) as connection:
                latest = connection.execute(
                    """
                    SELECT generation_id,status,
                           planet_empirical_extinction_coefficient_mag_per_airmass
                    FROM latest_planet_nightly_empirical_extinction_coefficients
                    """
                ).fetchall()
                accepted_count = connection.execute(
                    "SELECT count(*) FROM latest_accepted_planet_empirical_extinction_coefficients"
                ).fetchone()[0]
            self.assertEqual(latest, [(third, "insufficient_airmass_span", None)])
            self.assertEqual(accepted_count, 0)

    def test_database_generation_rolls_back_if_any_fit_row_conflicts(self):
        from scripts import plot_planet_only_airmass_correction as correction

        writer = getattr(
            correction, "write_planet_empirical_extinction_generation", None
        )
        self.assertTrue(callable(writer))
        if not callable(writer):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "stars.sqlite"
            manifest = root / "manifest.sqlite"
            manifest.write_bytes(b"verified manifest fixture")
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE runs (run_id TEXT)")
            writer(
                database, manifest, root / "first-output",
                {"G": [self.database_fit()]}, {"G": {}},
                producer_version="0.16.0",
            )

            duplicate = self.database_fit(coefficient=0.4)
            with self.assertRaises(sqlite3.IntegrityError):
                writer(
                    database, manifest, root / "bad-output",
                    {"G": [duplicate, duplicate]}, {"G": {}},
                    producer_version="0.16.0",
                )

            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM planet_empirical_extinction_generations"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM planet_nightly_empirical_extinction_coefficients"
                    ).fetchone()[0],
                    1,
                )

    def test_command_line_is_read_only_without_store_coefficients_flag(self):
        from scripts import plot_planet_only_airmass_correction as correction

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "stars.sqlite"
            manifest = root / "manifest.sqlite"
            output = root / "output"
            database.write_bytes(b"")
            with sqlite3.connect(manifest) as connection:
                connection.execute("CREATE TABLE marker (value TEXT)")
                connection.execute("INSERT INTO marker VALUES ('before')")
            with mock.patch.object(
                correction,
                "load_mmto_manifest_planet_measurements",
                return_value=([], {}),
            ) as loader, mock.patch.object(
                correction, "_horizons_distance_lookup", return_value={}
            ):
                self.assertEqual(
                    correction.main([
                        "--database", str(database),
                        "--manifest", str(manifest),
                        "--output", str(output),
                    ]),
                    0,
                )

            snapshot_paths = {call.args[1] for call in loader.call_args_list}
            self.assertEqual(len(snapshot_paths), 1)
            snapshot = next(iter(snapshot_paths))
            self.assertNotEqual(Path(snapshot), manifest)
            with sqlite3.connect(snapshot) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM marker").fetchall(),
                    [("before",)],
                )

            with sqlite3.connect(database) as connection:
                extension_tables = connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name LIKE 'planet_%extinction%'
                    """
                ).fetchall()
            self.assertEqual(extension_tables, [])

    def test_manifest_snapshot_includes_wal_and_is_immutable_after_source_changes(self):
        from scripts import plot_planet_only_airmass_correction as correction

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "manifest.sqlite"
            snapshot = root / "snapshot.sqlite"
            with sqlite3.connect(source) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE marker (value TEXT)")
                connection.execute("INSERT INTO marker VALUES ('captured')")

            digest = correction.snapshot_sqlite_database(source, snapshot)
            with sqlite3.connect(source) as connection:
                connection.execute("INSERT INTO marker VALUES ('later')")

            self.assertEqual(digest, correction._file_sha256(snapshot))
            with sqlite3.connect(snapshot) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM marker").fetchall(),
                    [("captured",)],
                )

    def test_stored_generation_identifies_the_exact_manifest_snapshot(self):
        from scripts import plot_planet_only_airmass_correction as correction

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "stars.sqlite"
            manifest = root / "manifest.sqlite"
            output = root / "output"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE runs (run_id TEXT)")
            with sqlite3.connect(manifest) as connection:
                connection.execute("CREATE TABLE marker (value TEXT)")
                connection.execute("INSERT INTO marker VALUES ('captured')")

            with mock.patch.object(
                correction,
                "load_mmto_manifest_planet_measurements",
                return_value=([], {}),
            ), mock.patch.object(
                correction, "_horizons_distance_lookup", return_value={}
            ):
                self.assertEqual(
                    correction.main([
                        "--database", str(database),
                        "--manifest", str(manifest),
                        "--output", str(output),
                        "--store-coefficients",
                    ]),
                    0,
                )

            snapshot = output / "input_manifest_snapshot.sqlite"
            with sqlite3.connect(database) as connection:
                saved_path, saved_sha256 = connection.execute(
                    "SELECT manifest_path,manifest_sha256 "
                    "FROM planet_empirical_extinction_generations"
                ).fetchone()
            self.assertEqual(Path(saved_path), snapshot.resolve())
            self.assertEqual(saved_sha256, correction._file_sha256(snapshot))

if __name__ == "__main__":
    unittest.main()
