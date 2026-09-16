"""Checks for the automatic one-page scientific report."""
import json
import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

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

    def test_zenith_overlay_projects_saved_candidate_and_labels_provisional(self):
        from PIL import Image
        from point_star_barghini import BarghiniCamera
        from point_star_report import write_report_sky_overlay
        camera = BarghiniCamera.initial((100, 120), 60., np.eye(3))
        expected = np.array([[47., 39.]])
        vector = camera.to_sky(expected)[0].tolist()
        for status in ('conditional_zenith', 'not_identifiable'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                Image.new('RGB', (120, 100)).save(root/'source.png')
                result = {'source': str(root/'source.png'), 'camera': camera.serialise()}
                science = {'photometry': {'photometric_zenith': {
                    'status': status, 'zenith_unit_vector': vector}}}
                with patch('point_star_report.save_png') as save:
                    write_report_sky_overlay(root, result, science)
                axis = save.call_args.args[0].axes[0]
                markers = [line for line in axis.lines if line.get_marker() == 'x']
                self.assertEqual(len(markers), 1)
                np.testing.assert_allclose(markers[0].get_xydata(), expected, atol=1e-7)
                self.assertEqual(markers[0].get_color(), 'red')
                labels = ' '.join(item.get_text() for item in axis.get_legend().get_texts())
                self.assertIn('Extinction zenith', labels)
                self.assertEqual('provisional' in labels, status == 'not_identifiable')

    def test_absent_zenith_is_explicit_and_does_not_draw_a_position(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (120, 100)).save(root/'source.png')
            science = {'photometry': {'photometric_zenith': {
                'status': 'not_identifiable', 'zenith_unit_vector': None}}}
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(root, {'source': str(root/'source.png')}, science)
            axis = save.call_args.args[0].axes[0]
            self.assertFalse(any(line.get_marker() == 'x' for line in axis.lines))
            self.assertIn('Extinction zenith: no candidate',
                          ' '.join(item.get_text() for item in axis.texts))

    def test_geometric_fallback_is_not_labelled_as_extinction_zenith(self):
        from PIL import Image
        from point_star_barghini import BarghiniCamera
        from point_star_report import write_report_sky_overlay
        camera = BarghiniCamera.initial((100, 120), 60., np.eye(3))
        centre = np.array([[59.5, 49.5]])
        vector = camera.to_sky(centre)[0].tolist()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (120, 100)).save(root/'source.png')
            science = {'photometry': {'photometric_zenith': {
                'status': 'not_identifiable', 'provisional': True,
                'zenith_source': 'centred_full_horizon_geometry',
                'zenith_unit_vector': vector}}}
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(
                    root, {'source': str(root/'source.png'), 'camera': camera.serialise()}, science)
            axis = save.call_args.args[0].axes[0]
            labels = ' '.join(item.get_text() for item in axis.get_legend().get_texts())
            self.assertIn('Geometric zenith', labels)
            self.assertNotIn('Extinction zenith', labels)
            np.testing.assert_allclose(
                [line for line in axis.lines if line.get_marker() == 'x'][0].get_xydata(),
                centre, atol=1e-7)

    def test_results_text_distinguishes_geometric_fallback_from_extinction_trial(self):
        science = {'stellar_epoch': {}, 'refraction': {}, 'planets': {},
                   'photometry': {'photometric_zenith': {
                       'status': 'not_identifiable', 'provisional': True,
                       'zenith_source': 'centred_full_horizon_geometry'}}}
        text = report_sections(self.sample_result(), science)['atmosphere']
        self.assertIn('image-centre geometric zenith', text)
        self.assertIn('extinction trial remains not identifiable', text)

    def test_predicted_planets_are_distinct_and_keep_saved_positions(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        from point_star_planets import _plot_candidates
        answer = {'status': 'planet_epoch_ambiguous',
                  'matches': [{'planet': 'Mars', 'measured_x_px': 30., 'measured_y_px': 40.}],
                  'predicted_planets': [{'planet': 'Jupiter', 'predicted_x_px': 85., 'predicted_y_px': 60.}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (120, 100)).save(root/'source.png')
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(root, {'source': str(root/'source.png')}, {'planets': answer})
            report_axis = save.call_args.args[0].axes[0]
            with patch('point_star_plotting.save_png') as save:
                _plot_candidates(root/'source.png', root, answer)
            for axis in (report_axis, save.call_args.args[0].axes[0]):
                markers = [line for line in axis.lines if line.get_marker() == '*']
                self.assertEqual(len(markers), 2)
                np.testing.assert_allclose(markers[0].get_xydata(), [[30., 40.]])
                np.testing.assert_allclose(markers[1].get_xydata(), [[85., 60.]])
                self.assertTrue(all(m.get_markerfacecolor() == 'none' for m in markers))
                self.assertLess(markers[1].get_markeredgewidth(), markers[0].get_markeredgewidth())
                self.assertIn('Jupiter (predicted)', [t.get_text() for t in axis.texts])

    def test_missing_original_preserves_rendered_fallback_without_detector_labels(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (240, 180), color='gray').save(root/'astrometry_overlay.png')
            science = {'planets': {'matches': [{'planet': 'Mars', 'measured_x_px': 30., 'measured_y_px': 40.}],
                       'predicted_planets': [{'planet': 'Jupiter', 'predicted_x_px': 80., 'predicted_y_px': 60.}]}}
            target = write_report_sky_overlay(root, {'source': str(root/'missing.png')}, science)
            self.assertEqual(target.read_bytes(), (root/'astrometry_overlay.png').read_bytes())

    def test_planet_table_distinguishes_not_run_from_no_match(self):
        from point_star_report import table_rows
        for status, expected in [('not_run', 'Not run'),
                                 ('no_planet_match', 'No matched planet')]:
            rows = dict(table_rows(self.sample_result(), {'planets': {
                'status': status, 'matches': []}}))
            self.assertIn(expected, rows['Planet epoch'])

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

    def test_single_planet_aliases_are_reported_as_not_identifiable(self):
        from point_star_report import table_rows
        science = {'planets': {'status': 'planet_epoch_not_identifiable', 'matches': [],
            'match_count': 0, 'candidate_count': 12, 'single_planet_candidate_count': 12,
            'derived_epoch_utc': None, 'best_candidate_epoch_tdb': None,
            'reason': 'Only single-planet aliases remain; no planetary epoch is identifiable.'}}
        text = report_sections(self.sample_result(), science)['planets']
        self.assertIn('not identifiable', text.lower())
        self.assertIn('12', text)
        self.assertNotIn('None', text)
        row = dict(table_rows(self.sample_result(), science))['Planet epoch']
        self.assertIn('Not identifiable', row)
        self.assertIn('12', row)
        self.assertNotIn('None', row)

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

    def test_rgb_photometry_uses_gaia_rp_g_bp_and_keeps_finite_unsaturated_rows(self):
        from point_star_report import photometry_comparisons
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'stellar_photometry.csv').write_text(
                'detection_id,star_id,saturated,R_mag,G_mag,B_mag\n'
                '1,Gaia DR3 101,False,-5.0,-5.1,-5.2\n'
                '2,Gaia DR3 102,True,-6.0,-6.1,-6.2\n'
                '3,HIP 000001,False,-7.0,-7.1,-7.2\n'
                '4,Gaia DR3 103,False,-8.0,nan,-8.2\n')
            catalogue = root/'gaia-source.csv'
            catalogue.write_text(
                'source_id,phot_g_mean_mag,phot_bp_mean_mag,phot_rp_mean_mag\n'
                '101,6.0,6.5,5.5\n'
                '102,7.0,7.5,6.5\n'
                '103,8.0,8.5,7.5\n')

            comparisons = photometry_comparisons(root, catalogue_path=catalogue)

            np.testing.assert_allclose(comparisons['R']['catalogue_mag'], [5.5, 7.5])
            np.testing.assert_allclose(comparisons['R']['machine_mag'], [-5.0, -8.0])
            np.testing.assert_allclose(comparisons['G']['catalogue_mag'], [6.0])
            np.testing.assert_allclose(comparisons['G']['machine_mag'], [-5.1])
            np.testing.assert_allclose(comparisons['B']['catalogue_mag'], [6.5, 8.5])
            np.testing.assert_allclose(comparisons['B']['machine_mag'], [-5.2, -8.2])
            self.assertEqual(comparisons['R']['catalogue_band'], 'Gaia RP')
            self.assertEqual(comparisons['G']['catalogue_band'], 'Gaia G')
            self.assertEqual(comparisons['B']['catalogue_band'], 'Gaia BP')

    def test_rgb_photometry_plots_put_brighter_magnitudes_upper_right_without_unit_line(self):
        from point_star_report import photometry_page
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'stellar_photometry.csv').write_text(
                'detection_id,star_id,saturated,R_mag,G_mag,B_mag\n'
                '1,Gaia DR3 132667245587072,False,-5.0,-5.1,-5.2\n'
                '2,Gaia DR3 219563023736832,False,-6.0,-6.1,-6.2\n')

            figure = photometry_page(root)

            positions = [axis.get_position() for axis in figure.axes]
            self.assertEqual(len(positions), 3)
            self.assertLess(max(box.y0 for box in positions)-min(box.y0 for box in positions), .01)
            self.assertLess(positions[0].x0, positions[1].x0)
            self.assertLess(positions[1].x0, positions[2].x0)
            self.assertGreater(figure.get_figwidth(), figure.get_figheight())
            for axis in figure.axes:
                self.assertTrue(axis.yaxis_inverted())
                self.assertTrue(axis.xaxis_inverted())
                self.assertIn('brighter →', axis.get_xlabel().lower())
                self.assertIn('brighter', axis.get_ylabel().lower())
                self.assertEqual([line.get_label() for line in axis.lines],
                                 ['ordinary least-squares line'])
            plt.close(figure)

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

    def test_report_title_does_not_spend_a_line_on_hidden_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('astrometry_overlay.png', 'astrometry_residuals.png'):
                fig, ax = plt.subplots(figsize=(3, 2))
                ax.plot([0, 1], [0, 1])
                fig.savefig(root/name)
                plt.close(fig)
            with patch('point_star_report.PdfPages') as pages:
                write_report(root, self.sample_result())
            saved = pages.return_value.__enter__.return_value.savefig.call_args_list
            self.assertEqual(saved[0].args[0]._suptitle.get_text(),
                             'Wide-field image solution: example.jpeg')

    def test_write_report_has_results_formulae_and_rgb_photometry_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('astrometry_overlay.png', 'astrometry_residuals.png',
                         'planet_epoch_candidates.png'):
                fig, ax = plt.subplots(figsize=(3, 2))
                ax.plot([0, 1], [0, 1])
                fig.savefig(root/name)
                plt.close(fig)

            result = self.sample_result()
            result['source'] = '/data/warwick_20260914T052808Z_abcd.jpg'
            report = write_report(root, result)

            self.assertEqual(report.name, 'report.pdf')
            payload = report.read_bytes()
            self.assertTrue(payload.startswith(b'%PDF'))
            self.assertEqual(len(re.findall(rb'/Type\s*/Page\b', payload)), 3)
            media = re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)', payload)
            self.assertIsNotNone(media)
            self.assertLess(float(media.group(1)), float(media.group(2)))


if __name__ == '__main__':
    unittest.main()
