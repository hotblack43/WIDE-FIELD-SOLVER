"""Count-rate and saturation-wing photometry regressions."""
import unittest

import numpy as np

from point_star_photometry import measure_channel


class ChannelPhotometryTests(unittest.TestCase):
    def test_unsaturated_aperture_count_rate_is_direct_measurement(self):
        yy, xx = np.mgrid[:31, :31]
        pixels = 100. + 900.*np.exp(-((xx-15.2)**2+(yy-14.8)**2)/(2*1.4**2))
        answer = measure_channel(
            pixels, np.isfinite(pixels), np.zeros(pixels.shape, bool),
            x=15.2, y=14.8, aperture_radius=5., exposure_seconds=2.)
        self.assertEqual(answer['measurement_method'], 'aperture')
        self.assertFalse(answer['saturated'])
        self.assertAlmostEqual(answer['count_rate_adu_per_s'],
                               answer['aperture_counts_adu']/2.)
        self.assertEqual(answer['wing_fit_status'], 'not_needed')

    def test_clipped_moffat_recovers_centroid_and_keeps_model_separate(self):
        yy, xx = np.mgrid[:51, :51]
        x0, y0, amplitude, alpha, beta, background = 25.35, 24.65, 50000., 2.2, 2.7, 120.
        radius2 = ((xx-x0)**2+(yy-y0)**2)/alpha**2
        pristine = background + amplitude*(1.+radius2)**(-beta)
        pixels = np.minimum(pristine, 4095.)
        saturated = pristine >= 4095.
        answer = measure_channel(
            pixels, np.isfinite(pixels), saturated,
            x=25., y=25., aperture_radius=8., exposure_seconds=4.)
        expected_total = amplitude*np.pi*alpha**2/(beta-1.)
        self.assertEqual(answer['measurement_method'], 'saturated_aperture_lower_bound')
        self.assertTrue(answer['saturated'])
        self.assertEqual(answer['wing_fit_status'], 'modelled_from_unsaturated_wings')
        self.assertAlmostEqual(answer['wing_fit_x_px'], x0, delta=.12)
        self.assertAlmostEqual(answer['wing_fit_y_px'], y0, delta=.12)
        self.assertAlmostEqual(answer['wing_fit_total_counts_adu']/expected_total, 1., delta=.08)
        self.assertAlmostEqual(answer['wing_fit_count_rate_adu_per_s'],
                               answer['wing_fit_total_counts_adu']/4.)
        self.assertGreater(answer['wing_fit_unsaturated_pixels'], 20)
        self.assertGreater(answer['saturated_pixels_in_aperture'], 0)


if __name__ == '__main__':
    unittest.main()
