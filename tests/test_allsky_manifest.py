from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from allsky_download.http import DownloadedFile
from allsky_download.manifest import Manifest, OutputLockedError, output_lock
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
