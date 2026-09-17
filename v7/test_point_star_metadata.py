"""Observation-time metadata used only by the v7 planetary control path."""
import tempfile
from pathlib import Path
import unittest

import numpy as np
from astropy.io import fits
from PIL import Image


class ObservationTimeMetadataTests(unittest.TestCase):
    def test_fits_date_obs_is_selected_and_numeric_dates_are_audited(self):
        from point_star_metadata import resolve_observation_time
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'image.fits'
            header = fits.Header()
            header['DATE-OBS'] = '2018-09-16T00:13:55.000'
            header['MJD-OBS'] = 58377.00966435186
            header['JD'] = 2458377.509664352
            fits.PrimaryHDU(np.zeros((4, 4)), header).writeto(source)

            result = resolve_observation_time(source)

        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['source'], 'fits:PRIMARY:DATE-OBS')
        self.assertEqual(result['time_utc'], '2018-09-16T00:13:55.000 UTC')
        self.assertTrue(result['assumed_utc'])
        self.assertEqual([row['field'] for row in result['candidates']],
                         ['DATE-OBS', 'MJD-OBS', 'JD'])
        self.assertLess(result['maximum_disagreement_seconds'], .001)

    def test_malformed_fits_date_does_not_hide_valid_numeric_time(self):
        from point_star_metadata import resolve_observation_time
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'image.fits'
            header = fits.Header()
            header['DATE-OBS'] = 'not-a-date'
            header['MJD-OBS'] = 58377.00966435186
            fits.PrimaryHDU(np.zeros((4, 4)), header).writeto(source)

            result = resolve_observation_time(source)

        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['source'], 'fits:PRIMARY:MJD-OBS')
        self.assertEqual(result['time_utc'], '2018-09-16T00:13:55.000 UTC')

    def test_fits_date_obs_honours_declared_time_scale(self):
        from point_star_metadata import resolve_observation_time
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'image.fits'
            header = fits.Header()
            header['TIMESYS'] = 'TAI'
            header['DATE-OBS'] = '2018-09-16T00:14:32.000'
            fits.PrimaryHDU(np.zeros((4, 4)), header).writeto(source)

            result = resolve_observation_time(source)

        self.assertEqual(result['time_utc'], '2018-09-16T00:13:55.000 UTC')
        self.assertFalse(result['assumed_utc'])

    def test_exif_original_time_and_offset_are_converted_to_utc(self):
        from point_star_metadata import resolve_observation_time
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'image.jpg'
            exif = Image.Exif()
            exif[36867] = '2018:09:16 00:13:55'
            exif[36881] = '+02:00'
            Image.new('RGB', (4, 4)).save(source, exif=exif)

            result = resolve_observation_time(source)

        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['source'], 'exif:DateTimeOriginal')
        self.assertEqual(result['time_utc'], '2018-09-15T22:13:55.000 UTC')
        self.assertFalse(result['assumed_utc'])

    def test_filename_iso_and_compact_times_are_supported(self):
        from point_star_metadata import resolve_observation_time
        cases = {
            'APICAM.2018-09-16T00:13:55.000.fits':
                '2018-09-16T00:13:55.000 UTC',
            'warwick_20260915T031637Z_camera.jpg':
                '2026-09-15T03:16:37.000 UTC',
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, expected in cases.items():
                with self.subTest(name=name):
                    source = root/name
                    source.write_bytes(b'not decoded because filename is sufficient')
                    result = resolve_observation_time(source)
                    self.assertEqual(result['status'], 'selected')
                    self.assertEqual(result['source'], 'filename')
                    self.assertEqual(result['time_utc'], expected)

    def test_header_wins_over_disagreeing_filename_and_conflict_is_recorded(self):
        from point_star_metadata import resolve_observation_time
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'APICAM.2019-01-01T00:00:00.000.fits'
            header = fits.Header()
            header['DATE-OBS'] = '2018-09-16T00:13:55.000'
            fits.PrimaryHDU(np.zeros((4, 4)), header).writeto(source)

            result = resolve_observation_time(source)

        self.assertEqual(result['source'], 'fits:PRIMARY:DATE-OBS')
        self.assertTrue(result['disagreement'])
        self.assertGreater(result['maximum_disagreement_seconds'], 86400.)
        self.assertEqual({row['source'] for row in result['candidates']},
                         {'fits:PRIMARY:DATE-OBS', 'filename'})

    def test_no_parseable_time_is_explicit(self):
        from point_star_metadata import resolve_observation_time
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'undated.png'
            Image.new('L', (4, 4)).save(source)
            result = resolve_observation_time(source)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['time_utc'])
        self.assertEqual(result['candidates'], [])

    def test_metadata_search_window_is_two_days_and_labelled_nonblind(self):
        from astropy.time import Time
        from point_star_metadata import planet_search_context
        context = planet_search_context(
            'APICAM.2018-09-16T00:13:55.000.fits',
            latest_jd_tdb=Time('2026-01-01', scale='utc').tdb.jd)
        limits = Time(context['epoch_limits'], format='jyear', scale='tdb').jd
        self.assertEqual(context['planet_search_mode'], 'metadata_conditioned')
        self.assertTrue(context['metadata_used'])
        self.assertAlmostEqual(limits[1]-limits[0], 2., places=8)
        self.assertAlmostEqual(np.mean(limits),
                               Time('2018-09-16T00:13:55', scale='utc').tdb.jd,
                               places=8)

    def test_forced_blind_and_missing_metadata_choose_full_search(self):
        from astropy.time import Time
        from point_star_metadata import planet_search_context
        ceiling = Time('2026-01-01', scale='utc').tdb.jd
        forced = planet_search_context(
            'APICAM.2018-09-16T00:13:55.000.fits', force_blind=True,
            latest_jd_tdb=ceiling)
        fallback = planet_search_context('undated.png', latest_jd_tdb=ceiling)
        self.assertEqual(forced['planet_search_mode'], 'blind_forced')
        self.assertEqual(fallback['planet_search_mode'], 'blind_fallback')
        self.assertEqual(forced['epoch_limits'], (1850., 2036.))
        self.assertEqual(fallback['epoch_limits'], (1850., 2036.))
        self.assertFalse(forced['metadata_used'])
        self.assertFalse(fallback['metadata_used'])


if __name__ == '__main__':
    unittest.main()
