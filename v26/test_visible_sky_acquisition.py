"""Bounded automatic acquisition for new visible-sky camera installations."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from visible_sky_acquisition import plan_managed_acquisition


class ManagedVisibleSkyAcquisitionTests(unittest.TestCase):
    @staticmethod
    def _registry(root: Path) -> None:
        (root / "sources.json").write_text(
            json.dumps({
                "schema_version": 1,
                "sources": [{
                    "id": "new-source",
                    "aliases": [],
                    "name": "New raw camera",
                    "status": "SUCCESS",
                    "adapter": "mmto",
                    "automatic_acquisition": True,
                    "archive_roots": ["https://example.invalid/archive/"],
                    "documentation": [],
                    "licensing": "fixture",
                    "cameras": [{
                        "id": "new-camera",
                        "name": "New camera",
                        "timezone": "UTC",
                        "latitude_deg": 50.0,
                        "longitude_deg": 10.0,
                        "elevation_m": 100.0,
                    }],
                }],
            }),
            encoding="utf-8",
        )

    def test_new_camera_gets_ten_bounded_night_download_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._registry(root)
            requests = plan_managed_acquisition(
                root,
                calibrated_keys=frozenset(),
                now_utc=datetime(2026, 11, 16, 18, tzinfo=timezone.utc),
            )

        self.assertEqual(
            [request.night_date for request in requests],
            [f"2026-11-{day:02d}" for day in range(6, 16)],
        )
        self.assertTrue(all(request.source_id == "new-source" for request in requests))
        self.assertTrue(all(request.camera_id == "new-camera" for request in requests))
        self.assertTrue(all("--max-files" in request.arguments for request in requests))
        self.assertTrue(all("10" in request.arguments for request in requests))
        self.assertTrue(all("--backfill-missing" in request.arguments for request in requests))
        self.assertTrue(all("--sun-below" in request.arguments for request in requests))

    def test_registered_camera_never_requests_more_calibration_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._registry(root)
            requests = plan_managed_acquisition(
                root,
                calibrated_keys=frozenset({("new-source", "new-camera")}),
                now_utc=datetime(2026, 11, 16, 18, tzinfo=timezone.utc),
            )

        self.assertEqual(requests, ())


if __name__ == "__main__":
    unittest.main()
