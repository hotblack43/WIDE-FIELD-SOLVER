from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest
import warnings

import numpy as np
from erfa import ErfaWarning

from . import mmto_validation
from .mmto_validation import (
    known_airmass,
    known_zenith_unit_vector,
    planet_epoch_comparison,
    stellar_epoch_comparison,
    validate_blind_zenith,
)


UTC = timezone.utc


class MMTOValidationTests(unittest.TestCase):
    def setUp(self):
        self.midpoint = datetime(2026, 9, 19, 2, 20, 0, tzinfo=UTC)

    def test_predicted_zenith_has_known_site_declination(self):
        vector = known_zenith_unit_vector(self.midpoint)
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=12)
        result = validate_blind_zenith(vector, self.midpoint)
        self.assertLess(result["zenith_separation_deg"], 1e-8)
        self.assertAlmostEqual(result["derived_latitude_deg"], 31.6866666667, places=7)
        self.assertAlmostEqual(result["latitude_minus_known_deg"], 0.0, places=7)

    def test_known_airmass_is_one_at_predicted_zenith(self):
        vector = known_zenith_unit_vector(self.midpoint)
        ra = np.degrees(np.arctan2(vector[1], vector[0])) % 360.0
        dec = np.degrees(np.arcsin(vector[2]))
        result = known_airmass(ra, dec, self.midpoint)
        self.assertGreater(result["altitude_deg"], 89.99)
        self.assertAlmostEqual(result["airmass"], 1.0, places=3)
        self.assertIn("refraction_toward_zenith_position_angle_deg", result)

    def test_known_airmass_batch_matches_scalar_results(self):
        batch_function = getattr(mmto_validation, "known_airmass_batch", None)
        self.assertIsNotNone(batch_function)
        coordinates = ((45.0, 20.0), (180.0, -15.0), (300.0, 55.0))
        expected = [known_airmass(ra, dec, self.midpoint) for ra, dec in coordinates]

        actual = batch_function(
            [ra for ra, _ in coordinates],
            [dec for _, dec in coordinates],
            self.midpoint,
        )

        self.assertEqual(len(actual), len(expected))
        for batch_row, scalar_row in zip(actual, expected, strict=True):
            self.assertEqual(batch_row.keys(), scalar_row.keys())
            for key in ("altitude_deg", "airmass", "parallactic_angle_deg"):
                if scalar_row[key] is None:
                    self.assertIsNone(batch_row[key])
                else:
                    self.assertAlmostEqual(batch_row[key], scalar_row[key], places=10)

    def test_stellar_epoch_difference_is_post_fit_only(self):
        result = stellar_epoch_comparison(2025.0, self.midpoint)
        self.assertFalse(result["used_in_fit"])
        self.assertLess(result["stellar_minus_header_years"], 0.0)
        self.assertGreater(result["absolute_difference_days"], 365.0)

    def test_old_stellar_epoch_does_not_emit_leap_second_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = stellar_epoch_comparison(1937.3238904472876, self.midpoint)

        erfa_warnings = [
            warning for warning in caught
            if issubclass(warning.category, ErfaWarning)
        ]
        self.assertEqual(erfa_warnings, [])
        self.assertGreater(result["absolute_difference_days"], 80 * 365.0)

    def test_planet_comparison_preserves_blind_candidates(self):
        record = {
            "status": "planet_epoch_ambiguous",
            "metadata_used": False,
            "candidates": [
                {"epoch_tdb": "2026-09-19T02:21:00 TDB", "jd_tdb": 2461302.598},
                {"epoch_tdb": "2025-09-19T02:20:00 TDB", "jd_tdb": 2460937.597},
            ],
        }
        original = deepcopy(record)
        rows = planet_epoch_comparison(record, self.midpoint)
        self.assertEqual(record, original)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["used_in_fit"] is False for row in rows))
        self.assertLess(abs(rows[0]["planet_minus_header_seconds"]), 120.0)
        self.assertGreater(abs(rows[1]["planet_minus_header_seconds"]), 300 * 86400.0)


if __name__ == "__main__":
    unittest.main()
