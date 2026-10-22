"""Blind time search recovers measured positions and preserves date aliases."""
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
import numpy as np
from astropy.io import fits
from point_star_barghini import BarghiniCamera


_PARALLEL_ORIGIN = 2451545.


def _parallel_vectors(name, jd):
    camera = BarghiniCamera.initial((300, 400), 180., np.eye(3))
    t = np.atleast_1d(jd)-_PARALLEL_ORIGIN
    if name == 'saturn':
        points = np.c_[120+2*(t-4.3), np.full(len(t), 100.)]
    elif name == 'jupiter':
        points = np.c_[np.full(len(t), 270.), 170+3*(t-4.3)]
    else:
        points = np.c_[220+1.5*(t-4.3), np.full(len(t), 210.)]
    return camera.to_sky(points)


class PlanetSearchTests(unittest.TestCase):
    def setUp(self):
        self.camera = BarghiniCamera.initial((300, 400), 180., np.eye(3))
        self.origin = 2451545.

    def search(self, tracks, positions, stop=10., step=1.):
        from point_star_planets import search_planet_epochs
        dates = self.origin + np.arange(0., stop + step/2, step)
        def vectors(name, jd):
            return self.camera.to_sky(tracks[name](np.atleast_1d(jd)-self.origin))
        grid = {name: vectors(name, dates) for name in tracks}
        sources = [dict(detection_id=str(i), x_px=x, y_px=y, saturated='True',
                        source_class='broad_blob', flux_above_background=100.)
                   for i, (x, y) in enumerate(positions)]
        return search_planet_epochs(self.camera, sources, dates, grid, vectors,
                                    gate_arcmin=20., positional_sigma_arcmin=4.,
                                    zenith_unit_vector=[0, 0, 1])

    def test_visibility_records_geometric_zenith_provenance(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin + np.arange(2.)
        vectors = lambda name, jd: self.camera.to_sky(
            np.tile([150., 130.], (len(np.atleast_1d(jd)), 1)))
        answer = search_planet_epochs(
            self.camera, [], dates, {'mars': vectors('mars', dates)}, vectors,
            zenith_unit_vector=[0., 0., 1.], zenith_status='not_identifiable',
            zenith_source='centred_full_horizon_geometry', latest_jd_tdb=self.origin+10.)
        self.assertEqual(answer['visibility']['zenith_source'],
                         'centred_full_horizon_geometry')
        self.assertEqual(answer['visibility']['source'],
                         'image-derived centred full-horizon geometry')

    def search_catalogue_constellation(self, mars_offset=.9, mars_speed=20.,
                                       include_jupiter=True, include_uranus=False):
        from point_star_planets import search_planet_epochs
        dates = self.origin + np.arange(11.)
        tracks = {
            'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
            'mars': lambda t: np.c_[220+mars_speed*(t-4.3), np.full(len(t), 210.)],
        }
        sources = [dict(detection_id='1', x_px=120., y_px=100.)]
        if include_jupiter:
            tracks['jupiter'] = lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)]
            sources.append(dict(detection_id='2', x_px=270., y_px=170.))
        sources.append(dict(detection_id='3', x_px=220+mars_offset, y_px=210.,
                            catalogue_star_id='chance-gaia-star',
                            catalogue_residual_px=.6, catalogue_residual_arcmin=12.))
        if include_uranus:
            tracks['uranus'] = lambda t: np.c_[np.full(len(t), 250.), np.full(len(t), 250.)]
            sources.append(dict(detection_id='4', x_px=250.7, y_px=250.,
                                catalogue_star_id='better-gaia-star',
                                catalogue_residual_px=.6, catalogue_residual_arcmin=12.))
        def vectors(name, jd):
            return self.camera.to_sky(tracks[name](np.atleast_1d(jd)-self.origin))
        grid = {name: vectors(name, dates) for name in tracks}
        return search_planet_epochs(
            self.camera, sources, dates, grid, vectors, gate_arcmin=20.,
            positional_sigma_arcmin=4., zenith_unit_vector=[0, 0, 1])

    def search_catalogue_case(self, tracks, sources, gate_arcmin=20.):
        from point_star_planets import search_planet_epochs
        dates = self.origin + np.arange(11.)
        sources = [dict(row, catalogue_residual_arcmin=(
            20*float(row['catalogue_residual_px'])
            if row.get('catalogue_residual_px') is not None else np.inf))
            for row in sources]
        def vectors(name, jd):
            return self.camera.to_sky(tracks[name](np.atleast_1d(jd)-self.origin))
        grid = {name: vectors(name, dates) for name in tracks}
        return search_planet_epochs(
            self.camera, sources, dates, grid, vectors, gate_arcmin=gate_arcmin,
            positional_sigma_arcmin=4., zenith_unit_vector=[0, 0, 1],
            latest_jd_tdb=self.origin+100.)

    def test_other_planets_use_fixed_epoch_and_visibility_without_changing_fit(self):
        from copy import deepcopy
        from point_star_planets import predict_other_planets
        answer = {'best_candidate_jd_tdb': self.origin + 4.3,
                  'matches': [{'planet': 'Mars', 'detection_id': 7}],
                  'searched_planets': ['mars', 'jupiter', 'uranus', 'neptune'],
                  'visibility': {'zenith_unit_vector': [0., 0., 1.]}}
        before = deepcopy(answer)
        calls = []
        def vectors(name, jd):
            calls.append((name, list(jd)))
            if name == 'neptune':
                return np.array([[0., 0., -1.]])
            point = [240., 160.] if name == 'jupiter' else [450., 150.]
            return self.camera.to_sky([point])
        rows = predict_other_planets(self.camera, answer, vectors)
        self.assertEqual(answer, before)
        self.assertEqual([r['planet'] for r in rows], ['Jupiter'])
        np.testing.assert_allclose([rows[0]['predicted_x_px'], rows[0]['predicted_y_px']],
                                   [240., 160.], atol=1e-7)
        self.assertTrue(all(date == [self.origin + 4.3] for name, date in calls))
        self.assertNotIn('mars', [name for name, date in calls])
        self.assertNotIn('detection_id', rows[0])

    def test_metadata_time_association_distinguishes_detected_and_predicted_planets(self):
        import point_star_planets
        self.assertTrue(hasattr(point_star_planets, 'associate_planets_at_metadata_time'))
        associate = point_star_planets.associate_planets_at_metadata_time
        detections = [
            dict(detection_id='1', x_px=150., y_px=130., saturated='True',
                 source_class='compact', flux_above_background=900.),
            dict(detection_id='2', x_px=190., y_px=150., saturated='False',
                 source_class='compact', flux_above_background=100.,
                 catalogue_star_id='gaia-star', catalogue_residual_px=.1,
                 catalogue_residual_arcmin=.1),
        ]
        positions = {'jupiter': [150.2, 130.1], 'neptune': [230., 150.],
                     'mars': [190.2, 150.]}
        calls = []
        def vectors(name, dates):
            calls.append((name, list(dates)))
            return self.camera.to_sky(np.tile(positions[name], (len(dates), 1)))
        metadata = {'status': 'selected', 'jd_tdb': self.origin+4.3,
                    'time_utc': '2000-01-05T19:12:00 UTC',
                    'source': 'fits:PRIMARY:DATE-OBS'}

        answer = associate(
            self.camera, detections, list(positions), vectors, metadata,
            gate_arcmin=30., positional_sigma_arcmin=3.,
            zenith_unit_vector=[0., 0., 1.])

        self.assertEqual(answer['status'], 'metadata_time_associated')
        self.assertEqual([(row['planet'], row['detection_id']) for row in answer['matches']],
                         [('Jupiter', 1)])
        self.assertAlmostEqual(answer['matches'][0]['separation_px'], np.hypot(.2, .1))
        self.assertEqual([row['planet'] for row in answer['predicted_without_source']],
                         ['Neptune', 'Mars'])
        self.assertTrue(all(row['association_status'] == 'predicted_no_detected_source'
                            for row in answer['predicted_without_source']))
        self.assertEqual(answer['epoch_source'], 'fits:PRIMARY:DATE-OBS')
        self.assertTrue(all(dates == [self.origin+4.3] for _, dates in calls))

    def test_metadata_time_association_uses_great_circle_arcminutes(self):
        from point_star_planets import associate_planets_at_metadata_time
        measured = np.array([[150.2, 130.]])
        predicted = np.array([[150., 130.]])
        measured_ray = self.camera.to_sky(measured)[0]
        predicted_ray = self.camera.to_sky(predicted)[0]
        expected_arcmin = np.degrees(np.arccos(
            np.clip(measured_ray @ predicted_ray, -1., 1.)))*60.
        detections = [dict(
            detection_id='1', x_px=measured[0, 0], y_px=measured[0, 1],
            saturated='False', source_class='compact', flux_above_background=100.)]
        metadata = {'status': 'selected', 'jd_tdb': self.origin+4.3,
                    'time_utc': '2000-01-05T19:12:00 UTC',
                    'source': 'fits:PRIMARY:DATE-OBS'}

        answer = associate_planets_at_metadata_time(
            self.camera, detections, ['uranus'],
            lambda name, dates: np.tile(predicted_ray, (len(dates), 1)), metadata,
            gate_arcmin=expected_arcmin+.01, positional_sigma_arcmin=.1,
            zenith_unit_vector=[0., 0., 1.])

        self.assertEqual(answer['matches'][0]['planet'], 'Uranus')
        self.assertAlmostEqual(answer['matches'][0]['separation_arcmin'],
                               expected_arcmin, places=8)
        self.assertAlmostEqual(answer['gate_arcmin'], expected_arcmin+.01)
        self.assertNotIn('gate_px', answer)

    def test_metadata_time_association_rejects_measured_source_below_horizon(self):
        from point_star_planets import associate_planets_at_metadata_time
        predicted_ray = self.camera.to_sky([[150., 130.]])[0]
        measured = np.array([[150.2, 130.]])
        measured_ray = self.camera.to_sky(measured)[0]
        zenith = predicted_ray-measured_ray
        zenith /= np.linalg.norm(zenith)
        self.assertGreater(predicted_ray @ zenith, 0.)
        self.assertLess(measured_ray @ zenith, 0.)
        detections = [dict(
            detection_id='1', x_px=measured[0, 0], y_px=measured[0, 1],
            saturated='False', source_class='compact', flux_above_background=100.)]
        metadata = {'status': 'selected', 'jd_tdb': self.origin+4.3,
                    'time_utc': '2000-01-05T19:12:00 UTC',
                    'source': 'fits:PRIMARY:DATE-OBS'}

        answer = associate_planets_at_metadata_time(
            self.camera, detections, ['uranus'],
            lambda name, dates: np.tile(predicted_ray, (len(dates), 1)), metadata,
            gate_arcmin=30., positional_sigma_arcmin=.1,
            zenith_unit_vector=zenith)

        self.assertEqual(answer['matches'], [])
        self.assertEqual(answer['predicted_without_source'][0]['planet'], 'Uranus')

    def test_blind_search_uses_great_circle_arcminute_gate(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(2.)
        measured = np.array([[150.2, 130.]])
        predicted = np.array([[150., 130.]])
        measured_ray = self.camera.to_sky(measured)[0]
        predicted_ray = self.camera.to_sky(predicted)[0]
        expected_arcmin = np.degrees(np.arccos(
            np.clip(measured_ray @ predicted_ray, -1., 1.)))*60.
        sources = [dict(detection_id='1', x_px=measured[0, 0], y_px=measured[0, 1])]
        vectors = lambda name, jd: np.tile(predicted_ray, (len(np.atleast_1d(jd)), 1))
        grid = {'uranus': vectors('uranus', dates)}

        accepted = search_planet_epochs(
            self.camera, sources, dates, grid, vectors,
            gate_arcmin=expected_arcmin+.01, positional_sigma_arcmin=.1,
            zenith_unit_vector=[0., 0., 1.], latest_jd_tdb=self.origin+10.)
        rejected = search_planet_epochs(
            self.camera, sources, dates, grid, vectors,
            gate_arcmin=expected_arcmin-.01, positional_sigma_arcmin=.1,
            zenith_unit_vector=[0., 0., 1.], latest_jd_tdb=self.origin+10.)

        self.assertEqual(accepted['match_count'], 1)
        self.assertAlmostEqual(accepted['matches'][0]['separation_arcmin'],
                               expected_arcmin, places=8)
        self.assertEqual(accepted['gate_arcmin'], expected_arcmin+.01)
        self.assertNotIn('gate_px', accepted)
        self.assertEqual(rejected['match_count'], 0)

    def test_targeted_planet_recovery_retains_multichannel_rejected_peak(self):
        from point_star_detection import detect_stars
        from point_star_image import load_scientific_image
        from point_star_planets import recover_predicted_planet_sources
        rng = np.random.default_rng(20260918)
        yy, xx = np.mgrid[:120, :160]
        planes = []
        for amplitude in (90., 130., 110.):
            plane = 200.+rng.normal(0., .7, xx.shape)
            plane += amplitude*np.exp(-((xx-80.05)**2+(yy-60.05)**2)/(2*.5**2))
            planes.append(plane)
        # A strong one-channel event remains ineligible for astronomical recovery.
        planes[1][85, 110] += 300.
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder)/'undersampled.fits'
            fits.PrimaryHDU(np.asarray(planes, dtype=np.float32)).writeto(image_path)
            scientific = load_scientific_image(image_path)
            accepted, audit = detect_stars(
                scientific.luminance, saturated_mask=scientific.saturated_mask,
                saturation_known=True)
            self.assertTrue(any(
                row['reason'] == 'too_sharp' and
                np.hypot(row['x_px']-80., row['y_px']-60.) < 1.
                for row in audit['rejected']))
            predictions = [
                dict(planet='Uranus', predicted_x_px=80.05, predicted_y_px=60.05),
                dict(planet='Neptune', predicted_x_px=110., predicted_y_px=85.),
            ]

            recovered = recover_predicted_planet_sources(
                scientific, self.camera, predictions, accepted,
                audit['rejected'], audit['valid_mask'], gate_arcmin=30.)

        self.assertEqual(len(recovered), 1)
        source = recovered[0]
        self.assertEqual(source['recovery_planet'], 'Uranus')
        self.assertEqual(source['source_class'], 'targeted_planet_recovery')
        self.assertEqual(source['morphology_rejection_reason'], 'too_sharp')
        self.assertGreaterEqual(source['significant_channels'], 2)
        self.assertLess(np.hypot(source['x_px']-80.05, source['y_px']-60.05), .35)

    def test_targeted_recovery_excludes_selected_sources_and_invalid_footprint(self):
        from point_star_image import load_scientific_image
        from point_star_planets import recover_predicted_planet_sources
        yy, xx = np.mgrid[:120, :160]
        planes = np.stack([
            200.+amplitude*np.exp(-((xx-80.05)**2+(yy-60.05)**2)/(2*.5**2))
            for amplitude in (90., 130., 110.)])
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder)/'undersampled.fits'
            fits.PrimaryHDU(planes.astype(np.float32)).writeto(image_path)
            scientific = load_scientific_image(image_path)
            predictions = [dict(
                planet='Uranus', predicted_x_px=80.05, predicted_y_px=60.05)]
            rejected = [dict(x_px='80.0', y_px='60.0', reason='too_sharp')]
            valid = np.ones((120, 160), dtype=bool)
            accepted = [dict(
                detection_id='1', x_px=80.05, y_px=60.05,
                major_sigma_px=.5, source_class='compact')]

            duplicate = recover_predicted_planet_sources(
                scientific, self.camera, predictions, accepted,
                rejected, valid, gate_arcmin=30.)
            valid[60, 80] = False
            outside = recover_predicted_planet_sources(
                scientific, self.camera, predictions, [],
                rejected, valid, gate_arcmin=30.)

        self.assertEqual(duplicate, [])
        self.assertEqual(outside, [])

    def test_metadata_time_association_requires_selected_metadata(self):
        import point_star_planets
        self.assertTrue(hasattr(point_star_planets, 'associate_planets_at_metadata_time'))
        answer = point_star_planets.associate_planets_at_metadata_time(
            self.camera, [], ['jupiter'], lambda *_: None,
            {'status': 'unavailable'}, gate_arcmin=30., positional_sigma_arcmin=3.,
            zenith_unit_vector=[0., 0., 1.])
        self.assertEqual(answer, {'status': 'metadata_time_unavailable',
                                  'matches': [], 'predicted_without_source': []})

    def test_metadata_recovery_is_reassociated_as_uranus(self):
        from point_star_detection import detect_stars
        from point_star_image import load_scientific_image
        from point_star_planets import associate_metadata_planets_with_recovery
        rng = np.random.default_rng(20260919)
        yy, xx = np.mgrid[:300, :400]
        planes = []
        for amplitude in (90., 130., 110.):
            plane = 200.+rng.normal(0., .7, xx.shape)
            plane += amplitude*np.exp(-((xx-150.05)**2+(yy-130.05)**2)/(2*.5**2))
            planes.append(plane)
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder)/'uranus.fits'
            fits.PrimaryHDU(np.asarray(planes, dtype=np.float32)).writeto(image_path)
            scientific = load_scientific_image(image_path)
            _, audit = detect_stars(
                scientific.luminance, saturated_mask=scientific.saturated_mask,
                saturation_known=True)
            predicted_ray = self.camera.to_sky([[150.05, 130.05]])[0]
            metadata = {'status': 'selected', 'jd_tdb': self.origin+4.3,
                        'source': 'fits:PRIMARY:DATE-OBS'}

            association, recovered = associate_metadata_planets_with_recovery(
                scientific, self.camera, [], audit['rejected'], audit['valid_mask'],
                ['uranus'],
                lambda name, dates: np.tile(predicted_ray, (len(dates), 1)), metadata,
                gate_arcmin=30., positional_sigma_arcmin=3.,
                zenith_unit_vector=[0., 0., 1.])

        self.assertEqual(len(recovered), 1)
        self.assertEqual(association['matches'][0]['planet'], 'Uranus')
        self.assertEqual(association['matches'][0]['source_origin'],
                         'metadata_predicted_recovery')
        self.assertEqual(association['predicted_without_source'], [])

    def test_recovered_source_photometry_records_count_rates(self):
        from point_star_image import load_scientific_image
        from point_star_planets import append_recovered_source_photometry
        yy, xx = np.mgrid[:80, :100]
        planes = np.asarray([
            200.+100*np.exp(-((xx-50.)**2+(yy-40.)**2)/(2*1.1**2)),
            200.+120*np.exp(-((xx-50.)**2+(yy-40.)**2)/(2*1.1**2)),
            200.+80*np.exp(-((xx-50.)**2+(yy-40.)**2)/(2*1.1**2)),
        ], dtype=np.float32)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image_path = root/'source.fits'
            hdu = fits.PrimaryHDU(planes)
            hdu.header['EXPOSURE'] = 20.
            hdu.writeto(image_path)
            scientific = load_scientific_image(image_path)
            fields = [
                'detection_id', 'x_px', 'y_px', 'star_id', 'identified_as_star',
                'source_class', 'saturated', 'saturation_known', 'saturated_channels',
                'exposure_seconds', 'exposure_status', 'exposure_source',
                'R_flux', 'R_count_rate_adu_per_s', 'R_saturated',
                'R_measurement_method', 'R_saturated_pixels_in_aperture',
                'R_wing_fit_status', 'R_wing_fit_total_counts_adu',
                'R_wing_fit_count_rate_adu_per_s', 'R_wing_fit_x_px',
                'R_wing_fit_y_px', 'R_wing_fit_rms_adu',
                'R_wing_fit_unsaturated_pixels']
            with (root/'source_photometry.csv').open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
            recovered = [dict(
                detection_id='1', x_px=50., y_px=40.,
                source_class='targeted_planet_recovery', saturated=False,
                saturation_known=True, saturated_channels='', major_sigma_px=1.1)]

            rows = append_recovered_source_photometry(root, scientific, recovered)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['exposure_seconds'], 20.)
            self.assertAlmostEqual(float(rows[0]['R_count_rate_adu_per_s']),
                                   float(rows[0]['R_flux'])/20.)
            with (root/'source_photometry.csv').open() as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(saved[0]['source_class'], 'targeted_planet_recovery')

    def test_no_predictions_without_a_fitted_candidate_or_visibility(self):
        from point_star_planets import predict_other_planets
        from unittest.mock import Mock
        vectors = Mock(side_effect=AssertionError('No epoch to predict'))
        for answer in ({}, {'matches': [{'planet': 'Mars'}]},
                       {'matches': [{'planet': 'Mars'}], 'best_candidate_jd_tdb': self.origin}):
            self.assertEqual(predict_other_planets(self.camera, answer, vectors), [])
        vectors.assert_not_called()

    def test_single_planet_alias_does_not_project_an_unearned_constellation(self):
        from point_star_planets import predict_other_planets
        calls = []
        def vectors(name, jd):
            calls.append((name, list(jd)))
            return self.camera.to_sky([[240., 160.]])
        answer = {'status': 'planet_epoch_not_identifiable',
                  'match_count': 1,
                  'matches': [{'planet': 'Mercury', 'detection_id': 7}],
                  'best_candidate_jd_tdb': self.origin + 4.3,
                  'searched_planets': ['mercury', 'jupiter'],
                  'visibility': {'zenith_unit_vector': [0., 0., 1.]},
                  'candidates': [{'match_count': 1, 'epoch_tdb': 'an audited alias'}]}
        self.assertEqual(predict_other_planets(self.camera, answer, vectors), [])
        self.assertEqual(calls, [])

    def test_two_planets_recover_date_from_positions_without_epoch_hint(self):
        tracks = {'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
                  'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)]}
        result = self.search(tracks, [(120., 100.), (270., 170.)])
        self.assertEqual(result['match_count'], 2)
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin, 4.3, places=4)
        self.assertFalse(result['metadata_used'])
        self.assertEqual(len({r['detection_id'] for r in result['matches']}), 2)
        self.assertTrue(all(r['saturated'] for r in result['matches']))

    def test_complete_search_is_deterministic_for_one_two_and_four_workers(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(11.)
        names = ('saturn', 'jupiter', 'mars')
        grid = {name: _parallel_vectors(name, dates) for name in names}
        positions = ([120., 100.], [270., 170.], [220., 210.])
        sources = [dict(detection_id=str(index), x_px=x, y_px=y,
                        saturated='True', source_class='broad_blob',
                        flux_above_background=100.)
                   for index, (x, y) in enumerate(positions)]
        answers = []
        with tempfile.TemporaryDirectory() as temporary:
            old_cwd = os.getcwd()
            try:
                os.chdir(temporary)
                for workers in (1, 2, 4):
                    answer = search_planet_epochs(
                        self.camera, sources, dates, grid, _parallel_vectors,
                        gate_arcmin=20., positional_sigma_arcmin=4.,
                        zenith_unit_vector=[0, 0, 1], planet_workers=workers,
                        latest_jd_tdb=self.origin+100.)
                    answer.pop('planet_search_performance')
                    answers.append(answer)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(list(os.scandir(temporary)), [])
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(answers[0], answers[2])

    def test_fast_planet_between_daily_samples_is_not_missed(self):
        tracks = {'mercury': lambda t: np.c_[150+30*(t-.37), np.full(len(t), 130.)]}
        result = self.search(tracks, [(150., 130.)], stop=1.)
        self.assertEqual(result['match_count'], 1)
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin, .37, places=4)
        self.assertEqual(result['status'], 'planet_epoch_ambiguous')

    def test_interpolation_and_daily_grid_cannot_override_exact_gate(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(5.)
        source = [dict(detection_id='1', x_px=150., y_px=130.)]
        proposed = self.camera.to_sky(np.tile([150., 130.], (len(dates), 1)))

        def exact_outside(name, jd):
            return self.camera.to_sky(np.tile([155., 130.], (len(np.atleast_1d(jd)), 1)))

        rejected = search_planet_epochs(
            self.camera, source, dates, {'mars': proposed}, exact_outside,
            gate_arcmin=30., zenith_unit_vector=[0, 0, 1])
        self.assertEqual(rejected['match_count'], 0)

        coarse_offset = self.camera.to_sky(np.tile([151.5, 130.], (len(dates), 1)))

        def exact_inside(name, jd):
            return self.camera.to_sky(np.tile([150., 130.], (len(np.atleast_1d(jd)), 1)))

        accepted = search_planet_epochs(
            self.camera, source, dates, {'mars': coarse_offset}, exact_inside,
            gate_arcmin=30., zenith_unit_vector=[0, 0, 1])
        self.assertEqual(accepted['match_count'], 1)
        self.assertAlmostEqual(accepted['matches'][0]['separation_px'], 0., places=12)

    def test_repeated_planet_positions_preserve_separate_date_solutions(self):
        tracks = {'saturn': lambda t: np.c_[150+(t-5)*(t-15), np.full(len(t), 130.)]}
        result = self.search(tracks, [(150., 130.)], stop=20.)
        dates = [r['jd_tdb']-self.origin for r in result['candidates']]
        self.assertTrue(any(abs(t-5) < .01 for t in dates))
        self.assertTrue(any(abs(t-15) < .01 for t in dates))
        self.assertEqual(result['status'], 'planet_epoch_ambiguous')
        self.assertIsNone(result['derived_epoch_utc'])

    def test_joint_solution_between_individual_minima_is_not_missed(self):
        tracks = {'saturn': lambda t: np.c_[120+.7*(t-4), np.full(len(t), 100.)],
                  'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+.7*(t-6)]}
        result = self.search(tracks, [(120., 100.), (270., 170.)])
        self.assertEqual(result['match_count'], 2)
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin,
                               4.98665717, places=5)

    def test_distinct_minima_less_than_two_days_apart_survive(self):
        tracks = {'saturn': lambda t: np.c_[150+10*(t-4)*(t-5), np.full(len(t), 130.)]}
        result = self.search(tracks, [(150., 130.)], stop=8., step=.1)
        dates = [r['jd_tdb']-self.origin for r in result['candidates']]
        self.assertTrue(any(abs(t-4) < .01 for t in dates))
        self.assertTrue(any(abs(t-5) < .01 for t in dates))

    def test_event_boundaries_do_not_create_false_date_aliases(self):
        tracks = {'saturn': lambda t: np.c_[120+t-5, np.full(len(t), 100.)],
                  'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+t-5],
                  'mars': lambda t: np.c_[200+10*(t-5.7), np.full(len(t), 200.)]}
        result = self.search(tracks, [(120., 100.), (270., 170.), (200., 200.)])
        best = [c for c in result['candidates'] if c['match_count'] == 3]
        self.assertEqual(len(best), 1)
        self.assertAlmostEqual(best[0]['jd_tdb']-self.origin, 5.68642928, places=5)

    def test_one_source_cannot_count_as_two_planets(self):
        track = lambda t: np.c_[150+2*(t-4.3), np.full(len(t), 130.)]
        result = self.search({'saturn': track, 'jupiter': track}, [(150., 130.)])
        self.assertEqual(result['match_count'], 1)

    def test_planet_can_challenge_a_poor_catalogue_association(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin + np.arange(11.)
        def vectors(name, jd):
            t = np.atleast_1d(jd)-self.origin
            return self.camera.to_sky(np.c_[150+2*(t-4.3), np.full(len(t), 130.)])
        row = dict(detection_id='1', x_px=150., y_px=130., saturated='True',
                   catalogue_star_id='wrong-star', catalogue_residual_px=3.,
                   catalogue_residual_arcmin=60.)
        result = search_planet_epochs(self.camera, [row], dates, {'saturn': vectors('saturn', dates)},
                                     vectors, gate_arcmin=20., positional_sigma_arcmin=10.,
                                     zenith_unit_vector=[0, 0, 1])
        self.assertEqual(result['match_count'], 1)
        self.assertEqual(result['matches'][0]['catalogue_star_id'], 'wrong-star')
        self.assertGreater(result['matches'][0]['improvement_over_star_chi2'], 9.)
        row['catalogue_residual_px'] = .1
        row['catalogue_residual_arcmin'] = 2.
        result = search_planet_epochs(self.camera, [row], dates, {'saturn': vectors('saturn', dates)},
                                     vectors, gate_arcmin=20., positional_sigma_arcmin=10.,
                                     zenith_unit_vector=[0, 0, 1])
        self.assertEqual(result['match_count'], 0)

    def test_two_planet_constellation_can_recruit_better_planet_over_gaia(self):
        result = self.search_catalogue_constellation()

        self.assertEqual(result['match_count'], 3)
        self.assertEqual({row['planet'] for row in result['matches']},
                         {'Mars', 'Jupiter', 'Saturn'})
        mars = next(row for row in result['matches'] if row['planet'] == 'Mars')
        self.assertEqual(mars['detection_id'], 3)
        self.assertEqual(mars['catalogue_star_id'], 'chance-gaia-star')
        self.assertGreater(mars['improvement_over_star_chi2'], 0.)
        self.assertTrue(mars['constellation_override'])
        # Mars begins 0.9 px from the source, worse than the 0.6 px Gaia
        # alternative. Joint least squares moves to
        # dt=(20*.9)/(2**2+3**2+20**2)=0.0435835351 day, where Mars wins.
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin,
                               4.34359078, places=5)

    def test_constellation_does_not_displace_a_better_gaia_position(self):
        result = self.search_catalogue_constellation(mars_offset=.7, mars_speed=0.)
        self.assertEqual(result['match_count'], 2)
        self.assertEqual({row['planet'] for row in result['matches']},
                         {'Jupiter', 'Saturn'})

    def test_invalid_fourth_override_does_not_hide_valid_third_planet(self):
        tracks = {
            'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
            'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)],
            'mars': lambda t: np.c_[220+1*(t-4.3), np.full(len(t), 210.)],
            'uranus': lambda t: np.c_[250+20*(t-4.3), np.full(len(t), 250.)],
        }
        sources = [
            dict(detection_id='1', x_px=120., y_px=100.),
            dict(detection_id='2', x_px=270., y_px=170.),
            dict(detection_id='3', x_px=220.5, y_px=210.,
                 catalogue_star_id='mars-gaia', catalogue_residual_px=.49),
            dict(detection_id='4', x_px=249.7, y_px=250.,
                 catalogue_star_id='uranus-gaia', catalogue_residual_px=.005),
        ]
        result = self.search_catalogue_case(tracks, sources)
        self.assertEqual(result['match_count'], 3)
        self.assertEqual({row['planet'] for row in result['matches']},
                         {'Mars', 'Jupiter', 'Saturn'})

    def test_rejected_nearer_source_does_not_hide_valid_planet_source(self):
        tracks = {
            'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
            'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)],
            'mars': lambda t: np.c_[220+1*(t-4.3), np.full(len(t), 210.)],
        }
        sources = [
            dict(detection_id='1', x_px=120., y_px=100.),
            dict(detection_id='2', x_px=270., y_px=170.),
            dict(detection_id='3', x_px=220.2, y_px=210.,
                 catalogue_star_id='tight-gaia', catalogue_residual_px=.10),
            dict(detection_id='4', x_px=220.5, y_px=210.,
                 catalogue_star_id='valid-gaia', catalogue_residual_px=.59),
        ]
        result = self.search_catalogue_case(tracks, sources)
        self.assertEqual({(row['planet'], row['detection_id']) for row in result['matches']},
                         {('Saturn', 1), ('Jupiter', 2), ('Mars', 4)})

    def test_valid_override_identities_remain_auditable_and_ambiguous(self):
        tracks = {
            'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
            'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)],
            'mars': lambda t: np.c_[220+20*(t-4.3), np.full(len(t), 210.)],
        }
        sources = [
            dict(detection_id='1', x_px=120., y_px=100.),
            dict(detection_id='2', x_px=270., y_px=170.),
            dict(detection_id='3', x_px=222.9, y_px=210.,
                 catalogue_star_id='later-gaia', catalogue_residual_px=.59),
            dict(detection_id='4', x_px=217.1, y_px=210.,
                 catalogue_star_id='earlier-gaia', catalogue_residual_px=.59),
        ]
        result = self.search_catalogue_case(tracks, sources, gate_arcmin=60.)
        three_body = [candidate for candidate in result['candidates']
                      if candidate['match_count'] == 3]
        self.assertEqual({next(row['detection_id'] for row in candidate['matches']
                               if row['planet'] == 'Mars')
                          for candidate in three_body}, {3, 4})
        self.assertEqual(result['status'], 'planet_epoch_ambiguous')
        self.assertEqual(result['competing_candidates'], 1)

    def test_two_planet_constellation_can_recruit_uranus(self):
        tracks = {
            'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
            'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)],
            'uranus': lambda t: np.c_[250+20*(t-4.3), np.full(len(t), 250.)],
        }
        sources = [
            dict(detection_id='1', x_px=120., y_px=100.),
            dict(detection_id='2', x_px=270., y_px=170.),
            dict(detection_id='3', x_px=250.9, y_px=250.,
                 catalogue_star_id='chance-gaia-star', catalogue_residual_px=.6),
        ]
        result = self.search_catalogue_case(tracks, sources)
        self.assertEqual(result['match_count'], 3)
        uranus = next(row for row in result['matches'] if row['planet'] == 'Uranus')
        self.assertTrue(uranus['constellation_override'])
        self.assertLess(uranus['separation_px'], uranus['catalogue_residual_px'])

    def test_one_planet_anchor_cannot_unlock_a_catalogue_override(self):
        result = self.search_catalogue_constellation(include_jupiter=False)
        self.assertEqual(result['match_count'], 1)
        self.assertEqual(result['matches'][0]['planet'], 'Saturn')

    def test_constellation_override_is_preserved_in_audit_products(self):
        import csv
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from point_star_planets import fit_blind_planet_epoch
        dates = self.origin + np.arange(11.)
        tracks = {
            'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
            'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)],
            'mars': lambda t: np.c_[220+4*(t-4.3), np.full(len(t), 210.)],
        }
        def vectors(name, jd):
            return self.camera.to_sky(tracks[name](np.atleast_1d(jd)-self.origin))
        grid = {name: vectors(name, dates) for name in tracks}
        rows = [
            dict(detection_id='1', x_px=120., y_px=100., saturated='False',
                 source_class='compact', flux_above_background=100.),
            dict(detection_id='2', x_px=270., y_px=170., saturated='False',
                 source_class='compact', flux_above_background=90.),
            dict(detection_id='3', x_px=220.1, y_px=210., saturated='False',
                 source_class='compact', flux_above_background=80.),
            dict(detection_id='4', x_px=219.9, y_px=210., saturated='False',
                 source_class='compact', flux_above_background=70.),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output/'dots').mkdir()
            with (output/'dots/star_candidates.csv').open('w') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
            (output/'star_coordinates.csv').write_text(
                'detection_id,star_id,residual_px,residual_arcmin\n'
                '3,chance-gaia-star,0.6,12.0\n'
                '4,other-chance-gaia-star,0.6,12.0\n')
            (output/'photometric_zenith.json').write_text(
                '{"status": "conditional_zenith", "zenith_unit_vector": [0,0,1]}')
            source = output/'image.png'
            Image.new('L', (self.camera.shape[1], self.camera.shape[0]), 100).save(source)
            result = {'camera': self.camera.serialise(),
                      'fit': {'rms_px': .2, 'rms_arcmin': 4.},
                      'source': str(source),
                      'causal_epoch_ceiling': {'jd_tdb': self.origin+100,
                                               'source': 'test clock'}}
            search_context = {
                'planet_search_mode': 'metadata_conditioned',
                'metadata_used': True,
                'metadata_search_half_width_days': 1.,
                'observation_time_metadata': {
                    'time_utc': '2000-01-06T00:00:00.000 UTC',
                    'source': 'fits:PRIMARY:DATE-OBS',
                    'jd_tdb': self.origin+4.5,
                },
            }
            with patch('point_star_planet_ephemeris.load_ephemeris',
                       return_value=(dates, grid, {})), \
                 patch('point_star_planet_ephemeris.planet_vectors', side_effect=vectors), \
                 patch('point_star_planets._plot_candidates'):
                answer = fit_blind_planet_epoch(
                    source, output, result, search_context=search_context)

            mars = next(row for row in answer['matches'] if row['planet'] == 'Mars')
            self.assertTrue(mars['constellation_override'])
            self.assertEqual(answer['source_identity_alternatives']['3'], ['Mars'])
            self.assertEqual(answer['source_identity_alternatives']['4'], ['Mars'])
            self.assertEqual(answer['status'], 'planet_epoch_ambiguous')
            self.assertIn('metadata-conditioned trajectory-segment search',
                          answer['method'])
            self.assertIn('selected observation time bounds this local search',
                          answer['limitation'])
            self.assertNotIn('No site, image date', answer['limitation'])
            self.assertIn('coherent three-or-more-planet constellation',
                          answer['candidate_selection'])
            saved = json.loads((output/'planet_epoch.json').read_text())
            self.assertTrue(next(row for row in saved['matches']
                                 if row['planet'] == 'Mars')['constellation_override'])
            with (output/'planet_candidates.csv').open() as handle:
                csv_rows = list(csv.DictReader(handle))
            saved_mars_rows = [row for row in csv_rows if row['planet'] == 'Mars']
            self.assertEqual({row['detection_id'] for row in saved_mars_rows}, {'3', '4'})
            saved_by_detection = {row['detection_id']: row for row in saved_mars_rows}
            self.assertTrue(all(row['constellation_override'] == 'True'
                                for row in saved_mars_rows))
            self.assertEqual(saved_by_detection['3']['catalogue_star_id'],
                             'chance-gaia-star')
            self.assertEqual(saved_by_detection['4']['catalogue_star_id'],
                             'other-chance-gaia-star')

    def test_integrated_search_ignores_poisoned_site_date_and_stellar_epoch(self):
        import csv, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from point_star_planets import fit_blind_planet_epoch
        dates = self.origin+np.arange(11.)
        def vectors(name, jd):
            t = np.atleast_1d(jd)-self.origin
            return self.camera.to_sky(np.c_[150+2*(t-4.3), np.full(len(t), 130.)])
        grid = {'saturn': vectors('saturn', dates)}
        row = dict(detection_id='1', x_px=150., y_px=130., saturated='True')
        with tempfile.TemporaryDirectory() as tmp:
            answers = []
            for index, year in enumerate(('not-a-date', '2150-01-01')):
                output = Path(tmp)/str(index); (output/'dots').mkdir(parents=True)
                with (output/'dots/star_candidates.csv').open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
                (output/'star_coordinates.csv').write_text('detection_id,star_id,residual_px\n')
                (output/'photometric_zenith.json').write_text('{"status": "conditional_zenith", "zenith_unit_vector": [0,0,1]}')
                from PIL import Image
                source = output/f'warwick_{year}.png'
                Image.new('L', (self.camera.shape[1], self.camera.shape[0]), 100).save(source)
                result = {'camera': self.camera.serialise(), 'fit': {'rms_px': .5},
                          'source': str(source),
                          'observation': {'time_utc': year, 'latitude_deg': 999},
                          'stellar_epoch': {'epoch_jyear': 1800+index*300},
                          'causal_epoch_ceiling': {'jd_tdb': self.origin+100, 'source': 'test clock'}}
                with patch('point_star_planet_ephemeris.load_ephemeris', return_value=(dates, grid, {})) as load, \
                     patch('point_star_planet_ephemeris.planet_vectors', side_effect=vectors), \
                     patch('point_star_planets._plot_candidates'), \
                     patch('point_star_report.observation_metadata', side_effect=AssertionError('Metadata read')):
                    answers.append(fit_blind_planet_epoch(result['source'], output, result))
                load.assert_called_once_with(1850., 2036.)
            for answer in answers:
                performance = answer.pop('planet_search_performance')
                self.assertEqual(performance['schema_version'], 1)
                self.assertGreaterEqual(performance['seconds']['total_planet_stage'], 0.)
                self.assertEqual(performance['counts']['refined_visits'], 1)
            self.assertEqual(answers[0], answers[1])
            saved = json.loads((Path(tmp)/'0/planet_epoch.json').read_text())
            standalone = json.loads((Path(tmp)/'0/planet_search_performance.json').read_text())
            self.assertEqual(saved['planet_search_performance'], standalone)

    def test_printed_epoch_list_and_plot_preserve_all_candidates(self):
        import contextlib, io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from point_star_planets import write_epoch_diagnostics
        answer = {'status': 'planet_epoch_ambiguous', 'metadata_used': True,
                  'planet_search_mode': 'metadata_conditioned',
                  'observation_time_metadata': {
                      'time_utc': '2018-09-16T00:13:55.000 UTC',
                      'source': 'fits:PRIMARY:DATE-OBS'},
                  'candidates': [
            {'epoch_tdb': '2000-01-01T00:00:00 TDB', 'jd_tdb': self.origin,
             'rms_arcmin': 4., 'rms_px': .2,
             'conditional_time_sigma_minutes': 60., 'matches': [{'planet': 'Saturn', 'detection_id': 4}]},
            {'epoch_tdb': '2030-01-01T00:00:00 TDB', 'jd_tdb': self.origin+10957.,
             'rms_arcmin': 8., 'rms_px': .4,
             'conditional_time_sigma_minutes': 120., 'matches': [{'planet': 'Mars', 'detection_id': 8}]}]}
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as printed:
            with patch('point_star_plotting.save_png') as save:
                write_epoch_diagnostics(Path(tmp), answer)
            self.assertIn('2000-01-01', printed.getvalue())
            self.assertIn('2030-01-01', printed.getvalue())
            self.assertIn('Saturn', printed.getvalue())
            self.assertIn('Mars', printed.getvalue())
            self.assertIn('Metadata-conditioned planetary candidates', printed.getvalue())
            self.assertIn('fits:PRIMARY:DATE-OBS', printed.getvalue())
            self.assertNotIn('Blind planetary epoch candidates', printed.getvalue())
            self.assertEqual(save.call_args.args[1].name, 'planet_epoch_candidates.png')
            self.assertTrue((Path(tmp)/'planet_epoch_candidates.txt').is_file())

    def test_metadata_search_progress_is_not_labelled_blind(self):
        import contextlib, io
        from point_star_planets import search_planet_epochs
        dates = self.origin + np.arange(2.)
        def vectors(name, jd):
            return self.camera.to_sky(
                np.tile([250., 230.], (len(np.atleast_1d(jd)), 1)))
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            search_planet_epochs(
                self.camera,
                [dict(detection_id='1', x_px=250., y_px=230.)],
                dates, {'mars': vectors('mars', dates)}, vectors,
                zenith_unit_vector=[0, 0, 1], search_label='Metadata planets')
        self.assertIn('Metadata planets:', printed.getvalue())
        self.assertNotIn('Blind planets:', printed.getvalue())

    def test_metadata_accuracy_records_fitted_date_error_and_all_offsets(self):
        from point_star_planets import annotate_metadata_accuracy
        answer = {
            'metadata_used': True,
            'observation_time_metadata': {
                'time_utc': '2000-01-01T12:00:00.000 UTC',
                'source': 'fits:PRIMARY:DATE-OBS',
                'jd_tdb': self.origin,
            },
            'best_candidate_jd_tdb': self.origin+.25,
            'candidates': [
                {'jd_tdb': self.origin+.25, 'match_count': 3, 'rms_px': .2},
                {'jd_tdb': self.origin-.5, 'match_count': 2, 'rms_px': .4},
            ],
        }
        result = annotate_metadata_accuracy(answer)
        validation = result['metadata_accuracy']
        self.assertEqual(validation['status'], 'local_planet_epoch_compared')
        self.assertEqual(validation['reference_source'], 'fits:PRIMARY:DATE-OBS')
        self.assertAlmostEqual(validation['planet_minus_metadata_seconds'], 21600.)
        self.assertAlmostEqual(validation['absolute_timing_error_seconds'], 21600.)
        self.assertEqual([row['metadata_offset_seconds'] for row in result['candidates']],
                         [21600., -43200.])
        self.assertIn('metadata-supplied local interval', validation['limitation'])

    def test_below_horizon_measured_source_is_rejected(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(3.)
        ray = self.camera.to_sky([[150., 130.]])[0]
        def vectors(name, jd):
            return np.tile(ray, (len(np.atleast_1d(jd)), 1))
        answer = search_planet_epochs(self.camera, [dict(detection_id='1', x_px=150., y_px=130.)],
            dates, {'saturn': vectors('saturn', dates)}, vectors, zenith_unit_vector=-ray)
        self.assertEqual(answer['matches'], [])
        self.assertEqual(answer['visibility']['rejected_below_horizon_count'], 1)

    def test_below_horizon_ephemeris_is_rejected_even_within_angular_gate(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(3.)
        ray = self.camera.to_sky([[199.2, 149.5]])[0]
        def vectors(name, jd):
            return np.tile(ray, (len(np.atleast_1d(jd)), 1))
        answer = search_planet_epochs(self.camera, [dict(detection_id='1', x_px=199.8, y_px=149.5)],
            dates, {'saturn': vectors('saturn', dates)}, vectors,
            gate_arcmin=20., zenith_unit_vector=[1, 0, 0])
        self.assertEqual(answer['matches'], [])

    def test_missing_zenith_cannot_produce_visible_planet_claims(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(3.)
        def vectors(name, jd):
            return self.camera.to_sky(np.tile([150., 130.], (len(np.atleast_1d(jd)), 1)))
        answer = search_planet_epochs(self.camera, [dict(detection_id='1', x_px=150., y_px=130.)],
            dates, {'saturn': vectors('saturn', dates)}, vectors)
        self.assertEqual(answer['status'], 'visibility_unresolved')
        self.assertEqual(answer['matches'], [])
        self.assertEqual(answer['planet_search_performance']['counts']['refined_visits'], 0)
        self.assertIn('total_planet_stage', answer['planet_search_performance']['seconds'])

    def test_future_planet_solution_is_excluded_at_recorded_cutoff(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(11.)
        def vectors(name, jd):
            t = np.atleast_1d(jd)-self.origin
            return self.camera.to_sky(np.c_[150+10*(t-8), np.full(len(t), 130.)])
        answer = search_planet_epochs(self.camera, [dict(detection_id='1', x_px=150., y_px=130.)],
            dates, {'saturn': vectors('saturn', dates)}, vectors,
            zenith_unit_vector=[0, 0, 1], latest_jd_tdb=self.origin+5.5)
        self.assertEqual(answer['matches'], [])
        self.assertLessEqual(answer['search_end_jd_tdb'], self.origin+5.5)

    def test_brief_visible_passage_is_not_hidden_by_visibility_penalty(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.array([0., 1.])
        def vectors(name, jd):
            t = np.atleast_1d(jd)-self.origin
            return self.camera.to_sky(np.c_[199.5001-(t-.1)**2, 149.5+(t-.1)])
        answer = search_planet_epochs(self.camera, [dict(detection_id='1', x_px=199.5001, y_px=149.5)],
            dates, {'saturn': vectors('saturn', dates)}, vectors,
            zenith_unit_vector=[1,0,0], latest_jd_tdb=self.origin+10.)
        self.assertEqual(answer['match_count'], 1)
        self.assertAlmostEqual(answer['best_candidate_jd_tdb']-self.origin, .1, places=4)
        self.assertGreaterEqual(answer['matches'][0]['predicted_altitude_deg'], 0.)

    def test_both_visible_sides_of_below_horizon_minimum_are_retained(self):
        from point_star_planets import search_planet_epochs
        dates = self.origin+np.arange(3.)
        def vectors(name, jd):
            t = np.atleast_1d(jd)-self.origin-1.
            return self.camera.to_sky(np.c_[199.4+t*t, 149.5+2*t])
        answer = search_planet_epochs(self.camera, [dict(detection_id='1', x_px=199.6, y_px=149.5)],
            dates, {'saturn': vectors('saturn', dates)}, vectors, gate_arcmin=20.,
            zenith_unit_vector=[1,0,0], latest_jd_tdb=self.origin+10.)
        candidate_dates = [c['jd_tdb']-self.origin for c in answer['candidates']]
        self.assertTrue(any(abs(t-(1-np.sqrt(.1))) < 1e-5 for t in candidate_dates))
        self.assertTrue(any(abs(t-(1+np.sqrt(.1))) < 1e-5 for t in candidate_dates))
        self.assertEqual(len(candidate_dates), 2)

    def test_off_detector_projection_failure_does_not_abort_other_bodies(self):
        from point_star_planets import _visible_projection
        camera = BarghiniCamera.initial((300,400),180.,np.eye(3))
        camera.p[6] = -.1; camera.p[7] = 1.
        self.assertTrue(camera.is_monotonic())
        bad = np.array([np.sin(3.),0.,np.cos(3.)]); good = np.array([0.,0.,1.])
        zenith = bad+good; zenith /= np.linalg.norm(zenith)
        points = _visible_projection(camera, np.array([bad,good]), zenith)
        self.assertFalse(np.isfinite(points[0]).any())
        self.assertTrue(np.isfinite(points[1]).all())

    def test_no_match_and_empty_sources_are_explicit(self):
        tracks = {'saturn': lambda t: np.c_[100+t, np.full(len(t), 100.)]}
        for positions in ([], [(250., 230.)]):
            result = self.search(tracks, positions)
            self.assertEqual(result['status'], 'no_planet_match')
            self.assertEqual(result['matches'], [])
            self.assertIn('planet_search_performance', result)


class IdentifiedPhotometryTests(unittest.TestCase):
    def test_planet_candidates_share_detection_count_rates_with_stars(self):
        import csv
        import tempfile
        from pathlib import Path
        from point_star_planets import _attach_identified_photometry
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with (output/'source_photometry.csv').open('w', newline='') as handle:
                fields = ['detection_id', 'x_px', 'y_px', 'star_id',
                          'identified_as_star', 'source_class', 'saturated',
                          'saturation_known', 'saturated_channels',
                          'exposure_seconds', 'G_flux', 'G_count_rate_adu_per_s',
                          'G_measurement_method', 'G_wing_fit_count_rate_adu_per_s']
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
                writer.writerows([
                    dict(detection_id='1', x_px=10, y_px=11, star_id='gaia-1',
                         identified_as_star=True, source_class='compact', saturated=False,
                         saturation_known=True, saturated_channels='', exposure_seconds=20,
                         G_flux=1000, G_count_rate_adu_per_s=50,
                         G_measurement_method='aperture', G_wing_fit_count_rate_adu_per_s='nan'),
                    dict(detection_id='2', x_px=20, y_px=21, star_id='',
                         identified_as_star=False, source_class='broad_blob', saturated=True,
                         saturation_known=True, saturated_channels='G', exposure_seconds=20,
                         G_flux=60000, G_count_rate_adu_per_s=3000,
                         G_measurement_method='saturated_aperture_lower_bound',
                         G_wing_fit_count_rate_adu_per_s=4200)])
            (output/'stellar_photometry.csv').write_text(
                'detection_id,star_id\n1,gaia-1\n')
            match = dict(detection_id=2, planet='Ceres')
            answer = dict(matches=[match], candidates=[dict(epoch_tdb='2000-01-01 TDB',
                          matches=[match])])
            fields = _attach_identified_photometry(output, answer)
            with (output/'identified_source_photometry.csv').open() as handle:
                rows = list(csv.DictReader(handle))
        self.assertIn('G_count_rate_adu_per_s', fields)
        self.assertEqual(answer['matches'][0]['G_count_rate_adu_per_s'], '3000')
        self.assertEqual(len(rows), 2)
        planet = next(row for row in rows if row['identity_type'] == 'minor_planet')
        self.assertEqual(planet['identity_name'], 'Ceres')
        self.assertEqual(planet['identity_status'], 'selected_planet_match')
        self.assertEqual(planet['G_measurement_method'],
                         'saturated_aperture_lower_bound')
        self.assertEqual(planet['G_wing_fit_count_rate_adu_per_s'], '4200')

    def test_metadata_time_match_is_an_identified_source(self):
        import csv
        import tempfile
        from pathlib import Path
        from point_star_planets import _attach_identified_photometry
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output/'source_photometry.csv').write_text(
                'detection_id,x_px,y_px,star_id,identified_as_star,source_class,'
                'saturated,saturation_known,saturated_channels,exposure_seconds,'
                'G_count_rate_adu_per_s\n'
                '1,10,11,,False,compact,True,True,G,20,5000\n')
            match = dict(detection_id=1, planet='Jupiter',
                         epoch_tdb='2000-01-02T00:00:00 TDB')
            answer = dict(matches=[], metadata_matches=[match], candidates=[
                dict(epoch_tdb='2000-01-01T00:00:00 TDB', matches=[
                    dict(detection_id=1, planet='Jupiter')])])
            _attach_identified_photometry(output, answer)
            with (output/'identified_source_photometry.csv').open() as handle:
                rows = list(csv.DictReader(handle))
        planet = next(row for row in rows if row['identity_name'] == 'Jupiter')
        self.assertEqual(planet['identity_status'], 'metadata_time_match')
        self.assertEqual(planet['epoch_tdb'], '2000-01-02T00:00:00 TDB')
        self.assertEqual(planet['G_count_rate_adu_per_s'], '5000')

if __name__ == '__main__':
    unittest.main()
