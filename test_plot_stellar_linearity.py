"""Stellar linearity diagnostics use corrected counts and clean fit rows."""
from __future__ import annotations

import csv
import math
from pathlib import Path
import tempfile
import unittest


class StellarLinearityPlotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _write_csv(self, name, fields, rows):
        path = self.root / name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_uses_extinction_corrected_zero_point_normalized_counts(self):
        from scripts import plot_stellar_linearity as linearity

        audit_fields = [
            "night", "channel", "source_sha256", "catalogue_sha256",
            "star_id", "saturated", "measurement_method",
            "included_in_adopted_fit",
        ]
        corrected_fields = [
            "night", "channel", "source_sha256", "catalogue_sha256",
            "star_id", "catalogue_magnitude", "count_rate_adu_per_s",
            "airmass", "extinction_mag_per_airmass", "zero_point_magnitude",
            "corrected_magnitude", "status",
        ]
        base = {
            "night": "2026-09-20", "source_sha256": "a" * 64,
            "catalogue_sha256": "b" * 64, "star_id": "Gaia DR3 1",
        }
        audit = self._write_csv(
            "calibration_star_measurements.csv", audit_fields,
            [
                {**base, "channel": "R", "saturated": "False",
                 "measurement_method": "ordinary_aperture",
                 "included_in_adopted_fit": "True"},
                {**base, "channel": "G", "saturated": "True",
                 "measurement_method": "saturated_aperture_lower_bound",
                 "included_in_adopted_fit": "False"},
            ],
        )
        corrected = self._write_csv(
            "corrected_stellar_photometry.csv", corrected_fields,
            [
                {**base, "channel": "R", "catalogue_magnitude": "2.0",
                 "count_rate_adu_per_s": "100", "airmass": "2.0",
                 "extinction_mag_per_airmass": "0.25",
                 "zero_point_magnitude": "-8.0",
                 "corrected_magnitude": "-5.5", "status": "accepted"},
                {**base, "channel": "G", "catalogue_magnitude": "2.0",
                 "count_rate_adu_per_s": "999", "airmass": "2.0",
                 "extinction_mag_per_airmass": "0.25",
                 "zero_point_magnitude": "-8.0",
                 "corrected_magnitude": "-5.5", "status": "accepted"},
            ],
        )
        catalogue = self._write_csv(
            "stars_gaia_dr3_g75.gaia-source.csv",
            [
                "source_id", "phot_g_mean_mag", "phot_bp_mean_mag",
                "phot_rp_mean_mag",
            ],
            [{
                "source_id": "1", "phot_g_mean_mag": "2.0",
                "phot_bp_mean_mag": "2.4", "phot_rp_mean_mag": "1.5",
            }],
        )

        rows = linearity.load_linearity_measurements(audit, corrected, catalogue)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "R")
        self.assertEqual(rows[0]["catalogue_passband"], "Gaia RP")
        self.assertAlmostEqual(rows[0]["catalogue_magnitude"], 1.5, 12)
        # log10(100) + 0.4*k*X + 0.4*zero_point = 2 + .2 - 3.2
        self.assertAlmostEqual(
            rows[0]["normalized_extinction_corrected_log10_count_rate"],
            -1.0,
            12,
        )
        self.assertAlmostEqual(
            rows[0]["extinction_corrected_machine_magnitude"], 2.5, 12
        )
        self.assertAlmostEqual(rows[0]["calibrated_residual_magnitude"], 1.0, 12)

    def test_writes_one_png_with_count_and_residual_axes_for_rgb(self):
        from scripts import plot_stellar_linearity as linearity

        rows = []
        for channel, offset in zip("RGB", (0.0, 0.02, -0.03)):
            for magnitude in (1.0, 2.0, 3.0):
                rows.append({
                    "channel": channel,
                    "catalogue_magnitude": magnitude,
                    "normalized_extinction_corrected_log10_count_rate": (
                        -0.4 * magnitude + offset
                    ),
                    "calibrated_residual_magnitude": -2.5 * offset,
                })

        output = self.root / "stellar_linearity.png"
        summary = linearity.write_plot(rows, output)

        self.assertTrue(output.is_file())
        self.assertFalse(output.with_suffix(".pdf").exists())
        self.assertEqual(summary["measurement_count"], 9)
        self.assertEqual(summary["channels"], {"B": 3, "G": 3, "R": 3})
        figure, axes = linearity.build_figure(rows)
        self.addCleanup(figure.clear)
        self.assertIn("Nightly zero points", figure._suptitle.get_text())
        self.assertEqual(len(axes["count"]), 3)
        self.assertEqual(len(axes["residual"]), 3)
        self.assertIn("catalogue magnitude", axes["residual"][0].get_xlabel())
        self.assertIn("machine magnitude", axes["count"][0].get_ylabel())
        self.assertTrue(any(
            math.isclose(
                (line.get_ydata()[-1] - line.get_ydata()[0])
                / (line.get_xdata()[-1] - line.get_xdata()[0]),
                1.0,
                abs_tol=1e-12,
            )
            for line in axes["count"][0].lines
        ))


if __name__ == "__main__":
    unittest.main()
