"""Causal time bounds are independent of image observation metadata."""
import unittest
from unittest.mock import patch

from astropy.time import Time


class TimeBoundsTests(unittest.TestCase):
    def test_clock_is_captured_once_with_consistent_time_scales(self):
        from point_star_time_bounds import capture_time_ceiling
        instant = Time('2025-03-04T12:34:56.123456', scale='utc', precision=6)
        with patch('point_star_time_bounds.Time.now', return_value=instant) as clock:
            ceiling = capture_time_ceiling()
        clock.assert_called_once_with()
        self.assertEqual(ceiling['source'], 'current_system_time_at_run_start')
        self.assertLess(abs((Time(ceiling['utc'], scale='utc')-instant).sec), 1e-6)
        self.assertEqual(ceiling['jd_tdb'], float(instant.tdb.jd))
        self.assertEqual(ceiling['jyear'], float(instant.tdb.jyear))

    def test_cap_preserves_past_ranges_and_clips_future_upper_limit(self):
        from point_star_time_bounds import limit_epoch_range
        ceiling = {'jyear': 2025.25}
        self.assertEqual(limit_epoch_range((1850., 2150.), ceiling), (1850., 2025.25))
        self.assertEqual(limit_epoch_range((1900., 1950.), ceiling), (1900., 1950.))
        self.assertEqual(limit_epoch_range((1900., 2025.25), ceiling), (1900., 2025.25))

    def test_future_only_and_zero_width_ranges_are_rejected(self):
        from point_star_time_bounds import limit_epoch_range
        for limits in ((2030., 2150.), (2025.25, 2150.), (1900., 1900.), (2000., 1900.)):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                limit_epoch_range(limits, {'jyear': 2025.25})

    def test_invalid_range_or_ceiling_is_rejected(self):
        from point_star_time_bounds import limit_epoch_range
        for limits in ((), (1900.,), (1900., 2000., 2100.), (float('nan'), 2100.),
                       (1900., float('inf')), (None, 2000.)):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                limit_epoch_range(limits, {'jyear': 2025.25})
        for value in (float('nan'), float('inf'), -float('inf'), None):
            with self.subTest(ceiling=value), self.assertRaises(ValueError):
                limit_epoch_range((1850., 2150.), {'jyear': value})


class SolverTimeBoundsTests(unittest.TestCase):
    def test_fitted_epoch_uses_and_saves_one_ceiling_without_observation_metadata(self):
        import contextlib
        import csv
        import io
        import json
        from pathlib import Path
        import tempfile

        from PIL import Image

        from point_star_barghini import run
        from point_star_epoch import fit_epoch
        from test_point_star_epoch import moving_field

        instant = Time('2025-03-04T12:34:56.123456', scale='utc')
        initial, xy, rows, _ = moving_field(motion_scale=700., year=2020.)
        bounds_used = []

        def bounded_fit(camera, measured, catalogue, limits, **kwargs):
            bounds_used.append(limits)
            self.assertEqual(limits, (1850., float(instant.tdb.jyear)))
            return fit_epoch(camera, measured, catalogue, limits, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'image.png'
            Image.new('RGB', (1000, 800)).save(source)
            catalog = root/'stars.csv'
            with catalog.open('w') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            def detected(image, output):
                output.mkdir(parents=True)
                with (output/'star_candidates.csv').open('w') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(['detection_id', 'x_px', 'y_px', 'source_class', 'saturated'])
                    writer.writerows((i, x, y, 'compact', False) for i, (x, y) in enumerate(xy))
                return dict(height_px=800, width_px=1000, source_sha256='synthetic')

            output = root/'fit'
            with patch('point_star_time_bounds.Time.now', return_value=instant) as clock, \
                 patch('point_star_barghini.write_products', side_effect=detected), \
                 patch('point_star_barghini.bootstrap', return_value=(initial, {})), \
                 patch('point_star_epoch.fit_epoch', side_effect=bounded_fit), \
                 patch('point_star_barghini.annotate_stars'), \
                 patch('point_star_diagnostics.write_diagnostics'), \
                 patch('point_star_report.write_report', return_value=output/'report.pdf'), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = run(source, output, catalog, offline=True,
                             observation_time='not a timestamp', latitude='not a latitude',
                             longitude='not a longitude')
            clock.assert_called_once_with()
            self.assertTrue(bounds_used)
            self.assertAlmostEqual(result['stellar_epoch']['epoch_jyear'], 2020., delta=.5)
            self.assertFalse(result['metadata_used'])
            ceiling = result['causal_epoch_ceiling']
            self.assertEqual(ceiling['jd_tdb'], float(instant.tdb.jd))
            self.assertEqual(result['stellar_epoch']['causal_epoch_ceiling'], ceiling)
            saved = json.loads((output/'result.json').read_text())
            epoch = json.loads((output/'stellar_epoch.json').read_text())
            self.assertEqual(saved['causal_epoch_ceiling'], ceiling)
            self.assertEqual(epoch['causal_epoch_ceiling'], ceiling)

    def test_fixed_and_catalog_modes_do_not_capture_or_cap_the_clock(self):
        from point_star_barghini import run

        class ReachedOutput(Exception):
            pass

        for arguments in ({'epoch_mode': 'fixed', 'epoch_year': 2060.}, {'epoch_mode': 'catalog'}):
            with self.subTest(arguments=arguments), \
                 patch('point_star_time_bounds.Time.now', side_effect=AssertionError('Clock read')), \
                 patch('point_star_barghini.prepare_output', side_effect=ReachedOutput), \
                 self.assertRaises(ReachedOutput):
                run('/tmp/image.png', '/tmp/future-control', '/tmp/catalog.csv',
                    epoch_limits=(2050., 2150.), **arguments)
