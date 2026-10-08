"""Planet extinction diagnostics use stars of the same measured brightness."""
from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest


class BrightnessMatchedPlanetExtinctionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def _rate(machine_magnitude):
        return 10.0 ** (-0.4 * machine_magnitude)

    def _synthetic_rows(self):
        planets = []
        stars = []
        planet_airmasses = tuple(1.0 + 0.4 * index for index in range(10))
        for index, airmass in enumerate(planet_airmasses):
            image = f"image-{index}"
            planet_magnitude = -8.2 + 0.10 * airmass
            planets.append({
                "nightly_extinction_night": "2026-09-19",
                "channel": "G",
                "planet": "Mars",
                "camera_label": "MMTO skycam",
                "source_sha256": image,
                "planet_airmass": airmass,
                "machine_magnitude": planet_magnitude,
                "count_rate_adu_per_s": self._rate(planet_magnitude),
                "nightly_extinction_mag_per_airmass": 0.50,
            })
            for star_number, slope in enumerate((0.20, 0.25, 0.30), 1):
                star_airmass = airmass + 0.1 * star_number
                star_magnitude = (
                    -7.92
                    + slope * (star_airmass - (2.8 + 0.1 * star_number))
                )
                stars.append({
                    "night": "2026-09-19",
                    "channel": "G",
                    "source_sha256": image,
                    "catalogue_sha256": "catalogue",
                    "star_id": f"star-{star_number}",
                    "airmass": star_airmass,
                    "machine_magnitude": star_magnitude,
                    "count_rate_adu_per_s": self._rate(star_magnitude),
                })
            stars.append({
                "night": "2026-09-19",
                "channel": "G",
                "source_sha256": image,
                "catalogue_sha256": "catalogue",
                "star_id": "too-faint",
                "airmass": airmass,
                "machine_magnitude": -5.0 + 0.9 * airmass,
                "count_rate_adu_per_s": self._rate(-5.0 + 0.9 * airmass),
            })
        stars.append({
            "night": "2026-09-19",
            "channel": "G",
            "source_sha256": "not-a-planet-frame",
            "catalogue_sha256": "catalogue",
            "star_id": "star-2",
            "airmass": 7.0,
            "machine_magnitude": 20.0,
            "count_rate_adu_per_s": self._rate(20.0),
        })
        return stars, planets

    def test_matches_stars_by_median_count_rate_in_exact_planet_frames(self):
        from scripts import plot_brightness_matched_planet_extinction as diagnostic

        stars, planets = self._synthetic_rows()
        rows = diagnostic.measure_brightness_matched_extinction(stars, planets)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["matched_star_count"], 3)
        self.assertEqual(row["matched_star_measurement_count"], 30)
        self.assertEqual(row["planet_input_measurement_count"], 10)
        self.assertEqual(row["planet_measurement_count"], 10)
        self.assertEqual(row["planet_measurements_above_maximum_airmass"], 0)
        self.assertAlmostEqual(row["maximum_airmass"], 5.0, 12)
        self.assertAlmostEqual(row["planet_raw_slope_mag_per_airmass"], 0.10, 12)
        self.assertAlmostEqual(
            row["matched_star_median_slope_mag_per_airmass"], 0.25, 12
        )
        self.assertAlmostEqual(
            row["adopted_extinction_mag_per_airmass"], 0.50, 12
        )
        self.assertAlmostEqual(row["match_half_width_magnitude"], 0.50, 12)
        self.assertNotIn("not-a-planet-frame", row["matched_source_images"])

    def test_retains_an_audit_row_when_planet_sequence_is_too_short(self):
        from scripts import plot_brightness_matched_planet_extinction as diagnostic

        stars, planets = self._synthetic_rows()
        rows = diagnostic.measure_brightness_matched_extinction(stars, planets[:9])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "insufficient_planet_measurements")
        self.assertEqual(rows[0]["planet_measurement_count"], 9)

    def test_excludes_planet_and_stellar_measurements_above_airmass_five(self):
        from scripts import plot_brightness_matched_planet_extinction as diagnostic

        stars, planets = self._synthetic_rows()
        planets.append({
            **planets[-1],
            "source_sha256": "high-airmass-image",
            "planet_airmass": 8.0,
            "machine_magnitude": 50.0,
            "count_rate_adu_per_s": self._rate(50.0),
        })
        for star_number in range(1, 4):
            stars.append({
                **stars[star_number - 1],
                "source_sha256": "high-airmass-image",
                "star_id": f"star-{star_number}",
                "airmass": 8.0,
                "machine_magnitude": 50.0,
                "count_rate_adu_per_s": self._rate(50.0),
            })

        rows = diagnostic.measure_brightness_matched_extinction(stars, planets)

        row = rows[0]
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["planet_input_measurement_count"], 11)
        self.assertEqual(row["planet_measurement_count"], 10)
        self.assertEqual(row["planet_measurements_above_maximum_airmass"], 1)
        self.assertLessEqual(row["planet_airmass_max"], 5.0)
        self.assertAlmostEqual(row["planet_raw_slope_mag_per_airmass"], 0.10, 12)
        self.assertAlmostEqual(
            row["matched_star_median_slope_mag_per_airmass"], 0.25, 12
        )

    def test_figure_compares_matched_and_adopted_slopes_with_planet_style(self):
        import matplotlib.pyplot as plt
        from scripts import plot_brightness_matched_planet_extinction as diagnostic

        stars, planets = self._synthetic_rows()
        rows = diagnostic.measure_brightness_matched_extinction(stars, planets)
        figure, axes = diagnostic.build_figure(rows)
        self.addCleanup(plt.close, figure)

        self.assertEqual(len(axes), 3)
        green = axes[1]
        self.assertIn("Raw planet slope", green.get_xlabel())
        self.assertIn("stellar slope", green.get_ylabel())
        self.assertIn("G", green.get_title())
        self.assertTrue(any(
            line.get_linestyle() == "--"
            and math.isclose(line.get_xdata()[0], line.get_ydata()[0])
            for line in green.lines
        ))
        self.assertGreaterEqual(len(green.collections), 2)


if __name__ == "__main__":
    unittest.main()
