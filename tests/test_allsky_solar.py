from datetime import datetime, timezone
import unittest

from allsky_download.model import Candidate, Site
from allsky_download.solar import filter_by_solar_altitude, solar_altitude_deg


UTC = timezone.utc


def candidate(stamp: str) -> Candidate:
    observed = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
    filename = observed.strftime("%Y%m%d_%H%M.raw")
    return Candidate(
        "fixture",
        "equator",
        observed,
        stamp,
        f"https://example.test/{filename}",
        filename,
        None,
        {},
    )


class SolarFilterTests(unittest.TestCase):
    def setUp(self):
        self.site = Site("fixture", "equator", "Equator", "UTC", 0.0, 0.0, None)
        self.sites = {("fixture", "equator"): self.site}

    def test_solar_altitude_distinguishes_noon_from_midnight(self):
        midnight = datetime(2026, 3, 20, 0, tzinfo=UTC)
        noon = datetime(2026, 3, 20, 12, tzinfo=UTC)
        self.assertLess(solar_altitude_deg(self.site, midnight), -80.0)
        self.assertGreater(solar_altitude_deg(self.site, noon), 80.0)

    def test_filter_keeps_only_exposures_with_sun_below_horizon(self):
        midnight = candidate("2026-03-20T00:00:00")
        noon = candidate("2026-03-20T12:00:00")
        kept = filter_by_solar_altitude(
            (noon, midnight), self.sites, sun_below_deg=0.0
        )
        self.assertEqual(kept, (midnight,))

    def test_solar_filter_refuses_site_without_latitude_or_longitude(self):
        missing = Site("fixture", "equator", "Unknown", "UTC", None, 0.0, None)
        with self.assertRaisesRegex(ValueError, "latitude and longitude"):
            filter_by_solar_altitude(
                (candidate("2026-03-20T00:00:00"),),
                {("fixture", "equator"): missing},
                sun_below_deg=0.0,
            )


if __name__ == "__main__":
    unittest.main()
