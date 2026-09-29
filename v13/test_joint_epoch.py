"""Moving bodies must affect the common camera/epoch, not only a plot."""
import copy
import unittest
import tempfile
import csv
from pathlib import Path
from unittest.mock import patch
import numpy as np
from astropy.time import Time
from point_star_barghini import BarghiniCamera
from point_star_epoch import Catalogue
from test_point_star_epoch import moving_field


class GlobalContextTests(unittest.TestCase):
    def test_fits_creation_clock_conflict_is_audit_only(self):
        from astropy.io import fits
        from point_star_metadata import fits_clock_audit
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'clock.fits'
            hdu = fits.PrimaryHDU(np.zeros((2, 2)))
            hdu.header['DATE-OBS'] = '2026-09-19T04:59:55.670400'
            hdu.header['DATE'] = '2026-09-19T12:00:17.769900'
            hdu.header['EXPOSURE'] = 20.
            hdu.writeto(path)
            before = path.read_bytes()
            audit = fits_clock_audit(path)
            self.assertAlmostEqual(audit['creation_minus_observation_seconds'], 25222.0995, places=3)
            self.assertEqual(audit['possible_clock_offset_hours'], 7)
            self.assertFalse(audit['timestamp_corrected'])
            self.assertEqual(path.read_bytes(), before)

    def test_wrong_timestamp_does_not_narrow_global_search(self):
        from point_star_metadata import planet_search_context
        answer = planet_search_context('missing-image', explicit_time='1950-01-01')
        self.assertEqual(answer['epoch_limits'], (1850., 2036.))
        self.assertNotEqual(answer['planet_search_mode'], 'metadata_conditioned')


class JointFitTests(unittest.TestCase):
    def test_adoption_handles_empty_photometry_and_declines_changed_zenith_authority(self):
        from astropy.io import fits
        from point_star_joint_epoch import attempt_adoption, profile_joint_candidate
        initial, xy, cat, jd, ephemeris, matches = self.fixture()
        fitted = profile_joint_candidate(initial, xy, cat, matches, ephemeris,
                                         (jd-1, jd+1), star_sigma_arcmin=.1, planet_sigma_arcmin=.1)
        fitted['fitted_pairs'] = [[i, i] for i in range(len(xy))]
        camera = BarghiniCamera.from_serialised(fitted['camera'])
        vector = camera.to_sky([[499.5, 399.5]])[0]
        for prior_source in ('image_centre_assumption', 'photometric_extinction'):
            with self.subTest(prior_source=prior_source), tempfile.TemporaryDirectory() as d:
                output = Path(d); (output/'dots').mkdir()
                (output/'display_names.json').write_text('{}\n')
                image_path = output/'empty.fits'
                fits.PrimaryHDU(np.full(camera.shape, 100., dtype=np.float32)).writeto(image_path)
                detections = [dict(detection_id=str(i), x_px=str(p[0]), y_px=str(p[1]),
                                   source_class='compact', saturated='False') for i, p in enumerate(xy)]
                with (output/'dots/star_candidates.csv').open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(detections[0]))
                    writer.writeheader(); writer.writerows(detections)
                trial = copy.deepcopy(fitted)
                trial['zenith_constraint'] = dict(
                    status='assumed_zenith' if prior_source == 'image_centre_assumption' else 'conditional_zenith',
                    zenith_source=prior_source, zenith_unit_vector=vector.tolist())
                result = dict(source=str(image_path), status='point_star_fit_converged',
                              camera=initial.serialise(), fit={'count': len(xy)})
                science = dict(planets={'searched_planets': [], 'visibility': {}})
                with patch('point_star_planet_ephemeris.sun_vectors',
                           side_effect=lambda dates: np.tile(-vector, (len(dates), 1))):
                    accepted, reason, failed = attempt_adoption(
                        image_path, output, result, science, cat, detections, trial, copy.deepcopy(result))
                self.assertFalse(failed, reason)
                self.assertEqual(accepted, prior_source == 'image_centre_assumption', reason)
                if accepted:
                    self.assertEqual(science['photometry']['photometric_zenith']['fitted_count'], 0)
                    self.assertEqual(result['coordinate_epoch_source'], 'joint_stellar_planet_profile')
                    self.assertTrue((output/'star_coordinates.csv').is_file())
                else:
                    self.assertIn('zenith authority changed', reason.lower())
                    self.assertEqual(result['camera'], initial.serialise())
                    self.assertFalse((output/'star_coordinates.csv').exists())

    def test_centre_zenith_visibility_tracks_trial_camera_not_initial_sky_vector(self):
        from point_star_zenith import zenith_constraints
        from point_star_planet_solar import SolarConstraint
        camera = BarghiniCamera.initial((800, 1000), 500., np.eye(3))
        camera.p[3] += .03
        saved = dict(status='assumed_zenith', zenith_source='image_centre_assumption',
                     zenith_unit_vector=[1., 0., 0.])
        vector, envelope, accepted = zenith_constraints(camera, saved, np.empty((0, 3)))
        self.assertTrue(accepted)
        np.testing.assert_allclose(camera.project([vector])[0], [499.5, 399.5], atol=1e-7)
        solar = SolarConstraint({'status': 'night_supported'}, envelope,
            zenith_unit_vector=vector, sun_function=lambda dates: np.tile(-np.asarray(vector), (len(dates), 1)))
        self.assertEqual(solar.assess(2450000.)['status'], 'solar_consistent')
        self.assertEqual(saved['zenith_unit_vector'], [1., 0., 0.])
        rejected = dict(saved, status='not_identifiable', zenith_source='unconstrained_photometric_trial')
        self.assertFalse(zenith_constraints(camera, rejected, np.empty((0, 3)))[2])

    def test_regeneration_failure_returns_stellar_fallback(self):
        from point_star_joint_epoch import attempt_adoption
        result = {'camera': {'unchanged': True}}
        science = {'planets': {'matches': []}}
        with patch('point_star_joint_epoch._adopt_joint_solution', side_effect=OSError('disk full')):
            accepted, reason, failed = attempt_adoption('image', Path('.'), result, science,
                                                        None, [], {}, copy.deepcopy(result))
        self.assertFalse(accepted)
        self.assertTrue(failed)
        self.assertIn('disk full', reason)
        self.assertEqual(result['camera'], {'unchanged': True})

    def test_zero_and_one_planet_preserve_saved_stellar_coordinates(self):
        from point_star_joint_epoch import refine_joint_epoch
        initial, xy, cat, jd, _, matches = self.fixture()
        for count in (0, 1):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as d:
                output = Path(d); (output/'dots').mkdir()
                star_rows = [dict(detection_id=str(i), star_id=cat.rows[i]['star_id'],
                                 x_px=str(p[0]), y_px=str(p[1])) for i, p in enumerate(xy)]
                det_rows = [dict(r, source_class='compact', saturated='False') for r in star_rows]
                for path, rows in ((output/'cat.csv', cat.rows), (output/'star_coordinates.csv', star_rows),
                                   (output/'dots/star_candidates.csv', det_rows)):
                    with path.open('w') as handle:
                        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
                before = (output/'star_coordinates.csv').read_bytes()
                result = dict(camera=initial.serialise(), epoch_mode='fit', fit={'rms_arcmin': 3.},
                              causal_epoch_ceiling={'jd_tdb': jd+1})
                candidates = [] if not count else [dict(matches=matches[:1], jd_tdb=jd, epoch_tdb='2010')]
                science = dict(planets={'candidates': candidates}, photometry={})
                answer = refine_joint_epoch('unused', output, result, science, output/'cat.csv')
                self.assertEqual(answer['status'], 'joint_epoch_not_attempted_insufficient_planets')
                self.assertFalse(answer['adopted'])
                self.assertEqual((output/'star_coordinates.csv').read_bytes(), before)
                self.assertEqual(result['camera'], initial.serialise())

    def test_causal_truncation_reports_a_finite_allowed_interval_not_infinite_uncertainty(self):
        from point_star_joint_epoch import interval_boundary_record
        answer = interval_boundary_record([100., None], [90., 110.], [0., 110.])
        self.assertEqual(answer['allowed_interval_95_jd_tdb'], [100., 110.])
        self.assertEqual(answer['upper_interval_boundary'], 'causal_present_time')
        self.assertFalse(answer['data_bounded_both_sides'])

    def test_final_planet_identity_uses_joint_epoch_not_metadata(self):
        from point_star_joint_epoch import planet_product_view
        from point_star_planets import _attach_identified_photometry
        match = dict(planet='Mars', detection_id=1, measured_x_px=20., measured_y_px=30.)
        old = dict(matches=[match], candidates=[dict(epoch_tdb='1900', matches=[match])],
                   metadata_matches=[dict(match, epoch_tdb='2000')])
        fitted = dict(matches=[match], epoch_tdb='2020', jd_tdb=2458849., planet_count=1,
                      planet_rms_arcmin=1., brightness={'cost': 0.})
        joint = dict(adopted=True, best_index=0, candidates=[fitted], status='joint_epoch_fitted')
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)
            (output/'source_photometry.csv').write_text('detection_id,x_px,y_px,G_flux\n1,20,30,100\n')
            final = planet_product_view(old, joint)
            _attach_identified_photometry(output, final)
            with (output/'identified_source_photometry.csv').open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['epoch_tdb'], '2020')
            self.assertEqual(rows[0]['identity_status'], 'selected_planet_match')
            self.assertEqual(final['metadata_validation_matches'][0]['epoch_tdb'], '2000')

    def test_adopted_joint_predictions_survive_view_but_stale_predictions_do_not(self):
        from point_star_joint_epoch import planet_product_view
        predictions = [dict(planet='Ceres', predicted_x_px=10., predicted_y_px=20.)]
        best = dict(matches=[], epoch_tdb='2020', jd_tdb=2458849.)
        joint = dict(adopted=True, best_index=0, candidates=[best], status='joint_epoch_fitted')
        planets = dict(predicted_planets=predictions, prediction_epoch_jd_tdb=2458849.)
        self.assertEqual(planet_product_view(planets, joint)['predicted_planets'], predictions)
        self.assertEqual(planet_product_view(dict(planets, prediction_epoch_jd_tdb=2400000.), joint)['predicted_planets'], [])

    def test_control_modes_with_no_planets_preserve_initial_solution(self):
        from point_star_joint_epoch import refine_joint_epoch
        import json
        for mode in ('fixed', 'catalog'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                result = dict(epoch_mode=mode, camera={'unchanged': True})
                science = dict(planets={'candidates': []})
                record = refine_joint_epoch('unused', Path(d), result, science, 'unused-catalogue')
                self.assertEqual(record['status'], 'joint_epoch_not_attempted_control')
                self.assertFalse(record['adopted'])
                self.assertEqual(result['camera'], {'unchanged': True})
                self.assertEqual(json.loads((Path(d)/'result.json').read_text())['camera'], result['camera'])

    def test_selection_does_not_let_brightness_resolve_positional_aliases(self):
        from point_star_joint_epoch import select_joint_candidate
        base = dict(planet_count=2, cost=10., bounded=True, eligible=True,
                    association_converged=True, physical_checks_passed=True,
                    brightness={'cost': 0.}, jd_tdb=2450000.)
        other = dict(base, jd_tdb=2451000., brightness={'cost': 100.})
        answer = select_joint_candidate([base, other])
        self.assertEqual(answer['status'], 'joint_epoch_ambiguous')
        self.assertIsNone(answer['adopted_index'])

    def test_selection_requires_complete_profiles_and_physical_checks(self):
        from point_star_joint_epoch import select_joint_candidate
        base = dict(planet_count=2, cost=10., bounded=True, eligible=True,
                    association_converged=True, physical_checks_passed=True,
                    brightness={'cost': 0.}, jd_tdb=2450000.)
        self.assertEqual(select_joint_candidate([base])['status'], 'joint_epoch_fitted')
        self.assertEqual(select_joint_candidate([base], failures=1)['status'], 'joint_epoch_failed')
        self.assertEqual(select_joint_candidate([dict(base, physical_checks_passed=False)])['status'],
                         'joint_epoch_ambiguous')
        self.assertEqual(select_joint_candidate([])['status'],
                         'joint_epoch_not_attempted_insufficient_planets')

    def test_different_stellar_membership_cannot_make_an_alias_disappear(self):
        from point_star_joint_epoch import select_joint_candidate
        first = dict(planet_count=2, cost=10., bounded=True, eligible=True,
                     association_converged=True, physical_checks_passed=True,
                     brightness={'cost': 0.}, jd_tdb=2450000., fitted_pairs=[[1, 1], [2, 2]])
        dropped_star = dict(first, cost=100., jd_tdb=2451000., fitted_pairs=[[1, 1]])
        self.assertEqual(select_joint_candidate([first, dropped_star])['status'], 'joint_epoch_ambiguous')

    def test_failed_promotion_rolls_back_authoritative_products(self):
        from point_star_joint_epoch import publish_candidate_files
        import shutil
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/'output'; output.mkdir()
            staging = Path(d)/'staging'; staging.mkdir()
            (output/'a.csv').write_text('initial-a')
            (output/'b.csv').write_text('initial-b')
            (staging/'a.csv').write_text('joint-a')
            (staging/'b.csv').write_text('joint-b')
            real_copy = shutil.copy2
            def fail(src, dst, *args, **kwargs):
                if Path(src) == staging/'b.csv' and Path(dst) == output/'b.csv':
                    raise OSError('simulated full device')
                return real_copy(src, dst, *args, **kwargs)
            with patch('point_star_joint_epoch.shutil.copy2', side_effect=fail):
                with self.assertRaises(OSError):
                    publish_candidate_files(staging, output)
            self.assertEqual((output/'a.csv').read_text(), 'initial-a')
            self.assertEqual((output/'b.csv').read_text(), 'initial-b')

    def fixture(self):
        initial, xy, rows, sky = moving_field(motion_scale=500, year=2010., noise=.0001)
        true = BarghiniCamera.initial((800, 1000), 500., np.eye(3))
        true.p[6:] = [.012, 1.5]
        jd = float(Time(2010., format='jyear', scale='tdb').jd)
        positions = {'mars': [300., 330.], 'jupiter': [650., 500.]}
        speeds = {'mars': [15., 4.], 'jupiter': [-8., 3.]}
        def ephemeris(name, dates):
            return true.to_sky(np.asarray(positions[name])[None, :] +
                               (np.atleast_1d(dates)-jd)[:, None]*speeds[name])
        matches = [dict(planet=name.title(), detection_id=100+i,
                        measured_x_px=p[0], measured_y_px=p[1])
                   for i, (name, p) in enumerate(positions.items())]
        return initial, xy, Catalogue.from_rows(rows), jd, ephemeris, matches

    def test_two_planets_recover_epoch_and_camera(self):
        from point_star_joint_epoch import profile_joint_candidate
        initial, xy, cat, jd, ephemeris, matches = self.fixture()
        before = initial.p.copy()
        fitted = profile_joint_candidate(initial, xy, cat, matches, ephemeris,
                    (jd-1, jd+1), star_sigma_arcmin=.1, planet_sigma_arcmin=.1)
        self.assertAlmostEqual(fitted['jd_tdb'], jd, delta=.0001)
        self.assertTrue(fitted['bounded'])
        self.assertLess(fitted['planet_rms_arcmin'], .01)
        self.assertLess(fitted['stellar_rms_arcmin'], .01)
        self.assertGreater(np.linalg.norm(np.array(fitted['camera']['normalised_parameters'])-before), .0001)
        np.testing.assert_array_equal(initial.p, before)
        self.assertGreater(len(fitted['profile']), 5)

    def test_single_or_duplicate_sources_cannot_qualify(self):
        from point_star_joint_epoch import qualifies
        _, _, _, _, _, matches = self.fixture()
        self.assertFalse(qualifies([]))
        self.assertFalse(qualifies(matches[:1]))
        duplicate = copy.deepcopy(matches)
        duplicate[1]['detection_id'] = duplicate[0]['detection_id']
        self.assertFalse(qualifies(duplicate))
        duplicate = copy.deepcopy(matches)
        duplicate[1]['planet'] = duplicate[0]['planet'].lower()
        self.assertFalse(qualifies(duplicate))
        self.assertTrue(qualifies(matches))

    def test_boundary_minimum_is_not_bounded(self):
        from point_star_joint_epoch import profile_joint_candidate
        initial, xy, cat, jd, ephemeris, matches = self.fixture()
        fitted = profile_joint_candidate(initial, xy, cat, matches, ephemeris,
                    (jd-1, jd-.1), star_sigma_arcmin=.1, planet_sigma_arcmin=.1)
        self.assertFalse(fitted['bounded'])

    def test_saved_coordinates_follow_joint_camera_and_epoch(self):
        from point_star_joint_epoch import write_joint_coordinates, profile_joint_candidate
        initial, xy, cat, jd, ephemeris, matches = self.fixture()
        fitted = profile_joint_candidate(initial, xy, cat, matches, ephemeris,
                    (jd-1, jd+1), star_sigma_arcmin=.1, planet_sigma_arcmin=.1)
        fitted['fitted_pairs'] = [[i, i] for i in range(len(xy))]
        detections = [dict(detection_id=str(i), x_px=str(p[0]), y_px=str(p[1]),
                           source_class='compact', saturated='False') for i, p in enumerate(xy)]
        with tempfile.TemporaryDirectory() as d:
            result = dict(camera=initial.serialise(), detection_count=len(xy))
            write_joint_coordinates(Path(d), result, cat, detections, fitted)
            with (Path(d)/'star_coordinates.csv').open() as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), len(xy))
            self.assertAlmostEqual(float(saved[0]['coordinate_epoch_jyear']), 2010., places=6)
            camera = BarghiniCamera.from_serialised(result['camera'])
            np.testing.assert_allclose([[float(r['predicted_x_px']), float(r['predicted_y_px'])] for r in saved],
                                       camera.project(cat.at_year(2010.)), atol=.0001)
            self.assertLess(result['fit']['rms_arcmin'], .01)


class BrightnessTests(unittest.TestCase):
    def test_relative_brightness_downranks_wrong_identity_but_not_centroids(self):
        from point_star_joint_epoch import relative_brightness_evidence
        rows = [dict(planet='Jupiter', detection_id=1), dict(planet='Mars', detection_id=2)]
        photo = {'1': dict(G_count_rate_adu_per_s=10000, G_saturated='False', saturation_known='True'),
                 '2': dict(G_count_rate_adu_per_s=100, G_saturated='False', saturation_known='True')}
        original = copy.deepcopy(rows)
        good = relative_brightness_evidence(rows, photo, {'jupiter': -2., 'mars': 3.})
        bad = relative_brightness_evidence(rows, photo, {'jupiter': 3., 'mars': -2.})
        self.assertAlmostEqual(good['cost'], 0.)
        self.assertGreater(bad['cost'], good['cost']+1.)
        self.assertEqual(rows, original)

    def test_saturated_or_missing_photometry_is_neutral(self):
        from point_star_joint_epoch import relative_brightness_evidence
        rows = [dict(planet='Jupiter', detection_id=1), dict(planet='Mars', detection_id=2)]
        photo = {'1': dict(G_count_rate_adu_per_s=10000, G_saturated='True', saturation_known='True')}
        answer = relative_brightness_evidence(rows, photo, {'jupiter': -2., 'mars': 3.})
        self.assertEqual(answer['cost'], 0.)
        self.assertEqual(answer['status'], 'neutral')


if __name__ == '__main__':
    unittest.main()
