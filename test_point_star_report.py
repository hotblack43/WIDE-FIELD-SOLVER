"""Checks for the automatic one-page scientific report."""
import json
import re
import tempfile
from pathlib import Path
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from point_star_report import formula_page, observation_metadata, report_sections, write_report


class ReportTests(unittest.TestCase):
    def sample_result(self):
        return {
            'source': '/data/example.jpeg',
            'model': 'Barghini_2019_O_Z_FET',
            'fit': {'count': 3653, 'rms_px': .398, 'median_px': .249,
                    'p90_px': .606},
            'detection_count': 3688,
            'unmatched_dots': 35,
            'camera': {
                'model': 'Barghini_2019_equations_5_6_11',
                'parameters': {'a0': .0043, 'x_o': 776.8, 'y_o': 712.5,
                               'x_z': 785.0, 'y_z': 721.3,
                               'v': .00181, 's': .0903, 'd': .00167},
                'monotonic_on_detector': True,
            },
        }

    def test_report_catalogue_label_uses_saved_checksum(self):
        import hashlib
        from point_star_report import table_rows
        cases = [('stars_gaia_dr3_g75.csv', 'Gaia DR3 + bright Tycho-2/Hipparcos supplement'),
                 ('stars_tycho2_mag75.csv', 'Tycho-2 + bright Hipparcos supplement')]
        for filename, expected in cases:
            with self.subTest(catalogue=filename):
                result = self.sample_result()
                result['catalogue_sha256'] = hashlib.sha256(
                    (Path(__file__).parent/'data'/filename).read_bytes()).hexdigest()
                rows = dict(table_rows(result, {}))
                self.assertIn('Catalogue', rows)
                self.assertEqual(rows['Catalogue'], expected)
        result = self.sample_result()
        result.update(source='/data/gaia_image.jpg', catalogue_sha256='unknown')
        rows = dict(table_rows(result, {}))
        self.assertIn('Catalogue', rows)
        self.assertIn('unrecognized', rows['Catalogue'].lower())

    def test_epoch_is_only_reported_when_planets_are_measured(self):
        no_planets = report_sections(
            self.sample_result(),
            {'planets': {'status': 'no_planet_match', 'matches': []}})
        self.assertNotIn('epoch is', no_planets['planets'])

        science = {'planets': {
            'status': 'planet_epoch_fitted',
            'derived_epoch_utc': '2026-09-13T22:00:00 UTC',
            'confidence': 'single_planet_candidate',
            'conditional_time_sigma_minutes': 30.,
            'competing_daily_minima': 2,
            'matches': [{'planet': 'Jupiter', 'detection_id': 7,
                         'separation_px': .4, 'unused_brightness_rank': 1}]}}
        with_planet = report_sections(self.sample_result(), science)
        self.assertIn('2026-09-13T22:00:00 UTC', with_planet['planets'])
        self.assertIn('Jupiter', with_planet['planets'])
        self.assertIn('single_planet_candidate', with_planet['planets'])

    def test_collector_manifest_supplies_epoch_and_orm_site(self):
        with tempfile.TemporaryDirectory() as directory:
            feed = Path(directory)/'liverpool'
            feed.mkdir()
            image = feed/'liverpool_20260914T052808Z_abc123.jpg'
            image.touch()
            record = {'captured_at': '2026-09-14T05:28:08Z', 'feed': 'liverpool',
                      'filename': image.name,
                      'last_modified': 'Mon, 14 Sep 2026 05:28:08 GMT'}
            (feed/'manifest.jsonl').write_text(json.dumps(record)+'\n')

            metadata = observation_metadata({'source': str(image)})

            self.assertEqual(metadata['observation_time'], '2026-09-14T05:28:08Z')
            self.assertEqual(metadata['epoch_source'], 'camera-server Last-Modified via OMRcam manifest')
            self.assertAlmostEqual(metadata['latitude'], 28.7606)
            self.assertAlmostEqual(metadata['longitude'], -17.8850)

    def test_formula_page_contains_lens_refraction_and_no_result_values(self):
        figure = formula_page()
        text = ' '.join(item.get_text() for axis in figure.axes for item in axis.texts)
        plt.close(figure)
        self.assertIn('Barghini O/Z fish-eye mapping', text)
        self.assertIn('$O=(x_O,y_O)$', text)
        self.assertIn('R(z)=', text)
        self.assertIn('Parameter roles', text)
        self.assertNotIn('0.225', text)
        self.assertNotIn('2026-09-14', text)

    def test_pdf_preserves_embedded_png_resolution(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('astrometry_overlay.png', 'astrometry_residuals.png'):
                Image.new('RGB', (1280, 900), 'navy').save(root/name)
            report = write_report(root, self.sample_result())
            dimensions = {tuple(map(int, pair)) for pair in re.findall(
                rb'/Width\s+(\d+)\s+/Height\s+(\d+)', report.read_bytes())}
            for name in ('report_sky_overlay.png', 'astrometry_residuals.png'):
                with Image.open(root/name) as source:
                    self.assertIn(source.size, dimensions,
                                  f'{name} was downsampled when embedded in the PDF')

    def test_write_report_creates_two_page_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('astrometry_overlay.png', 'astrometry_residuals.png'):
                fig, ax = plt.subplots(figsize=(3, 2))
                ax.plot([0, 1], [0, 1])
                fig.savefig(root/name)
                plt.close(fig)

            result = self.sample_result()
            result['source'] = '/data/warwick_20260914T052808Z_abcd.jpg'
            report = write_report(root, result)

            self.assertEqual(report.name, 'report_warwick_20260914T052808Z.pdf')
            payload = report.read_bytes()
            self.assertTrue(payload.startswith(b'%PDF'))
            self.assertEqual(len(re.findall(rb'/Type\s*/Page\b', payload)), 2)
            media = re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)', payload)
            self.assertIsNotNone(media)
            self.assertLess(float(media.group(1)), float(media.group(2)))


if __name__ == '__main__':
    unittest.main()
