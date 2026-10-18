"""V21 authoritative MMTO observation sidecar tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest


UTC = timezone.utc


def _manifest(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            """
            CREATE TABLE downloads (
                remote_url TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                observed_utc TEXT NOT NULL,
                sha256 TEXT
            )
            """
        )
        database.execute(
            "INSERT INTO downloads VALUES (?, 'mmto', 'mmto-skycam', ?, ?)",
            ("https://mmto.example/image.fits.bz2", "2026-09-19T09:20:01Z", "a" * 64),
        )


class MMTOObservationSidecarTests(unittest.TestCase):
    def test_record_preserves_listing_time_and_round_trips_by_checksum(self):
        from v21.mmto_observations import observation_for_sha256, record_observation
        from v21.mmto_time import MMTOObservation

        value = MMTOObservation(
            start_utc=datetime(2026, 9, 19, 9, 19, 40, 204800, tzinfo=UTC),
            midpoint_utc=datetime(2026, 9, 19, 9, 19, 50, 204800, tzinfo=UTC),
            exposure_seconds=20.0,
            schema="mmto_skywatch_local_date_obs",
            provenance="FITS DATE-OBS local America/Phoenix + EXPTIME/2",
            instrument="ZWO ASI294MC Pro",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.sqlite"
            _manifest(path)
            with sqlite3.connect(path) as database:
                record_observation(
                    database,
                    "a" * 64,
                    "https://mmto.example/image.fits.bz2",
                    "2026-09-19T09:20:01Z",
                    value,
                )
                recorded = observation_for_sha256(database, "a" * 64)
                listing = database.execute(
                    "SELECT observed_utc FROM downloads"
                ).fetchone()[0]

        self.assertEqual(listing, "2026-09-19T09:20:01Z")
        self.assertEqual(recorded, value)

    def test_identical_record_is_idempotent_but_conflict_is_atomic(self):
        from v21.mmto_observations import observation_for_sha256, record_observation
        from v21.mmto_time import MMTOObservation

        original = MMTOObservation(
            datetime(2026, 10, 16, 12, 19, 44, tzinfo=UTC),
            datetime(2026, 10, 16, 12, 19, 54, tzinfo=UTC),
            20.0,
            "mmto_skywatch_utc_date_beg",
            "FITS DATE-BEG UTC + EXPTIME/2",
            "ZWO ASI294MC Pro",
        )
        conflict = MMTOObservation(
            original.start_utc,
            datetime(2026, 10, 16, 12, 20, 4, tzinfo=UTC),
            40.0,
            original.schema,
            original.provenance,
            original.instrument,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.sqlite"
            _manifest(path)
            with sqlite3.connect(path) as database:
                args = (
                    database,
                    "a" * 64,
                    "https://mmto.example/image.fits.bz2",
                    "2026-10-16T12:20:05Z",
                )
                record_observation(*args, original)
                record_observation(*args, original)
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    record_observation(*args, conflict)
                retained = observation_for_sha256(database, "a" * 64)
                count = database.execute(
                    "SELECT count(*) FROM mmto_v21_observations"
                ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(retained, original)


if __name__ == "__main__":
    unittest.main()
