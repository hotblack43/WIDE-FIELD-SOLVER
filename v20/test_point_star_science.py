import tempfile
from pathlib import Path
import unittest

import numpy as np

from point_star_science import (_machine_magnitude_from_rate, _robust_line,
                                classify_image_colour, planet_confidence)
from point_star_report import report_sections, table_rows


class PointStarScienceTests(unittest.TestCase):
    def test_machine_magnitude_uses_count_rate_not_raw_counts(self):
        self.assertAlmostEqual(_machine_magnitude_from_rate(1200., 120.), -2.5)
        self.assertTrue(np.isnan(_machine_magnitude_from_rate(1200., None)))

    def test_extinction_line_recovers_known_slope_with_outlier(self):
        x = np.linspace(1., 3., 80)
        y = -9.2 + .24*x + .01*np.sin(np.arange(len(x)))
        y[7] += 4.
        result, keep = _robust_line(x, y)
        self.assertAlmostEqual(result['coefficient_mag_per_airmass'], .24, delta=.005)
        self.assertFalse(keep[7])
        self.assertGreater(result['fitted_count'], 70)


    def test_distinguishes_rgb_from_effectively_monochrome(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grey = np.arange(100, dtype=np.uint8).reshape(10, 10)
            Image.fromarray(np.dstack([grey, grey, grey]), 'RGB').save(root/'grey.png')
            colour = np.dstack([grey, np.roll(grey, 1, axis=0), np.roll(grey, 1, axis=1)])
            Image.fromarray(colour, 'RGB').save(root/'colour.png')
            self.assertEqual(classify_image_colour(root/'grey.png')['classification'],
                             'effectively_monochrome')
            self.assertEqual(classify_image_colour(root/'colour.png')['classification'], 'rgb')

    def test_one_bright_planet_is_a_candidate(self):
        self.assertEqual(planet_confidence(1, .03, True), 'single_planet_candidate')
        self.assertEqual(planet_confidence(1, .03, False), 'weak_single_planet_candidate')
        self.assertEqual(planet_confidence(2, .03), 'supported')
        self.assertEqual(planet_confidence(3, .03), 'strong')

    def test_planet_report_requires_measured_match(self):
        result = {
            'fit': {'count': 50, 'rms_px': .4, 'median_px': .3, 'p90_px': .7},
            'detection_count': 55,
            'camera': {'parameters': {'x_o': 10, 'y_o': 11, 'x_z': 12, 'y_z': 13,
                                      'v': .001, 's': .02, 'd': .003}}
        }
        no_match = {'planets': {'status': 'no_planet_match', 'matches': []}}
        self.assertNotIn('epoch is', report_sections(result, no_match)['planets'])
        one_match = {'planets': {
            'status': 'planet_epoch_fitted', 'confidence': 'single_planet_candidate',
            'derived_epoch_utc': '1950-01-01T00:00:00 UTC',
            'conditional_time_sigma_minutes': 80., 'competing_daily_minima': 4,
            'matches': [{'planet': 'Mars', 'detection_id': 8, 'separation_px': .5,
                         'unused_brightness_rank': 1}]}}
        text = report_sections(result, one_match)['planets']
        self.assertIn('Mars', text)
        self.assertIn('single_planet_candidate', text)
        self.assertIn('1950-01-01', text)

    def test_table_lists_each_rgb_extinction_slope(self):
        result = {
            'fit': {'count': 50, 'rms_px': .4, 'median_px': .3, 'p90_px': .7},
            'detection_count': 55,
            'camera': {'parameters': {'x_o': 10, 'y_o': 11, 'x_z': 12, 'y_z': 13,
                                      'v': .001, 's': .02, 'd': .003}}
        }
        fit = {'coefficient_mag_per_airmass': .2,
               'coefficient_sigma_mag_per_airmass': .01}
        science = {'stellar_epoch': {}, 'refraction': {},
                   'photometry': {'image_colour': {'classification': 'rgb'},
                                  'extinction_by_channel': {c: fit for c in 'RGB'}},
                   'planets': {}}
        rows = dict(table_rows(result, science))
        self.assertIn('kR=', rows['Extinction'])
        self.assertIn('kG=', rows['Extinction'])
        self.assertIn('kB=', rows['Extinction'])

    def test_table_lists_both_refraction_coefficients(self):
        result = {
            'fit': {'count': 50, 'rms_px': .4, 'median_px': .3, 'p90_px': .7},
            'detection_count': 55,
            'camera': {'parameters': {'x_o': 10, 'y_o': 11, 'x_z': 12, 'y_z': 13,
                                      'v': .001, 's': .02, 'd': .003}}
        }
        science = {'stellar_epoch': {},
                   'refraction': {'status': 'fitted',
                                  'refraction_a_arcsec': 7.51,
                                  'refraction_b_arcsec': -.005,
                                  'delta_bic': 4.2},
                   'photometry': {}, 'planets': {}}
        value = dict(table_rows(result, science))['Refraction']
        self.assertIn('A=7.51 arcsec', value)
        self.assertIn('B=-0.005 arcsec', value)

    def test_table_marks_single_planet_epoch(self):
        result = {
            'fit': {'count': 50, 'rms_px': .4, 'median_px': .3, 'p90_px': .7},
            'detection_count': 55,
            'camera': {'parameters': {'x_o': 10, 'y_o': 11, 'x_z': 12, 'y_z': 13,
                                      'v': .001, 's': .02, 'd': .003}}
        }
        science = {'stellar_epoch': {}, 'refraction': {}, 'photometry': {},
                   'planets': {'derived_epoch_utc': '2001 UTC', 'match_count': 1,
                               'confidence': 'single_planet_candidate',
                               'matches': [{'planet': 'Mars'}]}}
        rows = dict(table_rows(result, science))
        self.assertIn('1 planet(s)', rows['Planet epoch'])


if __name__ == '__main__':
    unittest.main()
