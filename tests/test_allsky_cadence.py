from datetime import date, datetime, timedelta, timezone
import unittest

from allsky_download.cadence import parse_duration, select_candidates, site_date_range
from allsky_download.model import Candidate, DateRange, Site


UTC = timezone.utc


def candidate(camera, stamp, url, size=None, source="trex_rgb"):
    return Candidate(
        source,
        camera,
        datetime.fromisoformat(stamp).replace(tzinfo=UTC),
        stamp,
        url,
        url.rsplit("/", 1)[-1],
        size,
        {},
    )


class CadenceTests(unittest.TestCase):
    def test_duration_units_and_invalid_values(self):
        self.assertEqual(parse_duration("30s"), timedelta(seconds=30))
        self.assertEqual(parse_duration("2.5m"), timedelta(seconds=150))
        self.assertEqual(parse_duration("1h"), timedelta(hours=1))
        for value in ("", "0m", "-1m", "nanm", "infh", "10", "1d"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_site_local_date_range_honours_dst(self):
        site = Site(
            "trex_rgb",
            "gill_rgb-04",
            "Gillam",
            "America/Winnipeg",
            None,
            None,
            None,
        )
        result = site_date_range(
            site, date_value=date(2026, 3, 8), start=None, end=None
        )
        self.assertEqual(result.start_utc.isoformat(), "2026-03-08T06:00:00+00:00")
        self.assertEqual(result.end_utc.isoformat(), "2026-03-09T05:00:00+00:00")

    def test_date_and_range_forms_are_validated(self):
        site = Site("mmto", "mmto-skycam", "MMTO", "America/Phoenix", None, None, None)
        invalid = (
            dict(date_value=None, start=None, end=None),
            dict(date_value=date(2026, 1, 1), start=date(2026, 1, 1), end=date(2026, 1, 2)),
            dict(date_value=None, start=date(2026, 1, 1), end=None),
            dict(date_value=None, start=None, end=date(2026, 1, 2)),
            dict(date_value=None, start=date(2026, 1, 2), end=date(2026, 1, 2)),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                site_date_range(site, **values)

    def test_first_candidate_per_slot_tie_order_and_absolute_cap(self):
        items = [
            candidate("a", "2026-01-01T00:10:02", "https://x/z.h5", 30),
            candidate("a", "2026-01-01T00:00:03", "https://x/b.h5", 20),
            candidate("a", "2026-01-01T00:00:03", "https://x/a.h5", 10),
            candidate("b", "2026-01-01T00:00:01", "https://x/c.h5", None),
        ]
        window = DateRange(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
        )
        result = select_candidates(
            items,
            {("trex_rgb", "a"): window, ("trex_rgb", "b"): window},
            timedelta(minutes=10),
            max_files=2,
        )
        self.assertEqual(
            [item.url for item in result.candidates],
            ["https://x/c.h5", "https://x/a.h5"],
        )
        self.assertEqual(result.eligible_count, 3)
        self.assertTrue(result.truncated)
        self.assertEqual(result.known_bytes, 10)
        self.assertEqual(result.unknown_size_count, 1)

    def test_half_open_boundaries_and_empty_slots_do_not_borrow(self):
        window = DateRange(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 20, tzinfo=UTC),
        )
        items = [
            candidate("a", "2025-12-31T23:59:59", "https://x/before.h5"),
            candidate("a", "2026-01-01T00:10:00", "https://x/boundary.h5"),
            candidate("a", "2026-01-01T00:20:00", "https://x/end.h5"),
        ]
        result = select_candidates(
            items,
            {("trex_rgb", "a"): window},
            timedelta(minutes=10),
            max_files=20,
        )
        self.assertEqual(
            [item.filename for item in result.candidates], ["boundary.h5"]
        )
        self.assertEqual(result.eligible_count, 1)

    def test_newest_mode_keeps_last_slots_for_incremental_cron(self):
        window = DateRange(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
        items = [
            candidate("a", f"2026-01-01T00:{minute:02d}:00", f"https://x/{minute}.h5")
            for minute in (0, 20, 40)
        ]
        result = select_candidates(
            items,
            {("trex_rgb", "a"): window},
            timedelta(minutes=20),
            max_files=1,
            newest=True,
        )
        self.assertEqual([item.filename for item in result.candidates], ["40.h5"])

    def test_model_rejects_naive_timestamp_and_negative_size(self):
        with self.assertRaises(ValueError):
            Candidate("s", "c", datetime(2026, 1, 1), "raw", "https://x/a", "a", 1, {})
        with self.assertRaises(ValueError):
            candidate("c", "2026-01-01T00:00:00", "https://x/a", -1, source="s")


if __name__ == "__main__":
    unittest.main()
