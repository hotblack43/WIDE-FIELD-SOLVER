import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import scripts.calibrate_nightly_extinction as calibration_cli
from scripts.calibrate_nightly_extinction import (
    CalibrationAuditRow,
    LoadedCalibrationData,
    ManifestEntry,
    load_mmto_calibration_data,
    main,
    read_mmto_manifest,
    write_calibration_outputs,
)
from scripts.nightly_extinction import CalibrationConfig, StellarMeasurement


def create_manifest_database(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            """
            CREATE TABLE downloads (
                remote_url TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                observed_utc TEXT NOT NULL,
                local_path TEXT,
                sha256 TEXT,
                download_status TEXT NOT NULL,
                validation_status TEXT NOT NULL
            )
            """
        )


def insert_manifest_row(
    path: Path,
    *,
    remote_url: str,
    source_id: str = "mmto",
    camera_id: str = "mmto-skycam",
    observed_utc: str = "2026-09-26T05:00:00+00:00",
    sha256: str | None = None,
    download_status: str = "downloaded",
    validation_status: str = "verified",
) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            """
            INSERT INTO downloads (
                remote_url, source_id, camera_id, observed_utc, local_path,
                sha256, download_status, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                remote_url,
                source_id,
                camera_id,
                observed_utc,
                "/data/" + remote_url.rsplit("/", 1)[-1],
                sha256,
                download_status,
                validation_status,
            ),
        )


def create_run_database(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                recorded_at_utc TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT,
                catalogue_sha256 TEXT,
                exit_code INTEGER NOT NULL
            );
            CREATE TABLE measurements (
                run_id TEXT NOT NULL,
                product TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                star_id TEXT,
                detection_id TEXT,
                values_json TEXT NOT NULL
            );
            """
        )


def insert_run(
    path: Path,
    run_id: str,
    recorded_at: str,
    source_sha256: str,
    catalogue_sha256: str,
    exit_code: int,
) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                recorded_at,
                f"/images/{source_sha256}.fits",
                source_sha256,
                catalogue_sha256,
                exit_code,
            ),
        )


def insert_measurement(
    path: Path,
    run_id: str,
    row_number: int,
    star_id: str,
    payload: dict[str, object] | str,
) -> None:
    values_json = payload if isinstance(payload, str) else json.dumps(payload)
    with sqlite3.connect(path) as database:
        database.execute(
            "INSERT INTO measurements VALUES (?, 'stellar_photometry.csv', ?, ?, ?, ?)",
            (run_id, row_number, star_id, f"detection-{row_number}", values_json),
        )


def photometry_payload(*, r_rate: float, g_saturated: bool = False) -> dict[str, object]:
    return {
        "catalogue_magnitude": "3.0",
        "airmass": "1.5",
        "saturation_known": "True",
        "R_count_rate_adu_per_s": str(r_rate),
        "R_saturated": "False",
        "R_measurement_method": "aperture",
        "R_mag": "-999.0",
        "G_count_rate_adu_per_s": "50.0",
        "G_saturated": "True" if g_saturated else "False",
        "G_measurement_method": "aperture",
        "G_mag": "-888.0",
        "B_count_rate_adu_per_s": "25.0",
        "B_saturated": "False",
        "B_measurement_method": "aperture",
        "B_mag": "-777.0",
    }


def synthetic_loaded_data(
    image_count: int,
    *,
    add_faint: bool = False,
    add_high_airmass: bool = False,
) -> LoadedCalibrationData:
    catalogue_sha = "c" * 64
    measurements: list[StellarMeasurement] = []
    audit_rows: list[CalibrationAuditRow] = []
    manifest_entries: list[ManifestEntry] = []
    for image in range(image_count):
        source_sha = f"{image + 1:064x}"
        observed = datetime(2026, 9, 26, 3, tzinfo=timezone.utc) + timedelta(
            minutes=20 * image
        )
        manifest_entries.append(
            ManifestEntry(
                source_sha256=source_sha,
                observed_utc=observed,
                night="2026-09-25",
                source_url=f"https://skycam.mmto.arizona.edu/skycam/archive/{image}.fits.bz2",
                local_path=f"/data/{image}.fits.bz2",
            )
        )
        stars = [
            (f"bright-{star:02d}", 2.5 + star / 100.0, 1.0 + 3.0 * star / 29.0)
            for star in range(30)
        ]
        if add_faint:
            stars.append(("faint-star", 4.5, 2.0))
        if add_high_airmass:
            stars.append(("high-airmass-star", 3.0, 6.0))
        for star_id, catalogue_magnitude, airmass in stars:
            slope = 0.12 + 0.005 * image
            zero_point = -6.0 + 0.02 * (image % 3)
            delta_magnitude = zero_point + slope * airmass
            machine_magnitude = catalogue_magnitude + delta_magnitude
            count_rate = 10.0 ** (-0.4 * machine_magnitude)
            measurement = StellarMeasurement(
                night="2026-09-25",
                source_sha256=source_sha,
                catalogue_sha256=catalogue_sha,
                star_id=star_id,
                channel="R",
                catalogue_magnitude=catalogue_magnitude,
                count_rate_adu_per_s=count_rate,
                count_rate_uncertainty_adu_per_s=0.1,
                airmass=airmass,
                saturated=False,
                measurement_method="ordinary_aperture",
                observed_utc=observed.isoformat(),
            )
            measurements.append(measurement)
            audit_rows.append(
                CalibrationAuditRow(
                    run_id=f"run-{image}",
                    source_sha256=source_sha,
                    catalogue_sha256=catalogue_sha,
                    night="2026-09-25",
                    star_id=star_id,
                    detection_id=f"detection-{star_id}",
                    channel="R",
                    catalogue_magnitude=catalogue_magnitude,
                    count_rate_adu_per_s=count_rate,
                    airmass=airmass,
                    saturated=False,
                    measurement_method="ordinary_aperture",
                    included=True,
                    exclusion_reasons=(),
                )
            )
    return LoadedCalibrationData(
        measurements=tuple(measurements),
        audit_rows=tuple(audit_rows),
        selected_run_ids=tuple(f"run-{image}" for image in range(image_count)),
        manifest_entries=tuple(manifest_entries),
    )


class ManifestLoadingTests(unittest.TestCase):
    def test_sqlite_manifest_accepts_only_verified_mmto_skycam_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.sqlite"
            create_manifest_database(path)
            accepted_sha = "a" * 64
            insert_manifest_row(
                path,
                remote_url="https://skycam.mmto.arizona.edu/skycam/archive/accepted.jpg",
                sha256=accepted_sha,
            )
            insert_manifest_row(
                path,
                remote_url="https://example.test/not-mmto.jpg",
                source_id="rubin",
                camera_id="rubin-public-sample",
                sha256="b" * 64,
            )
            insert_manifest_row(
                path,
                remote_url="https://example.test/wrong-camera.jpg",
                camera_id="other-camera",
                sha256="c" * 64,
            )
            insert_manifest_row(
                path,
                remote_url="https://skycam.mmto.arizona.edu/skycam/archive/pending.jpg",
                sha256="d" * 64,
                download_status="pending",
            )
            insert_manifest_row(
                path,
                remote_url="https://skycam.mmto.arizona.edu/skycam/archive/invalid.jpg",
                sha256="e" * 64,
                validation_status="invalid",
            )
            insert_manifest_row(
                path,
                remote_url="https://skycam.mmto.arizona.edu/skycam/archive/no-hash.jpg",
                sha256=None,
            )

            entries = read_mmto_manifest(path)

        self.assertEqual(set(entries), {accepted_sha})
        entry = entries[accepted_sha]
        self.assertIsInstance(entry, ManifestEntry)
        self.assertEqual(
            entry.observed_utc,
            datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(entry.night, "2026-09-25")

    def test_csv_manifest_retains_existing_hash_time_convention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.csv"
            with path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(
                    output, fieldnames=("source_url", "sha256", "utc_mid")
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "source_url": "https://skycam.mmto.arizona.edu/skycam/archive/a.jpg",
                            "sha256": "f" * 64,
                            "utc_mid": "2026-09-26T05:00:00Z",
                        },
                        {
                            "source_url": "https://other.example/skycam/archive/b.jpg",
                            "sha256": "1" * 64,
                            "utc_mid": "2026-09-26T05:20:00Z",
                        },
                        {
                            "source_url": "https://skycam.mmto.arizona.edu/not-archive/c.jpg",
                            "sha256": "2" * 64,
                            "utc_mid": "2026-09-26T05:40:00Z",
                        },
                    ]
                )

            entries = read_mmto_manifest(path)

        self.assertEqual(set(entries), {"f" * 64})
        self.assertEqual(entries["f" * 64].night, "2026-09-25")

    def test_conflicting_hash_times_fail_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.csv"
            with path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(
                    output, fieldnames=("source_url", "sha256", "utc_mid")
                )
                writer.writeheader()
                for minute in ("00", "20"):
                    writer.writerow(
                        {
                            "source_url": "https://skycam.mmto.arizona.edu/skycam/archive/a.jpg",
                            "sha256": "a" * 64,
                            "utc_mid": f"2026-09-26T05:{minute}:00Z",
                        }
                    )

            with self.assertRaisesRegex(ValueError, "Conflicting manifest UTC times"):
                read_mmto_manifest(path)


class CalibrationDatabaseLoadingTests(unittest.TestCase):
    def test_snapshot_selects_latest_success_before_quality_and_preserves_database(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "stars.sqlite"
            manifest_path = root / "manifest.sqlite"
            create_run_database(database_path)
            create_manifest_database(manifest_path)
            source_sha = "a" * 64
            missing_sha = "b" * 64
            catalogue_sha = "c" * 64
            insert_manifest_row(
                manifest_path,
                remote_url="https://skycam.mmto.arizona.edu/skycam/archive/a.fits.bz2",
                sha256=source_sha,
            )

            insert_run(
                database_path,
                "old-success",
                "2026-09-26T05:01:00+00:00",
                source_sha,
                catalogue_sha,
                0,
            )
            insert_measurement(
                database_path,
                "old-success",
                1,
                "star-1",
                photometry_payload(r_rate=999.0),
            )
            insert_run(
                database_path,
                "new-success",
                "2026-09-26T05:02:00+00:00",
                source_sha,
                catalogue_sha,
                0,
            )
            insert_measurement(
                database_path,
                "new-success",
                1,
                "star-1",
                photometry_payload(r_rate=100.0, g_saturated=True),
            )
            insert_measurement(
                database_path,
                "new-success",
                2,
                "broken-star",
                "{not valid json",
            )
            insert_run(
                database_path,
                "newer-failed",
                "2026-09-26T05:03:00+00:00",
                source_sha,
                catalogue_sha,
                1,
            )
            insert_run(
                database_path,
                "missing-manifest",
                "2026-09-26T05:04:00+00:00",
                missing_sha,
                catalogue_sha,
                0,
            )

            digest_before = hashlib.sha256(database_path.read_bytes()).hexdigest()
            loaded = load_mmto_calibration_data(database_path, manifest_path)
            digest_after = hashlib.sha256(database_path.read_bytes()).hexdigest()

        self.assertIsInstance(loaded, LoadedCalibrationData)
        self.assertEqual(digest_after, digest_before)
        self.assertEqual(loaded.selected_run_ids, ("new-success",))
        self.assertEqual(
            {(row.star_id, row.channel) for row in loaded.measurements},
            {("star-1", "R"), ("star-1", "B")},
        )
        r_measurement = next(
            row for row in loaded.measurements if row.channel == "R"
        )
        self.assertEqual(r_measurement.count_rate_adu_per_s, 100.0)
        self.assertAlmostEqual(r_measurement.machine_magnitude, -5.0, 12)
        reasons = {
            reason
            for audit in loaded.audit_rows
            for reason in audit.exclusion_reasons
        }
        self.assertIn("channel_saturated", reasons)
        self.assertIn("malformed_values_json", reasons)
        self.assertIn("missing_manifest_hash", reasons)
        self.assertIn("failed_run", reasons)
        self.assertIn("superseded_successful_run", reasons)

    def test_missing_catalogue_identity_is_audited_not_fitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "stars.sqlite"
            manifest_path = root / "manifest.sqlite"
            create_run_database(database_path)
            create_manifest_database(manifest_path)
            source_sha = "d" * 64
            insert_manifest_row(
                manifest_path,
                remote_url="https://skycam.mmto.arizona.edu/skycam/archive/d.fits.bz2",
                sha256=source_sha,
            )
            insert_run(
                database_path,
                "missing-catalogue",
                "2026-09-26T05:00:00+00:00",
                source_sha,
                "",
                0,
            )
            insert_measurement(
                database_path,
                "missing-catalogue",
                1,
                "star-1",
                photometry_payload(r_rate=100.0),
            )

            loaded = load_mmto_calibration_data(database_path, manifest_path)

        self.assertFalse(loaded.measurements)
        self.assertTrue(
            any(
                "missing_catalogue_sha256" in row.exclusion_reasons
                for row in loaded.audit_rows
            )
        )


class CalibrationOutputTests(unittest.TestCase):
    def test_writer_creates_complete_sidecar_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sidecar"
            summary = write_calibration_outputs(
                synthetic_loaded_data(10), output, CalibrationConfig()
            )

            expected = {
                "calibration_manifest.json",
                "image_extinction_fits.csv",
                "nightly_extinction_coefficients.csv",
                "calibration_star_measurements.csv",
                "image_zero_points.csv",
                "corrected_stellar_photometry.csv",
                "extinction_diagnostics.png",
                "extinction_diagnostics.pdf",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected)
            self.assertEqual(summary["calibrated_nights"], 1)
            manifest = json.loads(
                (output / "calibration_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["formulae"]["machine_magnitude"],
                "m_machine = -2.5 log10(count_rate_adu_per_s)",
            )
            self.assertEqual(
                manifest["formulae"]["corrected_magnitude"],
                "m_corrected = m_machine - Z_fixed - k_night X",
            )
            with (output / "image_zero_points.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                self.assertEqual(
                    next(csv.reader(source)),
                    [
                        "night",
                        "channel",
                        "observed_utc",
                        "source_sha256",
                        "catalogue_sha256",
                        "model",
                        "status",
                        "zero_point_magnitude",
                        "uncertainty_magnitude",
                        "rms_magnitude",
                        "star_count",
                        "extinction_mag_per_airmass",
                    ],
                )

    def test_insufficient_night_keeps_audit_rows_without_corrected_values(self) -> None:
        data = synthetic_loaded_data(9)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sidecar"
            summary = write_calibration_outputs(data, output, CalibrationConfig())
            with (output / "calibration_star_measurements.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                audit = list(csv.DictReader(source))
            with (output / "corrected_stellar_photometry.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                corrected = list(csv.DictReader(source))

        self.assertEqual(len(audit), len(data.audit_rows))
        self.assertEqual(summary["insufficient_nights"], 1)
        self.assertTrue(corrected)
        self.assertTrue(
            all(
                row["status"] == "missing_nightly_extinction"
                and row["corrected_magnitude"] == ""
                for row in corrected
            )
        )

    def test_faint_and_high_airmass_rows_are_audited_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sidecar"
            write_calibration_outputs(
                synthetic_loaded_data(
                    10, add_faint=True, add_high_airmass=True
                ),
                output,
                CalibrationConfig(),
            )
            with (output / "calibration_star_measurements.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                rows = list(csv.DictReader(source))

        faint = [row for row in rows if row["star_id"] == "faint-star"]
        high = [row for row in rows if row["star_id"] == "high-airmass-star"]
        self.assertTrue(faint and high)
        self.assertTrue(
            all("catalogue_magnitude_not_bright" in row["fit_exclusion_reasons"] for row in faint)
        )
        self.assertTrue(
            all("airmass_above_reference_limit" in row["fit_exclusion_reasons"] for row in high)
        )
        self.assertTrue(all(row["included_in_adopted_fit"] == "False" for row in faint + high))

    def test_nonempty_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sidecar"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("original", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "nonempty"):
                write_calibration_outputs(
                    synthetic_loaded_data(10), output, CalibrationConfig()
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(output.iterdir()), [sentinel])


class CalibrationCliTests(unittest.TestCase):
    def test_cli_uses_repo_sqlite_manifest_default_and_timestamped_output(self) -> None:
        data = synthetic_loaded_data(10)
        database = calibration_cli.ROOT / "results" / "stars.sqlite"
        expected_manifest = (
            calibration_cli.ROOT / "raw_allsky_samples" / "manifest.sqlite"
        )
        summary = {
            "calibrated_nights": 1,
            "insufficient_nights": 0,
            "valid_measurements": len(data.measurements),
            "audit_rows": len(data.audit_rows),
            "output": "unused",
        }
        stdout = io.StringIO()
        with (
            patch.object(calibration_cli, "default_database", return_value=database),
            patch.object(
                calibration_cli,
                "load_mmto_calibration_data",
                return_value=data,
            ) as load_mock,
            patch.object(
                calibration_cli,
                "write_calibration_outputs",
                return_value=summary,
            ) as write_mock,
            redirect_stdout(stdout),
        ):
            result = main([])

        self.assertEqual(result, 0)
        load_mock.assert_called_once_with(database.resolve(), expected_manifest.resolve())
        output = write_mock.call_args.args[1]
        self.assertEqual(output.parent, database.parent / "extinction-calibration")
        self.assertRegex(output.name, r"^\d{8}T\d{12}Z$")
        self.assertIn("Reference defaults:", stdout.getvalue())
        self.assertIn("Calibrated night/channels: 1; insufficient: 0", stdout.getvalue())

    def test_cli_forwards_explicit_database_manifest_and_output(self) -> None:
        data = synthetic_loaded_data(9)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "custom.sqlite"
            manifest = root / "custom-manifest.sqlite"
            output = root / "custom-output"
            summary = {
                "calibrated_nights": 0,
                "insufficient_nights": 1,
                "valid_measurements": len(data.measurements),
                "audit_rows": len(data.audit_rows),
                "output": str(output),
            }
            stdout = io.StringIO()
            with (
                patch.object(
                    calibration_cli,
                    "load_mmto_calibration_data",
                    return_value=data,
                ) as load_mock,
                patch.object(
                    calibration_cli,
                    "write_calibration_outputs",
                    return_value=summary,
                ) as write_mock,
                redirect_stdout(stdout),
            ):
                result = main(
                    [
                        "--database",
                        str(database),
                        "--manifest",
                        str(manifest),
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(result, 0)
        load_mock.assert_called_once_with(database.resolve(), manifest.resolve())
        self.assertEqual(write_mock.call_args.args[1], output.resolve())
        self.assertIn("Calibrated night/channels: 0; insufficient: 1", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
