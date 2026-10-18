from __future__ import annotations

import math
import time
import unittest

import numpy as np

from scripts.nightly_extinction import StellarMeasurement
from .mmto_nightly_extinction import fit_grey_extinction


def measurement(star: int, image: int, airmass: float, delta_mag: float) -> StellarMeasurement:
    catalogue_magnitude = 2.0 + 0.1 * star
    machine_magnitude = catalogue_magnitude + delta_mag
    rate = 10 ** (-machine_magnitude / 2.5)
    return StellarMeasurement(
        night="2026-09-19", source_sha256=f"image-{image}",
        catalogue_sha256="catalogue", star_id=f"star-{star}", channel="G",
        catalogue_magnitude=catalogue_magnitude,
        count_rate_adu_per_s=rate, count_rate_uncertainty_adu_per_s=None,
        airmass=airmass, saturated=False,
        measurement_method="ordinary_aperture", observed_utc=f"2026-09-19T0{image}:00:00+00:00",
    )


class GreyExtinctionTests(unittest.TestCase):
    def synthetic(self):
        intercepts = np.array([-11.3, -11.1, -10.9, -10.7, -10.5])
        offsets = np.array([-0.18, 0.07, 0.20, -0.09])
        slope = 0.24
        rows = []
        for image in range(4):
            for star in range(5):
                airmass = 1.05 + 0.22 * image + 0.07 * star + 0.20 * image * star
                value = intercepts[star] + slope * airmass + offsets[image]
                if image == 2 and star == 4:
                    value += 4.0
                rows.append(measurement(star, image, airmass, value))
        return rows, intercepts, offsets, slope

    def test_recovers_shared_slope_star_intercepts_and_grey_offsets_with_outlier(self):
        rows, intercepts, offsets, slope = self.synthetic()
        fit = fit_grey_extinction(rows, min_stars=3, min_images=3, loss_scale_mag=0.08)
        self.assertEqual(fit.status, "accepted")
        self.assertAlmostEqual(fit.extinction_mag_per_airmass, slope, delta=0.025)
        self.assertAlmostEqual(sum(fit.image_offsets.values()), 0.0, places=10)
        for index, expected in enumerate(offsets):
            self.assertAlmostEqual(fit.image_offsets[f"image-{index}"], expected, delta=0.04)
        for index, expected in enumerate(intercepts):
            self.assertAlmostEqual(fit.star_intercepts[("catalogue", f"star-{index}")], expected, delta=0.04)

    def test_keeps_fixed_sample_and_reports_uncertainty(self):
        rows, _, _, _ = self.synthetic()
        fit = fit_grey_extinction(rows, min_stars=3, min_images=3)
        self.assertEqual(fit.sample_count, len(rows))
        self.assertEqual(len(fit.residuals), len(rows))
        self.assertIsNotNone(fit.extinction_uncertainty)
        self.assertEqual(set(fit.image_offset_uncertainties), set(fit.image_offsets))
        self.assertGreater(fit.design_rank, 0)

    def test_keeps_singleton_edge_star_when_repeated_network_identifies_fit(self):
        rows, _, _, slope = self.synthetic()
        rows.append(measurement(99, 0, 1.37, -8.2 + slope * 1.37))
        fit = fit_grey_extinction(
            rows, min_stars=3, min_images=3, loss_scale_mag=0.08
        )
        self.assertEqual(fit.status, "accepted")
        self.assertEqual(fit.sample_count, len(rows))
        self.assertIn(("catalogue", "star-99"), fit.star_intercepts)
        self.assertEqual(len(fit.residuals), len(rows))

    def test_rejects_airmass_that_is_confounded_with_image_offsets(self):
        rows = []
        for image in range(3):
            for star in range(3):
                x = 1.0 + 0.3 * image
                rows.append(measurement(star, image, x, -11 + 0.2 * x))
        fit = fit_grey_extinction(rows, min_stars=3, min_images=3)
        self.assertEqual(fit.status, "deficient_airmass_leverage")
        self.assertIsNone(fit.extinction_mag_per_airmass)

    def test_rejects_large_exactly_confounded_airmass_after_sparse_projection(self):
        generator = np.random.default_rng(42)
        star_airmass = generator.uniform(0.0, 20.0, 3000)
        image_airmass = generator.uniform(0.0, 0.3, 40)
        rows = []
        for star in range(3000):
            for image in generator.choice(40, size=5, replace=False):
                airmass = 1.0 + star_airmass[star] + image_airmass[image]
                delta_mag = (
                    -11.0 + 0.2 * airmass + 0.01 * math.sin(star)
                    + 0.02 * math.cos(image)
                )
                rows.append(measurement(star, int(image), airmass, delta_mag))

        fit = fit_grey_extinction(rows, min_stars=20, min_images=3)

        self.assertEqual(fit.status, "deficient_airmass_leverage")
        self.assertIsNone(fit.extinction_mag_per_airmass)

    def test_rejects_too_few_images_or_stars(self):
        rows = [measurement(star, 0, 1.0 + star * 0.1, -11) for star in range(3)]
        fit = fit_grey_extinction(rows, min_stars=3, min_images=2)
        self.assertEqual(fit.status, "insufficient_images")

    def test_accepts_exact_zero_response_from_lsqr_initialization(self):
        rows = [
            measurement(
                star, image,
                1.0 + 0.1 * image + 0.05 * star + 0.03 * image * star,
                0.0,
            )
            for image in range(3)
            for star in range(5)
        ]

        fit = fit_grey_extinction(rows, min_stars=3, min_images=3)

        self.assertEqual(fit.status, "accepted")
        self.assertAlmostEqual(fit.extinction_mag_per_airmass, 0.0, places=12)
        self.assertTrue(all(abs(value) < 1e-12 for value in fit.residuals))

    def test_large_nightly_network_avoids_dense_solver_failure(self):
        offsets = (-0.18, 0.07, 0.11)
        rows = []
        for image in range(3):
            for star in range(2000):
                airmass = 1.02 + 0.11 * image + 0.003 * star + 0.0007 * image * star
                noise = 0.005 * math.sin(0.37 * star + image)
                outlier = 4.0 if image == 2 and star == 1999 else 0.0
                delta_mag = (
                    -11.0 + 0.0002 * star + 0.24 * airmass
                    + offsets[image] + noise + outlier
                )
                rows.append(measurement(star, image, airmass, delta_mag))

        started = time.monotonic()
        fit = fit_grey_extinction(
            rows, min_stars=20, min_images=3, loss_scale_mag=0.08
        )
        elapsed = time.monotonic() - started

        self.assertEqual(fit.status, "accepted")
        self.assertAlmostEqual(fit.extinction_mag_per_airmass, 0.24, delta=0.001)
        self.assertEqual(fit.sample_count, len(rows))
        self.assertEqual(len(fit.residuals), len(rows))
        self.assertGreater(fit.extinction_uncertainty, 0.0)
        for image, expected in enumerate(offsets):
            self.assertAlmostEqual(
                fit.image_offsets[f"image-{image}"], expected, delta=0.002
            )
        self.assertLess(elapsed, 10.0)


if __name__ == "__main__":
    unittest.main()
