"""Tests for the frozen v22 VSX association builder."""
from __future__ import annotations

import math
import unittest

from v22.scripts.build_vsx_crossmatch import (
    classify_candidate_rows,
    period_is_positive_finite,
    propagate_to_j2000,
)


class VsxCrossmatchTests(unittest.TestCase):
    def test_propagates_catalogue_position_to_j2000(self):
        ra, dec = propagate_to_j2000(
            ra_deg=180.0,
            dec_deg=0.0,
            reference_epoch_jyear=2016.0,
            pm_ra_cosdec_mas_per_year=1000.0,
            pm_dec_mas_per_year=0.0,
        )

        self.assertAlmostEqual(ra, 180.0 - 16.0 / 3600.0, places=7)
        self.assertAlmostEqual(dec, 0.0, places=7)

    def test_missing_catalogue_proper_motion_preserves_position(self):
        ra, dec = propagate_to_j2000(
            ra_deg=123.5,
            dec_deg=-42.25,
            reference_epoch_jyear=2016.0,
            pm_ra_cosdec_mas_per_year="",
            pm_dec_mas_per_year="",
        )

        self.assertAlmostEqual(ra, 123.5, places=10)
        self.assertAlmostEqual(dec, -42.25, places=10)

    def test_exact_one_arcsecond_unique_confirmed_match_is_eligible(self):
        rows = [{
            "vsx_oid": "101",
            "vsx_flag": "0",
            "period_days": "50.0",
            "match_distance_arcsec": "1.0",
        }]

        classified = classify_candidate_rows(rows, match_radius_arcsec=1.0)

        self.assertEqual(classified[0]["selection_status"], "eligible_catalogue_variable")
        self.assertEqual(classified[0]["candidate_oid_count"], 1)

    def test_zero_separation_is_not_treated_as_missing(self):
        rows = [{
            "vsx_oid": "101",
            "vsx_flag": "0",
            "period_days": "2.0",
            "match_distance_arcsec": "0.0",
        }]

        classified = classify_candidate_rows(rows)

        self.assertEqual(classified[0]["candidate_oid_count"], 1)
        self.assertEqual(classified[0]["selection_status"], "eligible_catalogue_variable")

    def test_two_distinct_vsx_oids_are_ambiguous(self):
        rows = [
            {"vsx_oid": "101", "vsx_flag": "0", "period_days": "2", "match_distance_arcsec": "0.2"},
            {"vsx_oid": "202", "vsx_flag": "0", "period_days": "3", "match_distance_arcsec": "0.4"},
        ]

        classified = classify_candidate_rows(rows, match_radius_arcsec=1.0)

        self.assertEqual(
            [row["selection_status"] for row in classified],
            ["ambiguous_vsx_oid", "ambiguous_vsx_oid"],
        )
        self.assertEqual({row["candidate_oid_count"] for row in classified}, {2})

    def test_flag_and_period_failures_remain_explicit_audit_rows(self):
        fixtures = (
            ("1", "2.0", "vsx_flag_not_confirmed_variable"),
            ("2", "2.0", "vsx_flag_not_confirmed_variable"),
            ("0", "", "missing_period"),
            ("0", "nan", "invalid_period"),
            ("0", "inf", "invalid_period"),
            ("0", "0", "invalid_period"),
            ("0", "-1", "invalid_period"),
        )
        for index, (flag, period, expected) in enumerate(fixtures):
            with self.subTest(flag=flag, period=period):
                rows = [{
                    "vsx_oid": str(index + 1),
                    "vsx_flag": flag,
                    "period_days": period,
                    "match_distance_arcsec": "0.1",
                }]
                self.assertEqual(
                    classify_candidate_rows(rows)[0]["selection_status"], expected
                )

    def test_positive_finite_period_gate_does_not_apply_plot_limit(self):
        for value in (math.nan, math.inf, 0.0, -1.0):
            with self.subTest(value=value):
                self.assertFalse(period_is_positive_finite(value))
        self.assertTrue(period_is_positive_finite(50.0))


if __name__ == "__main__":
    unittest.main()
