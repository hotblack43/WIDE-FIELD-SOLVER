from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from allsky_download.model import DateRange
from allsky_download.registry import SourceRegistry, SourceUnavailableError
from allsky_download.sources.common import parse_directory_index
from allsky_download.sources.mmto import MmtoAdapter
from allsky_download.sources.rubin import RubinPublicSamplesAdapter
from allsky_download.sources.trex_rgb import TrexRgbAdapter


FIXTURES = Path(__file__).parent / "fixtures"
UTC = timezone.utc


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class SourceAdapterTests(unittest.TestCase):
    def test_strict_index_parser_rejects_escape_query_and_cross_origin(self):
        base = "https://example.test/archive/day/"
        html = """<pre>
        <a href='good.fit'>good.fit</a> 01-Jan-2026 00:00 1234
        <a href='../escape.fit'>escape.fit</a> 01-Jan-2026 00:00 2
        <a href='query.fit?x=1'>query.fit</a> 01-Jan-2026 00:00 3
        <a href='https://else.test/cross.fit'>cross.fit</a> 01-Jan-2026 00:00 4
        <a href='nested/deep.fit'>deep.fit</a> 01-Jan-2026 00:00 5
        </pre>"""
        entries = parse_directory_index(html, base)
        self.assertEqual([(item.name, item.size_bytes) for item in entries], [("good.fit", 1234)])

    def test_mmto_uses_verified_local_clock_and_noon_bucket(self):
        adapter = MmtoAdapter("https://skycam.mmto.arizona.edu/skycam/archive/")
        items = adapter.parse_listing(fixture("mmto_listing.html"), date(2026, 3, 15))
        self.assertEqual(items[0].filename, "2026_03_15__12_00_16.fits.bz2")
        self.assertEqual(items[0].observed_at.isoformat(), "2026-03-15T19:00:16+00:00")
        self.assertIsNone(items[0].size_bytes)
        self.assertEqual(len(items), 3)
        self.assertFalse(items[0].url.endswith("/"))

    def test_trex_minute_bundle_names_are_utc_candidates_with_sizes(self):
        adapter = TrexRgbAdapter(
            "https://data.phys.ucalgary.ca/sort_by_project/TREx/RGB/stream0/"
        )
        items = adapter.parse_hour_listing(
            fixture("trex_hour_listing.html"),
            "gill_rgb-04",
            "https://data.phys.ucalgary.ca/sort_by_project/TREx/RGB/stream0/2026/01/15/gill_rgb-04/ut06/",
        )
        self.assertEqual(items[0].observed_at.isoformat(), "2026-01-15T06:00:00+00:00")
        self.assertEqual(items[0].size_bytes, 7891561)
        self.assertTrue(items[0].url.endswith("20260115_0600_gill_rgb-04_full.h5"))
        self.assertEqual([item.filename for item in items], [
            "20260115_0600_gill_rgb-04_full.h5",
            "20260115_0601_gill_rgb-04_full.h5",
        ])

    def test_trex_lists_only_present_camera_and_intersecting_hour(self):
        root = "https://data.example/stream0/"
        adapter = TrexRgbAdapter(root)
        day = root + "2026/01/15/"
        camera = day + "gill_rgb-04/"
        hour = camera + "ut06/"

        class Client:
            def __init__(self):
                self.urls = []

            def get_text(self, url):
                self.urls.append(url)
                return {
                    day: fixture("trex_day_listing.html"),
                    camera: fixture("trex_camera_listing.html"),
                    hour: fixture("trex_hour_listing.html"),
                }[url]

        client = Client()
        site = adapter.sites("gill_rgb-04")[0]
        requested = DateRange(
            datetime(2026, 1, 15, 6, tzinfo=UTC),
            datetime(2026, 1, 15, 7, tzinfo=UTC),
        )
        items = adapter.list_candidates(client, site, requested)
        self.assertEqual(len(items), 2)
        self.assertEqual(client.urls, [day, camera, hour])

    def test_unknown_camera_is_refused(self):
        for adapter in (MmtoAdapter("https://example.test/"), TrexRgbAdapter("https://example.test/"), RubinPublicSamplesAdapter("https://example.test/")):
            with self.subTest(adapter=type(adapter).__name__), self.assertRaises(ValueError):
                adapter.sites("not-a-camera")

    def test_rubin_public_sample_is_static_and_range_filtered(self):
        adapter = RubinPublicSamplesAdapter("https://drive.usercontent.google.com/download")
        site = adapter.sites("rubin-asc")[0]
        requested = DateRange(
            datetime(2025, 6, 25, 4, tzinfo=UTC),
            datetime(2025, 6, 25, 5, tzinfo=UTC),
        )
        items = adapter.list_candidates(None, site, requested)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].filename, "asc2506240487.cr2")
        self.assertEqual(items[0].size_bytes, 28412776)
        self.assertIn("1rk3PsfuUj_9HG8YBR8T2doCgGvOYnBkr", items[0].url)
        outside = DateRange(
            datetime(2025, 6, 26, tzinfo=UTC),
            datetime(2025, 6, 27, tzinfo=UTC),
        )
        self.assertEqual(adapter.list_candidates(None, site, outside), ())


class RegistryTests(unittest.TestCase):
    def test_repository_registry_records_evidence_based_source_statuses(self):
        registry = SourceRegistry.from_json(Path(__file__).parents[1] / "sources.json")
        statuses = {
            source.source_id: source.status for source in registry.listed_sources()
        }
        self.assertEqual(
            statuses,
            {
                "indi_allsky": "RAW NOT FOUND",
                "mmto": "SUCCESS",
                "oasi": "RAW NOT FOUND",
                "presente": "ACCESS RESTRICTED",
                "rubin": "SUCCESS",
                "trex_rgb": "UNSUITABLE",
            },
        )

    def test_alias_resolution_and_unavailable_source(self):
        payload = {
            "schema_version": 1,
            "sources": [
                {
                    "id": "mmto",
                    "aliases": ["mmt"],
                    "name": "MMTO",
                    "status": "UNKNOWN",
                    "adapter": "mmto",
                    "archive_roots": ["https://example.test/mmto/"],
                    "documentation": [],
                    "licensing": "unknown",
                    "cameras": [{
                        "id": "mmto-skycam", "name": "MMTO", "timezone": "America/Phoenix",
                        "latitude_deg": 31.6866666667, "longitude_deg": -110.8841666667,
                        "elevation_m": 2616
                    }],
                },
                {
                    "id": "rubin", "aliases": ["lsst"], "name": "Rubin",
                    "status": "UNKNOWN", "adapter": None, "archive_roots": [],
                    "documentation": [], "licensing": "unknown", "cameras": []
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            registry = SourceRegistry.from_json(path)
        self.assertEqual(registry.resolve_source_id("MMT"), "mmto")
        self.assertEqual(registry.get_adapter("mmt").sites(None)[0].camera_id, "mmto-skycam")
        with self.assertRaises(SourceUnavailableError):
            registry.get_adapter("lsst")


if __name__ == "__main__":
    unittest.main()
