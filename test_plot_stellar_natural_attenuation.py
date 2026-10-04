"""Held-out same-star tests diagnose brightness-dependent response."""
from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest


class StellarNaturalAttenuationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _synthetic_rows(self):
        rows = []
        image_offsets = [0.0, 0.10, -0.05, 0.02, 0.08, -0.03, 0.04, -0.06, 0.06]
        extinction = 0.20
        for image_index, image_offset in enumerate(image_offsets):
            source = f"image-{image_index}"
            for star_index, intercept in enumerate((-4.0, -4.5, -5.0, -5.5, -6.0)):
                airmass = 1.0 + (((2 * image_index + 3 * star_index) % 9) / 4.0)
                magnitude = intercept + image_offset + extinction * airmass
                rows.append({
                    "night": "2026-09-20", "channel": "G",
                    "source_sha256": source, "star_id": f"faint-{star_index}",
                    "airmass": airmass, "machine_magnitude": magnitude,
                    "count_rate_adu_per_s": 10.0 ** (-0.4 * magnitude),
                })

            bright_airmass = 1.0 + image_index / 4.0
            predicted = -10.0 + image_offset + extinction * bright_airmass
            compression = 0.30 if image_index < 3 else 0.0
            observed = predicted + compression
            rows.append({
                "night": "2026-09-20", "channel": "G",
                "source_sha256": source, "star_id": "bright-test",
                "airmass": bright_airmass, "machine_magnitude": observed,
                "count_rate_adu_per_s": 10.0 ** (-0.4 * observed),
            })
        return rows

    def test_faint_controls_predict_held_out_bright_star_compression(self):
        from scripts import plot_stellar_natural_attenuation as attenuation

        tests, fits = attenuation.run_natural_attenuation_test(
            self._synthetic_rows(),
            control_max_count_rate=3000.0,
            min_controls_per_image=3,
            min_observations_per_star=9,
            min_airmass_span=1.0,
        )

        self.assertEqual(len(fits), 1)
        self.assertAlmostEqual(fits[0]["extinction_mag_per_airmass"], 0.20, 8)
        self.assertEqual(len(tests), 3)
        self.assertEqual({row["star_id"] for row in tests}, {"bright-test"})
        self.assertTrue(all(row["sample_role"] == "low_airmass_test" for row in tests))
        for row in tests:
            self.assertAlmostEqual(row["residual_magnitude"], 0.30, 8)
            self.assertGreater(row["predicted_count_rate_adu_per_s"], 3000.0)

    def test_writes_one_rgb_png_and_machine_readable_outputs(self):
        from scripts import plot_stellar_natural_attenuation as attenuation

        rows = []
        for channel, residual in zip("BGR", (0.2, 0.1, -0.1)):
            for index, rate in enumerate((2000.0, 5000.0, 10000.0)):
                rows.append({
                    "night": "2026-09-20", "channel": channel,
                    "source_sha256": f"{channel}-{index}",
                    "star_id": f"star-{channel}", "airmass": 1.0,
                    "predicted_machine_magnitude": -2.5 * math.log10(rate),
                    "predicted_count_rate_adu_per_s": rate,
                    "observed_machine_magnitude": -2.5 * math.log10(rate) + residual,
                    "residual_magnitude": residual,
                    "sample_role": "low_airmass_test",
                })

        output = self.root / "natural_attenuation.png"
        summary = attenuation.write_outputs(
            rows, [], output, control_max_count_rate=2500.0
        )

        self.assertTrue(output.is_file())
        self.assertFalse(output.with_suffix(".pdf").exists())
        self.assertTrue(output.with_suffix(".csv").is_file())
        self.assertTrue(output.with_name("natural_attenuation_summary.json").is_file())
        self.assertEqual(summary["measurement_count"], 9)
        self.assertEqual(summary["control_max_count_rate_adu_per_s"], 2500.0)
        self.assertEqual(summary["channel_measurements"], {"B": 3, "G": 3, "R": 3})
        self.assertEqual(summary["channel_high_signal"]["G"]["star_night_count"], 1)
        self.assertAlmostEqual(
            summary["channel_high_signal"]["G"]["median_residual_magnitude"],
            0.1,
            12,
        )
        self.assertAlmostEqual(
            summary["channel_high_signal"]["G"][
                "observed_to_predicted_count_ratio"
            ],
            10.0 ** (-0.4 * 0.1),
            12,
        )
        figure, axes = attenuation.build_figure(rows)
        import matplotlib.pyplot as plt
        self.addCleanup(plt.close, figure)
        self.assertEqual(len(axes), 3)
        self.assertIn("Predicted count rate", axes[0].get_xlabel())
        self.assertIn("Observed − predicted", axes[0].get_ylabel())
        self.assertEqual(axes[0].get_xscale(), "log")


if __name__ == "__main__":
    unittest.main()
