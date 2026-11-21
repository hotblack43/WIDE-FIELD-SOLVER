from __future__ import annotations

import unittest

from .mmto_sidereal_transmission import (
    Exposure,
    TransmissionMeasurement,
    differential_transmission,
    select_sidereal_pairs,
    sidereal_separation_minutes,
)


class SiderealPairTests(unittest.TestCase):
    def test_wraparound_separation(self):
        self.assertAlmostEqual(sidereal_separation_minutes(23.99, 0.01), 1.2)

    def test_pairs_only_distinct_nights_and_includes_tolerance_boundary(self):
        exposures = [
            Exposure("a", "2026-09-18", "2026-09-19T01:00:00Z", 23.99),
            Exposure("same-night", "2026-09-18", "2026-09-19T01:01:00Z", 12.0),
            Exposure("b", "2026-09-19", "2026-09-20T01:00:00Z", 0.01),
        ]
        pairs = select_sidereal_pairs(exposures, tolerance_minutes=1.2)
        self.assertEqual([(pair.first.source_sha256, pair.second.source_sha256) for pair in pairs], [("a", "b")])

    def test_deterministic_one_to_one_selection(self):
        exposures = [
            Exposure("a", "n1", "2026-09-18T00:00:00Z", 1.000),
            Exposure("b", "n2", "2026-09-19T00:00:00Z", 1.010),
            Exposure("c", "n3", "2026-09-20T00:00:00Z", 1.011),
            Exposure("d", "n4", "2026-09-21T00:00:00Z", 1.040),
        ]
        forward = select_sidereal_pairs(exposures, tolerance_minutes=3.0)
        reverse = select_sidereal_pairs(list(reversed(exposures)), tolerance_minutes=3.0)
        expected = [(pair.first.source_sha256, pair.second.source_sha256) for pair in forward]
        self.assertEqual(expected, [("b", "c"), ("a", "d")])
        self.assertEqual([(pair.first.source_sha256, pair.second.source_sha256) for pair in reverse], expected)
        self.assertEqual(len({item for pair in expected for item in pair}), 4)


class DifferentialTransmissionTests(unittest.TestCase):
    def rows(self):
        first = []
        second = []
        for channel in ("G", "R"):
            for index, (a, b) in enumerate(((1.0, 1.2), (2.0, 2.4), (3.0, 2.6))):
                first.append(TransmissionMeasurement(("cat", f"s{index}"), channel, a, 10.25 + index, 20.75 + index))
                second.append(TransmissionMeasurement(("cat", f"s{index}"), channel, b, 11.0 + index, 21.0 + index))
        return first, second

    def test_same_star_differences_are_channel_separated_and_grey_centred(self):
        first, second = self.rows()
        result = differential_transmission(first, second, min_common_stars=3)
        self.assertEqual(result.status_by_channel, {"G": "accepted", "R": "accepted"})
        green = [row for row in result.rows if row.channel == "G"]
        self.assertEqual([round(row.raw_difference_magnitude, 6) for row in green], [0.2, 0.4, -0.4])
        self.assertEqual([round(row.grey_centred_difference_magnitude, 6) for row in green], [0.0, 0.2, -0.6])
        self.assertEqual([(row.x_px, row.y_px) for row in green], [(10.25, 20.75), (11.25, 21.75), (12.25, 22.75)])

    def test_insufficient_coverage_is_explicit_and_not_interpolated(self):
        first, second = self.rows()
        result = differential_transmission(first, second, min_common_stars=4)
        self.assertEqual(result.status_by_channel, {"G": "insufficient_coverage", "R": "insufficient_coverage"})
        self.assertTrue(all(row.status == "insufficient_coverage" for row in result.rows))
        self.assertEqual(len(result.rows), 6)


if __name__ == "__main__":
    unittest.main()
