"""Checks for the automatic one-page scientific report."""
import json
import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg

from point_star_report import (formula_page, observation_metadata, report_sections,
                               table_rows, write_report)


class ReportTests(unittest.TestCase):
    def test_planet_label_between_nearby_sources_keeps_markers_clear(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        stars = [dict(display_name='ο Leo', x_px=121.4018, y_px=718.8467),
                 dict(display_name='ε Gem', x_px=449.1134, y_px=689.9899)]
        matches = [dict(planet='Mars', measured_x_px=334.7097, measured_y_px=704.4659,
                        predicted_x_px=334.8, predicted_y_px=704.6),
                   dict(planet='Jupiter', measured_x_px=173.8223, measured_y_px=747.2459,
                        predicted_x_px=174., predicted_y_px=747.4)]
        joint = dict(status='joint_epoch_ambiguous', adopted=False, best_index=0,
                     candidates=[dict(matches=matches, epoch_tdb='2026', jd_tdb=2461303.)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (1408, 1408)).save(root/'source.png')
            (root/'labelled_stars.json').write_text(json.dumps(dict(stars=stars)))
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(root, dict(source=str(root/'source.png'), joint_epoch=joint), {})
            ax = save.call_args.args[0].axes[0]
            canvas = FigureCanvasAgg(ax.figure)
            canvas.draw()
            renderer = canvas.get_renderer()
            labels = [t for t in ax.texts if t.get_text() and t.get_text() != 'Extinction zenith: no candidate']
            for text in labels:
                box = text.get_bbox_patch().get_window_extent(renderer)
                for marker in ax.lines:
                    self.assertFalse(box.overlaps(marker.get_window_extent(renderer)), text.get_text())
            audit = json.loads((root/'report_label_layout.json').read_text())
            self.assertEqual(audit['remaining_conflicts'], [])

    def test_sky_labels_avoid_each_other_markers_legend_and_image_edges(self):
        from copy import deepcopy
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        stars = [dict(display_name=name, x_px=x, y_px=y) for name, x, y in (
            ('Nearby star A', 180., 180.), ('Nearby star B', 183., 182.),
            ('Nearby star C', 177., 183.), ('Edge star', 396., 20.),
            ('Near legend', 35., 375.))]
        planets = dict(status='conditional_planet_epoch', matches=[
            dict(planet='Mars', measured_x_px=180., measured_y_px=177.),
            dict(planet='Jupiter', measured_x_px=185., measured_y_px=180.)],
            predicted_planets=[dict(planet='Saturn', predicted_x_px=182., predicted_y_px=185.)])
        original = deepcopy(planets)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (400, 400)).save(root/'source.png')
            (root/'labelled_stars.json').write_text(json.dumps(dict(stars=stars)))
            positions = []
            for repeat in range(2):
                with patch('point_star_report.save_png') as save:
                    write_report_sky_overlay(root, dict(source=str(root/'source.png')),
                                             dict(planets=planets, photometry={}))
                fig = save.call_args.args[0]
                canvas = FigureCanvasAgg(fig)
                canvas.draw()
                ax = fig.axes[0]
                renderer = canvas.get_renderer()
                labels = [t for t in ax.texts if t.get_text() and not t.get_text().startswith('Extinction zenith:')]
                self.assertEqual(len(labels), 8, 'Do not solve crowding by dropping labels')
                boxes = [t.get_bbox_patch().get_window_extent(renderer) for t in labels]
                marker_boxes = [line.get_window_extent(renderer) for line in ax.lines]
                fixed = marker_boxes + [ax.get_legend().get_window_extent(renderer)]
                fixed += [t.get_bbox_patch().get_window_extent(renderer) for t in ax.texts
                          if t.get_text().startswith('Extinction zenith:')]
                for i, box in enumerate(boxes):
                    for other in boxes[i+1:]+fixed:
                        self.assertFalse(box.overlaps(other), labels[i].get_text())
                    self.assertTrue(ax.bbox.contains(box.x0, box.y0), labels[i].get_text())
                    self.assertTrue(ax.bbox.contains(box.x1, box.y1), labels[i].get_text())
                expected = [[r['x_px'], r['y_px']] for r in stars]+[[180.,177.], [185.,180.], [182.,185.]]
                np.testing.assert_allclose([line.get_xydata()[0] for line in ax.lines], expected)
                positions.append([t.get_position() for t in labels])
            np.testing.assert_allclose(positions[0], positions[1], atol=1e-10)
        self.assertEqual(planets, original)

    def test_joint_table_distinguishes_initial_epoch_from_saved_coordinate_epoch(self):
        result = self.sample_result()
        result.update(stellar_epoch=dict(status='not_identifiable', applied_epoch_jyear=2000.),
                      coordinate_epoch_jyear=2020.,
                      joint_epoch=dict(status='joint_epoch_fitted', adopted=True))
        table = dict(table_rows(result, {}))
        self.assertIn('2020', table['Coordinate epoch'])
        self.assertIn('Initial', table['Stellar epoch'])
        self.assertNotIn('adopted J2000', table['Stellar epoch'])
    def test_joint_report_does_not_replace_fitted_candidate_with_metadata_match(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        match = dict(planet='Mars', detection_id=1, measured_x_px=30., measured_y_px=40.,
                     predicted_x_px=31., predicted_y_px=41., separation_arcmin=2., separation_px=1.4)
        metadata = dict(match, planet='Jupiter', measured_x_px=80., measured_y_px=60.)
        joint = dict(status='joint_epoch_ambiguous', adopted=False, best_index=0,
                     reason='Unresolved zenith', candidates=[dict(matches=[match], epoch_tdb='2020', jd_tdb=2458849.)])
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)
            Image.new('RGB', (120, 100)).save(output/'source.png')
            result = dict(source=str(output/'source.png'), joint_epoch=joint)
            science = dict(planets=dict(metadata_matches=[metadata], matches=[match]), joint_epoch=joint)
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(output, result, science)
            ax = save.call_args.args[0].axes[0]
            measured = [line for line in ax.lines if line.get_label() == 'joint fit source']
            self.assertEqual(len(measured), 1)
            np.testing.assert_allclose(measured[0].get_xydata(), [[30., 40.]])
            self.assertEqual(measured[0].get_markerfacecolor(), 'none')
            predictions = [line for line in ax.lines if line.get_label() == 'joint fit prediction']
            np.testing.assert_allclose(predictions[0].get_xydata(), [[31., 41.]])
            self.assertEqual(predictions[0].get_markerfacecolor(), 'none')
            self.assertNotIn(predictions[0].get_marker(), ('+', 'x', '*'))
            self.assertNotIn('Jupiter', ' '.join(t.get_text() for t in ax.texts))
            self.assertIn('Mars — joint fit', ' '.join(t.get_text() for t in ax.texts))
            legend = ' '.join(t.get_text() for t in ax.get_legend().get_texts())
            self.assertIn('used in joint epoch fit', legend)
            self.assertIn('conditional', legend)

    def test_saved_mirrored_camera_reconstructs_the_same_projection(self):
        from point_star_barghini import BarghiniCamera
        from point_star_report import _camera_from_result
        camera = BarghiniCamera.initial(
            (100, 120), 60., np.eye(3), detector_parity=-1)
        measured = np.array([[31., 27.], [82., 64.]])
        sky = camera.to_sky(measured)

        restored = _camera_from_result({'camera': camera.serialise()})

        self.assertEqual(restored.detector_parity, -1)
        np.testing.assert_allclose(restored.project(sky), measured, atol=1e-7)

    def test_report_discloses_selected_mirrored_detector_parity(self):
        result = self.sample_result()
        result['camera']['detector_parity'] = 'mirrored'

        sections = report_sections(result, {})

        self.assertIn('mirrored detector parity', sections['lens'])

    def test_report_leads_with_angular_astrometry_and_retains_pixel_diagnostics(self):
        result = self.sample_result()
        result['fit'].update(rms_arcmin=4.2, median_arcmin=3.1, p90_arcmin=6.8)

        sections = report_sections(result, {})
        rows = dict(table_rows(result, {}))

        self.assertIn('RMS 4.200 arcmin', sections['astrometry'])
        self.assertIn('0.398 px', sections['astrometry'])
        self.assertIn('RMS 4.200 arcmin', rows['Astrometry'])

    def test_sky_overlay_accepts_four_plane_high_bit_fits(self):
        from point_star_report import write_report_sky_overlay
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            planes = np.stack([np.full((100, 120), value, dtype=np.uint16)
                               for value in (256, 4095, 16383, 32768)])
            source = root/'source.fits'
            fits.PrimaryHDU(planes).writeto(source)
            science = {'photometry': {'photometric_zenith': {
                'status': 'not_identifiable', 'zenith_unit_vector': None}}}
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(root, {'source': str(source)}, science)
            shown = np.asarray(save.call_args.args[0].axes[0].images[0].get_array())
        self.assertEqual(shown.shape, (100, 120, 3))
        self.assertEqual(shown.dtype, np.uint8)

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
                self.assertFalse(any(item.get_text().startswith('Zenith (')
                                     for item in axis.texts))

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

    def test_assumed_centre_zenith_is_labelled_as_assumption_at_saved_position(self):
        from point_star_barghini import BarghiniCamera
        from point_star_report import _draw_photometric_zenith
        camera = BarghiniCamera.initial((100, 120), 60., np.eye(3))
        science = {'photometry': {'photometric_zenith': {
            'status': 'assumed_zenith', 'zenith_source': 'image_centre_assumption',
            'zenith_unit_vector': camera.to_sky([[59.5, 49.5]])[0].tolist()}}}
        fig, ax = plt.subplots()
        try:
            marker = _draw_photometric_zenith(ax, {'camera': camera.serialise()}, science, native_image=True)
            self.assertIn('assumed', marker.get_label().lower())
            self.assertNotIn('extinction', marker.get_label().lower())
            np.testing.assert_allclose(marker.get_xydata(), [[59.5, 49.5]], atol=1e-7)
            text = report_sections(self.sample_result(), science)['atmosphere']
            self.assertIn('assumed at image centre', text)
            self.assertIn('not an extinction measurement', text)
        finally:
            plt.close(fig)

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

    def test_report_figure_caption_names_geometric_zenith(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('astrometry_overlay.png', 'astrometry_residuals.png'):
                plt.imsave(root/name, np.zeros((20, 20, 3)))
            science = {'photometry': {'photometric_zenith': {
                'status': 'not_identifiable', 'provisional': True,
                'zenith_source': 'centred_full_horizon_geometry',
                'zenith_unit_vector': [0., 0., 1.]}}}
            with patch('point_star_report._show_image') as show, \
                 patch('point_star_report.PdfPages'):
                write_report(root, self.sample_result(), science=science)
            self.assertIn('geometric zenith', show.call_args_list[0].args[2].lower())
            self.assertNotIn('extinction zenith', show.call_args_list[0].args[2].lower())

    def test_predicted_planets_are_distinct_and_keep_saved_positions(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        from point_star_planets import _plot_candidates
        answer = {'status': 'planet_epoch_ambiguous',
                  'metadata_used': True, 'planet_search_mode': 'metadata_conditioned',
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
            self.assertIn('Metadata-conditioned', save.call_args.args[0].axes[0].get_title())
            self.assertNotIn('Blind planet', save.call_args.args[0].axes[0].get_title())
            for axis in (report_axis, save.call_args.args[0].axes[0]):
                markers = [line for line in axis.lines if line.get_marker() == '*']
                self.assertEqual(len(markers), 2)
                np.testing.assert_allclose(markers[0].get_xydata(), [[30., 40.]])
                np.testing.assert_allclose(markers[1].get_xydata(), [[85., 60.]])
                self.assertTrue(all(m.get_markerfacecolor() == 'none' for m in markers))
                self.assertLess(markers[1].get_markeredgewidth(), markers[0].get_markeredgewidth())
                self.assertIn('Jupiter (predicted)', [t.get_text() for t in axis.texts])

    def test_metadata_conditioned_planet_result_is_disclosed_in_report(self):
        planets = {
            'status': 'planet_epoch_ambiguous', 'metadata_used': True,
            'planet_search_mode': 'metadata_conditioned', 'candidate_count': 2,
            'match_count': 1, 'best_candidate_epoch_tdb': '2018-09-16T00:13:55 TDB',
            'observation_time_metadata': {
                'time_utc': '2018-09-16T00:13:55.000 UTC',
                'source': 'fits:PRIMARY:DATE-OBS'},
            'metadata_accuracy': {
                'status': 'local_planet_epoch_compared',
                'planet_minus_metadata_seconds': -42.5,
                'absolute_timing_error_seconds': 42.5},
            'matches': [{'planet': 'Mars', 'detection_id': 7,
                         'separation_arcmin': 1.25, 'separation_px': .4,
                         'unused_brightness_rank': 1}],
        }
        science = {'planets': planets}
        text = report_sections(self.sample_result(), science)['planets']
        row = dict(table_rows(self.sample_result(), science))['Planet epoch']
        self.assertEqual(text, 'Mars: epoch-fit match, 1.25 arcmin. Epoch: unresolved.')
        self.assertIn('Metadata-conditioned', row)

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
        self.assertLessEqual(len(with_planet['planets'].split()), 16)

    def test_single_planet_aliases_are_reported_as_not_identifiable(self):
        from point_star_report import table_rows
        science = {'planets': {'status': 'planet_epoch_not_identifiable', 'matches': [],
            'candidate_matches': [{'planet': 'Jupiter', 'detection_id': 1,
                                   'separation_px': .096,
                                   'unused_brightness_rank': 1}],
            'match_count': 0, 'candidate_count': 12, 'single_planet_candidate_count': 12,
            'derived_epoch_utc': None, 'best_candidate_epoch_tdb': None,
            'reason': 'Only single-planet aliases remain; no planetary epoch is identifiable.'}}
        text = report_sections(self.sample_result(), science)['planets']
        self.assertIn('not identifiable', text.lower())
        self.assertEqual(text, 'Jupiter: positional candidate, 0.10 px. Epoch: not identifiable.')
        self.assertNotIn('None', text)
        row = dict(table_rows(self.sample_result(), science))['Planet epoch']
        self.assertIn('Not identifiable', row)
        self.assertIn('12', row)
        self.assertNotIn('None', row)

    def test_single_planet_candidate_is_drawn_without_claiming_a_match(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        answer = {
            'status': 'planet_epoch_not_identifiable',
            'matches': [],
            'candidate_matches': [{
                'planet': 'Jupiter', 'detection_id': 1,
                'measured_x_px': 55., 'measured_y_px': 42.,
                'separation_px': .096, 'unused_brightness_rank': 1}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (120, 100)).save(root/'source.png')
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(
                    root, {'source': str(root/'source.png')}, {'planets': answer})
            axis = save.call_args.args[0].axes[0]
            markers = [line for line in axis.lines if line.get_marker() == '*']
            labels = [item.get_text() for item in axis.texts]
            legend = ' '.join(item.get_text() for item in axis.get_legend().get_texts())
        self.assertEqual(len(markers), 1)
        np.testing.assert_allclose(markers[0].get_xydata(), [[55., 42.]])
        self.assertIn('Jupiter candidate', labels)
        self.assertIn('planet candidate', legend)

    def test_metadata_time_planet_match_is_labelled_separately_from_prediction(self):
        from PIL import Image
        from point_star_report import write_report_sky_overlay
        from point_star_planets import _plot_candidates
        answer = {
            'status': 'planet_epoch_not_identifiable', 'metadata_used': True,
            'matches': [],
            'metadata_matches': [{
                'planet': 'Jupiter', 'detection_id': 1,
                'measured_x_px': 55., 'measured_y_px': 42.,
                'separation_px': .172, 'unused_brightness_rank': 1}],
            'predicted_planets': [{
                'planet': 'Neptune', 'predicted_x_px': 90., 'predicted_y_px': 70.,
                'association_status': 'predicted_no_detected_source'}],
            'single_planet_candidate_count': 1,
            'observation_time_metadata': {
                'time_utc': '2026-01-15T23:46:44.942 UTC',
                'source': 'fits:PRIMARY:DATE-OBS'},
        }
        text = report_sections(self.sample_result(), {'planets': answer})['planets']
        self.assertEqual(text, 'Jupiter: FITS-time match, 0.17 px. Epoch: not identifiable.')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new('RGB', (120, 100)).save(root/'source.png')
            with patch('point_star_report.save_png') as save:
                write_report_sky_overlay(
                    root, {'source': str(root/'source.png')}, {'planets': answer})
            axis = save.call_args.args[0].axes[0]
            labels = [item.get_text() for item in axis.texts]
            legend = ' '.join(item.get_text() for item in axis.get_legend().get_texts())
            prediction = next(item for item in axis.texts
                              if item.get_text().startswith('Neptune'))
            with patch('point_star_plotting.save_png') as save:
                _plot_candidates(root/'source.png', root, answer)
            candidate_axis = save.call_args.args[0].axes[0]
            candidate_legend = ' '.join(
                item.get_text() for item in candidate_axis.get_legend().get_texts())
        self.assertIn('Jupiter — FITS-time match', labels)
        self.assertIn('Neptune (predicted—no detected source)', labels)
        self.assertIn('metadata-time planet match', legend)
        canvas = FigureCanvasAgg(axis.figure)
        canvas.draw()
        box = prediction.get_bbox_patch().get_window_extent(canvas.get_renderer())
        self.assertGreaterEqual(box.x0, axis.bbox.x0)
        self.assertLessEqual(box.x1, axis.bbox.x1)
        self.assertIn('Metadata-time source match shown; epoch not inferred',
                      candidate_axis.get_title())
        self.assertIn('metadata-time planet match', candidate_legend)

    def test_report_distinguishes_two_fixed_time_matches_from_one_planet_epoch_fit(self):
        planets = {
            'status': 'planet_epoch_not_identifiable', 'metadata_used': True,
            'matches': [], 'match_count': 0, 'single_planet_candidate_count': 1,
            'candidate_matches': [{
                'planet': 'Jupiter', 'detection_id': 1,
                'separation_arcmin': .69, 'separation_px': .096,
                'unused_brightness_rank': 1}],
            'metadata_matches': [
                {'planet': 'Jupiter', 'detection_id': 1,
                 'separation_arcmin': 1.23, 'separation_px': .17,
                 'unused_brightness_rank': 1},
                {'planet': 'Uranus', 'detection_id': 1480,
                 'separation_arcmin': .35, 'separation_px': .05,
                 'unused_brightness_rank': 1172}],
            'observation_time_metadata': {
                'time_utc': '2026-01-15T23:46:44.942 UTC',
                'source': 'fits:PRIMARY:DATE-OBS'},
        }

        text = report_sections(self.sample_result(), {'planets': planets})['planets']
        row = dict(table_rows(self.sample_result(), {'planets': planets}))['Planet epoch']

        self.assertEqual(
            text,
            'Jupiter: FITS-time match, 1.23 arcmin; sole epoch-fit candidate. '
            'Uranus: FITS-time match, 0.35 arcmin. Epoch: not identifiable.')
        self.assertEqual(text.count('Jupiter'), 1)
        self.assertEqual(text.count('Uranus'), 1)
        self.assertNotIn('source #', text)
        self.assertNotIn('brightness rank', text)
        self.assertNotIn('2026-01-15', text)
        self.assertNotIn('px', text)
        self.assertLessEqual(len(text.split()), 18)
        self.assertEqual(row,
                         'Epoch fit: Jupiter only, unresolved; fixed FITS: Jupiter + Uranus')

    def test_report_preserves_single_planet_candidate_date_and_uncertainty(self):
        planets = {
            'status': 'planet_epoch_not_identifiable', 'metadata_used': True,
            'matches': [], 'match_count': 0, 'single_planet_candidate_count': 1,
            'candidate_matches': [{
                'planet': 'Uranus', 'detection_id': 3496,
                'separation_arcmin': 1.5181459811173688}],
            'candidates': [{
                'epoch_tdb': '2018-03-01T10:24:57.639 TDB',
                'conditional_time_sigma_minutes': 1635.5785976416405,
                'matches': [{'planet': 'Uranus', 'detection_id': 3496}]}],
            'metadata_matches': [{
                'planet': 'Uranus', 'detection_id': 3496,
                'separation_arcmin': 1.8849412964862136}],
            'observation_time_metadata': {
                'time_utc': '2018-03-01T00:13:02.000 UTC',
                'source': 'fits:PRIMARY:DATE-OBS'},
        }

        text = report_sections(self.sample_result(), {'planets': planets})['planets']
        row = dict(table_rows(self.sample_result(), {'planets': planets}))['Planet epoch']

        self.assertEqual(
            text,
            'Uranus: blind candidate 2018-03-01T10:24:57.639 TDB ±27 h, '
            '1.52 arcmin; single-planet identity unconfirmed. '
            'FITS-time match, 1.88 arcmin.')
        self.assertEqual(
            row,
            'Blind candidate: Uranus, 2018-03-01T10:24:57.639 TDB ±27 h '
            '(unconfirmed); fixed FITS: Uranus')

    def test_page_one_interpretation_blocks_are_strongly_compacted(self):
        result = self.sample_result()
        result['camera']['detector_parity'] = 'mirrored'
        result['fit'].update(rms_arcmin=2.502, median_arcmin=1.738, p90_arcmin=3.933)
        science = {
            'stellar_epoch': {'status': 'conditional_epoch', 'epoch_jyear': 2006.1,
                              'fitted_count': 1380},
            'refraction': {'status': 'not_identifiable', 'refraction_a_arcsec': 0.3,
                           'refraction_b_arcsec': -0.002, 'delta_bic': -4.1},
            'photometry': {
                'photometric_zenith': {'status': 'not_identifiable'},
                'extinction_by_channel': {
                    channel: {'coefficient_mag_per_airmass': value,
                              'coefficient_sigma_mag_per_airmass': .01,
                              'fitted_count': 1377, 'airmass_range': [1., 2.5]}
                    for channel, value in zip('RGB', (.20, .21, .24))}},
            'planets': {'status': 'no_planet_match', 'matches': []},
        }

        sections = report_sections(result, science)

        self.assertLessEqual(len((sections['lens']+' '+sections['astrometry']).split()), 55)
        self.assertLessEqual(len(sections['atmosphere'].split()), 45)
        self.assertIn('mirrored detector parity', sections['lens'])
        self.assertIn('RMS 2.502 arcmin', sections['astrometry'])
        self.assertIn('kR=', sections['atmosphere'])
        self.assertIn('kG=', sections['atmosphere'])
        self.assertIn('kB=', sections['atmosphere'])

    def test_compact_planet_text_does_not_merge_different_source_associations(self):
        planets = {
            'status': 'planet_epoch_not_identifiable',
            'candidate_matches': [
                {'planet': 'Jupiter', 'detection_id': 9, 'separation_arcmin': .6},
                {'planet': 'Saturn', 'detection_id': 3, 'separation_arcmin': .8},
                {'planet': 'Saturn', 'detection_id': 4, 'separation_arcmin': 1.1}],
            'metadata_matches': [
                {'planet': 'Jupiter', 'detection_id': 1, 'separation_arcmin': 1.2}],
            'observation_time_metadata': {'source': 'fits:PRIMARY:DATE-OBS'},
        }

        text = report_sections(self.sample_result(), {'planets': planets})['planets']

        self.assertEqual(
            text,
            'Jupiter: FITS-time match, 1.20 arcmin; separate epoch-fit candidate. '
            'Saturn: epoch-fit candidate, 0.80 arcmin. Epoch: not identifiable.')
        self.assertEqual(text.count('Jupiter'), 1)
        self.assertEqual(text.count('Saturn'), 1)
        self.assertNotIn('1.10 arcmin', text)

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
        self.assertIn(r'\mathbf{P}', text)
        self.assertIn('detector-parity reflection', text)
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

    def test_rgb_photometry_plots_reverse_magnitude_axes_without_direction_annotations(self):
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
            for axis, channel, catalogue_band in zip(
                    figure.axes, ('R', 'G', 'B'), ('Gaia RP', 'Gaia G', 'Gaia BP')):
                self.assertTrue(axis.yaxis_inverted())
                self.assertTrue(axis.xaxis_inverted())
                self.assertEqual(axis.get_xlabel(), f'{catalogue_band} catalogue magnitude [mag]')
                self.assertEqual(axis.get_ylabel(),
                                 f'Camera {channel} instrumental magnitude [mag]')
                self.assertEqual([line.get_label() for line in axis.lines],
                                 ['robust soft-L1 line'])
            plt.close(figure)

    def test_rgb_photometry_report_fit_resists_one_severe_outlier(self):
        from point_star_report import photometry_page
        catalogue = np.arange(10., dtype=float)
        machine = 2.+1.5*catalogue
        machine[-1] = 1000.
        comparisons = {
            channel: {
                'catalogue_mag': catalogue,
                'machine_mag': machine,
                'catalogue_band': band,
            }
            for channel, band in zip('RGB', ('Gaia RP', 'Gaia G', 'Gaia BP'))
        }

        with patch('point_star_report.photometry_comparisons',
                   return_value=comparisons):
            figure = photometry_page(Path('.'))

        for axis in figure.axes:
            line = axis.lines[0]
            slope = np.polyfit(line.get_xdata(), line.get_ydata(), 1)[0]
            self.assertAlmostEqual(slope, 1.5, delta=.02)
            annotation = ' '.join(text.get_text() for text in axis.texts)
            self.assertIn('Robust LS:', annotation)
            self.assertIn('MAD scatter=', annotation)
            self.assertNotIn('OLS', annotation)
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


class JointFitPresentationTests(unittest.TestCase):
    """Catch hidden source pixels and fit participation mislabelled as lookup."""

    def joint_record(self):
        matches = [dict(planet=name, detection_id=i, measured_x_px=30.+i*15,
                        measured_y_px=40., predicted_x_px=31.+i*15,
                        predicted_y_px=41., separation_arcmin=2., separation_px=1.4)
                   for i, name in enumerate(('Mars', 'Jupiter', 'Saturn', 'Uranus'))]
        best = dict(matches=matches, epoch_tdb='2020-01-01T12:00:00', jd_tdb=2458850.,
                    planet_count=4, star_count=100, stellar_rms_arcmin=2., planet_rms_arcmin=2.,
                    eligible=True, bounded=False, cost=10.,
                    interval_95_jd_tdb=[2458849.9, None],
                    search_limits_jd_tdb=[2458849., 2458850.1],
                    profile=[dict(jd_tdb=2458849.9, cost=12.), dict(jd_tdb=2458850., cost=10.),
                             dict(jd_tdb=2458850.1, cost=11.)],
                    brightness=dict(status='soft_relative_evidence', channel='R', cost=.3))
        return dict(status='joint_epoch_ambiguous', adopted=False, best_index=0,
                    candidates=[best], reason='Physical zenith unresolved; upper interval truncated.',
                    supported_search_jd_tdb=[2400000., 2458850.1], initial_fit=dict(rms_arcmin=2.1),
                    metadata_comparison=dict(candidate_minus_metadata_seconds=3600., rows=[
                        dict(detection_id=i, metadata_predicted_x_px=32.+i*15,
                             metadata_predicted_y_px=42., metadata_residual_arcmin=3.)
                        for i in range(4)]))

    def test_joint_crops_show_unmarked_pixels_and_faithful_open_overlays(self):
        from copy import deepcopy
        from PIL import Image
        from point_star_joint_report import joint_figure
        joint = self.joint_record()
        before = deepcopy(joint)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pixels = np.zeros((100, 120, 3), dtype=np.uint8)
            pixels[39:43, 29:80] = [160, 180, 255]
            Image.fromarray(pixels).save(root/'source.png')
            fig = joint_figure(root, dict(source=str(root/'source.png'), joint_epoch=joint), {})
            self.addCleanup(plt.close, fig)
            images = [ax for ax in fig.axes if ax.images]
            self.assertEqual(len(images), 8, 'Each of four bodies needs raw and overlay crops')
            for i, match in enumerate(joint['candidates'][0]['matches']):
                raw, overlay = images[2*i:2*i+2]
                self.assertEqual(len(raw.lines)+len(raw.collections)+len(raw.patches)+len(raw.texts), 0,
                                 'Nothing may be drawn over the raw source pixels')
                for ax in (raw, overlay):
                    np.testing.assert_array_equal(ax.images[0].get_array(), pixels)
                    self.assertEqual(ax.images[0].get_interpolation(), 'nearest')
                self.assertEqual(raw.get_xlim(), overlay.get_xlim())
                self.assertEqual(raw.get_ylim(), overlay.get_ylim())
                np.testing.assert_allclose(overlay.lines[0].get_xydata(), [[30.+i*15, 40.]])
                np.testing.assert_allclose(overlay.lines[1].get_xydata(), [[31.+i*15, 41.]])
                np.testing.assert_allclose(overlay.lines[2].get_xydata(), [[32.+i*15, 42.]])
                for marker in overlay.lines:
                    self.assertEqual(marker.get_markerfacecolor(), 'none')
                    self.assertNotIn(marker.get_marker(), ('+', 'x', '*'))
                self.assertIsNone(overlay.get_legend(), 'Legends must not cover the crop')
            text = ' '.join(t.get_text() for t in fig.texts)
            self.assertIn('100 stars + 4 planets', text)
            self.assertIn('used in joint epoch fit', text)
            self.assertIn('not adopted', text)
            self.assertEqual(joint, before, 'Rendering must not change scientific records')

    def test_summary_separates_fit_participation_from_adoption(self):
        result = ReportTests().sample_result()
        joint = self.joint_record()
        for adopted in (False, True):
            with self.subTest(adopted=adopted):
                joint['adopted'] = adopted
                joint['status'] = 'joint_epoch_fitted' if adopted else 'joint_epoch_ambiguous'
                science = dict(joint_epoch=joint)
                prose = report_sections(result, science)['planets']
                self.assertIn('100 stars + 4 planets used in joint epoch fit', prose)
                table = dict(table_rows(result, science))
                self.assertIn('4 planets used in joint fit', table['Planet epoch'])
                self.assertIn('adopted' if adopted else 'not adopted', table['Planet epoch'])
                if adopted:
                    self.assertNotIn('not adopted', table['Planet epoch'])


if __name__ == '__main__':
    unittest.main()
