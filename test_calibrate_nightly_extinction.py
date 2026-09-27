import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.calibrate_nightly_extinction import (
    LoadedCalibrationData,
    ManifestEntry,
    load_mmto_calibration_data,
    read_mmto_manifest,
)


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


if __name__ == "__main__":
    unittest.main()
