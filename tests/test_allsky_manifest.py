from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from allsky_download.http import DownloadedFile
from v24.allsky_download_v24.manifest import Manifest, OutputLockedError, output_lock
from allsky_download.model import Candidate


def make_candidate(url="https://example.test/raw.fit"):
    return Candidate(
        "mmto",
        "mmto-skycam",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "2026-01-01T00:00:00Z",
        url,
        "raw.fit",
        4,
        {},
    )


class ManifestTests(unittest.TestCase):
    def test_existing_schema_is_migrated_with_nullable_assignment_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.sqlite"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE downloads (
                      remote_url TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                      camera_id TEXT NOT NULL, observed_utc TEXT NOT NULL,
                      observed_raw TEXT NOT NULL, remote_filename TEXT NOT NULL,
                      local_path TEXT, advertised_bytes INTEGER,
                      observed_bytes INTEGER, sha256 TEXT,
                      download_status TEXT NOT NULL,
                      validation_status TEXT NOT NULL,
                      attempted_utc TEXT NOT NULL, error TEXT,
                      inspector_kind TEXT, inspection_id TEXT
                    )
                    """
                )
            with Manifest(path) as manifest:
                columns = {
                    row[1]
                    for row in manifest.connection.execute("PRAGMA table_info(downloads)")
                }
            self.assertTrue(
                {
                    "installation_assignment_status",
                    "installation_id",
                    "installation_assignment_error",
                }.issubset(columns)
            )

    def test_assignment_status_is_recorded_without_changing_verified_download(self):
        candidate = make_candidate()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "raw.fit"
            original.write_bytes(b"abcd")
            digest = hashlib.sha256(b"abcd").hexdigest()
            with Manifest(root / "manifest.sqlite") as manifest:
                manifest.record_attempt(candidate)
                manifest.record_success(
                    candidate, DownloadedFile(original, 4, digest), root
                )
                manifest.record_assignment_failure(
                    candidate.url, "installation-a", "detector mismatch"
                )
                row = manifest.connection.execute(
                    """
                    SELECT download_status, validation_status,
                           installation_assignment_status, installation_id,
                           installation_assignment_error
                    FROM downloads
                    """
                ).fetchone()
            self.assertEqual(
                row,
                (
                    "downloaded",
                    "verified",
                    "unassigned",
                    "installation-a",
                    "detector mismatch",
                ),
            )

    def test_success_is_reused_only_after_size_and_checksum_verification(self):
        candidate = make_candidate()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "mmto" / "mmto-skycam" / "raw.fit"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"abcd")
            digest = hashlib.sha256(b"abcd").hexdigest()
            with Manifest(root / "manifest.sqlite") as manifest:
                manifest.record_attempt(candidate)
                manifest.record_success(
                    candidate, DownloadedFile(original, 4, digest), root
                )
                self.assertEqual(
                    manifest.verified_download(candidate, root),
                    DownloadedFile(original, 4, digest),
                )
                original.write_bytes(b"abce")
                self.assertIsNone(manifest.verified_download(candidate, root))

            with sqlite3.connect(root / "manifest.sqlite") as connection:
                row = connection.execute(
                    "SELECT download_status, validation_status FROM downloads"
                ).fetchone()
            self.assertEqual(row, ("corrupt_local", "checksum_mismatch"))

    def test_failure_and_inspection_are_persisted(self):
        candidate = make_candidate()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.sqlite"
            with Manifest(path) as manifest:
                manifest.record_attempt(candidate)
                manifest.record_failure(candidate, "network unavailable")
                manifest.set_inspection_id(candidate.url, "fits", "inspection-1")
            with sqlite3.connect(path) as connection:
                row = connection.execute(
                    "SELECT download_status, error, inspector_kind, inspection_id FROM downloads"
                ).fetchone()
            self.assertEqual(
                row, ("failed", "network unavailable", "fits", "inspection-1")
            )

    def test_output_lock_refuses_concurrent_holder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with output_lock(root):
                with self.assertRaises(OutputLockedError):
                    with output_lock(root):
                        self.fail("second lock unexpectedly acquired")


if __name__ == "__main__":
    unittest.main()
