"""Solar checks reject daylight aliases without borrowing an observer or date."""
import copy
import importlib.util
import unittest
from unittest.mock import patch

import numpy as np


def ray(altitude, azimuth=0.):
    h, a = np.deg2rad([altitude, azimuth])
    return np.array([np.cos(h)*np.cos(a), np.cos(h)*np.sin(a), np.sin(h)])


class SolarTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('point_star_planet_solar'),
                             'Solar consistency is not implemented')
        from point_star_planet_solar import SolarConstraint, classify_night, zenith_envelope
        self.constraint = SolarConstraint
        self.classify = classify_night
        self.envelope = zenith_envelope
        self.stars = np.array([ray(3., a) for a in range(0, 360, 45)])

    def test_accepted_stellar_field_activates_without_metadata(self):
        result = dict(status='point_star_fit_converged', fit=dict(count=100))
        before = self.classify(result, 100)
        result.update(source='daytime_19000101.jpg', observation=dict(time_utc='nonsense'),
                      latitude=90, stellar_epoch=dict(epoch_jyear=1950))
        self.assertEqual(before, self.classify(result, 100))
        self.assertEqual(before['status'], 'night_supported')
        self.assertEqual(self.classify(dict(status='failed'), 100)['status'], 'unresolved')
        self.assertEqual(self.classify(result, 0)['status'], 'unresolved')

    def test_global_envelope_contains_independently_feasible_zeniths(self):
        region = self.envelope(self.stars)
        self.assertEqual(region['status'], 'bounded')
        self.assertLess(region['radius_deg'], 6.)
        rng = np.random.default_rng(144)
        directions = rng.normal(size=(30000, 3))
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        feasible = directions[np.min(directions@self.stars.T, axis=1) >= 0]
        self.assertGreater(len(feasible), 5)
        angles = np.rad2deg(np.arccos(np.clip(feasible@region['centre_unit_vector'], -1, 1)))
        self.assertTrue(np.all(angles <= region['radius_deg']))

    def test_envelope_is_rotation_independent_and_never_narrows_to_provisional_zenith(self):
        from scipy.spatial.transform import Rotation
        rotation = Rotation.from_rotvec([.7, -.4, .2]).as_matrix()
        region = self.envelope(self.stars@rotation.T)
        self.assertEqual(region['status'], 'bounded')
        centre = np.array(region['centre_unit_vector'])
        angle = np.rad2deg(np.arccos(np.clip(centre@rotation[:, 2], -1, 1)))
        self.assertLess(angle, region['radius_deg'])
        # This wildly wrong adopted zenith affects only a diagnostic altitude.
        wrong = self.make_constraint(-8)
        wrong.zenith = ray(-80)
        self.assertEqual(wrong.assess(2451545.)['status'], 'solar_consistent')

    def test_sparse_or_failed_geometry_never_establishes_infeasibility(self):
        self.assertEqual(self.envelope([[0, 0, 1]])['status'], 'unresolved')
        with patch('point_star_planet_solar.linprog', side_effect=RuntimeError('failed')):
            self.assertEqual(self.envelope(self.stars)['status'], 'unresolved')

    def make_constraint(self, sun_altitude=60., night=True, stars=None):
        def sun(dates):
            return np.tile(ray(sun_altitude), (len(np.atleast_1d(dates)), 1))
        return self.constraint(
            dict(status='night_supported' if night else 'unresolved'),
            self.envelope(self.stars if stars is None else stars),
            zenith_unit_vector=[0., 0., 1.], sun_function=sun)

    def test_daylight_is_rejected_for_every_admissible_zenith(self):
        check = self.make_constraint()
        evidence = check.assess(2451545., [2451544.9, 2451545.1])
        self.assertEqual(evidence['status'], 'solar_inconsistent')
        self.assertGreater(evidence['interval_minimum_solar_altitude_deg'], 50.)
        self.assertEqual(self.make_constraint(night=False).assess(2451545.)['status'],
                         'solar_unresolved')

    def test_twilight_and_weak_zenith_are_not_rejected(self):
        self.assertEqual(self.make_constraint(-8).assess(2451545.)['status'], 'solar_consistent')
        self.assertEqual(self.make_constraint(0).assess(2451545.)['status'], 'solar_unresolved')
        weak = self.make_constraint(60, stars=[ray(85, a) for a in range(0, 360, 90)])
        self.assertNotEqual(weak.assess(2451545.)['status'], 'solar_inconsistent')

    def test_interval_crossing_sunset_is_not_discarded(self):
        check = self.make_constraint(12)
        record = check.assess(2451545., [2451535., 2451555.])
        self.assertEqual(record['status'], 'solar_unresolved')
        self.assertTrue(record['requires_date_refinement'])

    def test_missing_or_malformed_ephemeris_is_unresolved(self):
        check = self.make_constraint()
        check.sun_function = lambda dates: np.full((len(dates), 3), np.nan)
        self.assertEqual(check.assess(2451545.)['status'], 'solar_unresolved')

    def test_real_sun_uses_local_geocentric_convention(self):
        from point_star_planet_ephemeris import sun_vectors, planet_vectors
        sun = sun_vectors([2451545.])
        self.assertEqual(sun.shape, (1, 3))
        self.assertAlmostEqual(np.linalg.norm(sun[0]), 1.)
        self.assertAlmostEqual(float(np.rad2deg(np.arcsin(sun[0, 2]))), -23.03, delta=.1)
        with self.assertRaises(ValueError):
            planet_vectors('sun', [2451545.])

    def test_solar_motion_guard_covers_supported_reference_interval(self):
        from astropy.time import Time
        from point_star_planet_ephemeris import sun_vectors
        from point_star_planet_solar import SUN_SPEED_BOUND_DEG_PER_DAY
        dates = np.arange(*Time([1850., 2036.], format='jyear', scale='tdb').jd, 30.)
        before, after = sun_vectors(dates), sun_vectors(dates+.1)
        speed = np.rad2deg(np.arccos(np.clip(np.sum(before*after, axis=1), -1, 1)))/.1
        self.assertLess(float(speed.max()), SUN_SPEED_BOUND_DEG_PER_DAY)


class SolarRankingTests(unittest.TestCase):
    def test_solar_rejection_precedes_planet_count_and_preserves_audit(self):
        from point_star_planet_nondetections import apply_evidence
        candidates = [dict(jd_tdb=2451545.+i, epoch_tdb=str(i), match_count=n,
                           matches=[dict(planet='Mars')]*n, cost_px2=.1, rms_px=.1,
                           solar_evidence=dict(status=status))
                      for i, n, status in [(0, 3, 'solar_inconsistent'),
                                            (1, 2, 'solar_consistent')]]
        answer = dict(status='planet_epoch_ambiguous', candidates=candidates,
                      visibility=dict(zenith_status='conditional_zenith'))
        original = copy.deepcopy(answer)
        result = apply_evidence(answer, [[], []])
        self.assertEqual(answer, original)
        self.assertEqual(result['best_candidate_jd_tdb'], 2451546.)
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(result['match_count'], 2)

    def test_all_solar_rejected_clears_epoch_and_matches(self):
        from point_star_planet_nondetections import apply_evidence
        answer = dict(status='planet_epoch_ambiguous', candidates=[dict(
            jd_tdb=2451545., epoch_tdb='date', match_count=2, matches=[],
            cost_px2=.1, rms_px=.1, solar_evidence=dict(status='solar_inconsistent'))])
        result = apply_evidence(answer, [[]])
        self.assertEqual(result['status'], 'planet_epoch_inconsistent')
        self.assertEqual(result['matches'], [])
        self.assertIsNone(result['best_candidate_jd_tdb'])

    def test_daylight_epoch_needing_refit_cannot_outrank_twilight_alternative(self):
        from point_star_planet_nondetections import apply_evidence
        candidates = [dict(jd_tdb=2451545.+i, epoch_tdb=str(i), match_count=2,
                           matches=[dict(planet='Mars'), dict(planet='Venus')],
                           cost_px2=.1+i, rms_px=.1+i,
                           solar_evidence=dict(status='solar_unresolved', requires_date_refinement=(i==0)))
                      for i in range(2)]
        result = apply_evidence(dict(status='planet_epoch_ambiguous', candidates=candidates), [[], []])
        self.assertEqual(result['best_candidate_jd_tdb'], 2451546.)

    def test_report_explains_solar_rejection_without_claiming_a_date(self):
        from point_star_report import report_sections
        from point_star_barghini import BarghiniCamera
        result = dict(fit=dict(count=8, rms_px=.5, median_px=.4, p90_px=.8),
                      camera=BarghiniCamera.initial((400, 400), 180., np.eye(3)).serialise())
        science = dict(planets=dict(status='planet_epoch_inconsistent',
            reason='All candidate dates contradicted',
            night_classification=dict(status='night_supported'),
            solar_evidence=dict(rejected_candidates=4, unresolved_candidates=0)))
        text = report_sections(result, science)['planets']
        self.assertIn('Solar geometry excludes 4', text)
        self.assertIn('treated as nighttime', text)
        self.assertNotIn('planet-derived epoch is', text)


class SolarPipelineTests(unittest.TestCase):
    def test_search_adds_twilight_alternative_to_daylight_positional_minimum(self):
        from point_star_barghini import BarghiniCamera
        from point_star_planets import search_planet_epochs
        from point_star_planet_solar import SolarConstraint, zenith_envelope
        camera = BarghiniCamera.initial((400, 400), 180., np.eye(3))
        origin = 2451545.
        dates = origin+np.arange(31.)
        def planets(name, dates):
            t = np.atleast_1d(dates)-origin-4.
            return camera.to_sky(np.c_[150+.05*t, np.full(len(t), 150.)] if name == 'venus'
                                 else np.c_[np.full(len(t), 250.), 250+.05*t])
        solar = SolarConstraint(dict(status='night_supported'),
            zenith_envelope([ray(3, a) for a in range(0, 360, 45)]),
            zenith_unit_vector=[0, 0, 1],
            sun_function=lambda dates: np.array([ray(12-(date-origin-4)) for date in dates]))
        sources = [dict(detection_id=i+1, x_px=x, y_px=y)
                   for i, (x, y) in enumerate([[150, 150], [250, 250]])]
        answer = search_planet_epochs(camera, sources, dates,
            {name: planets(name, dates) for name in ('venus', 'saturn')}, planets,
            gate_px=2., zenith_unit_vector=[0, 0, 1], latest_jd_tdb=origin+40,
            solar_constraint=solar)
        self.assertTrue(any(abs(c['jd_tdb']-origin-4)<1e-4 for c in answer['candidates']))
        alternatives = [c for c in answer['candidates'] if c.get('solar_boundary_refinement')]
        self.assertTrue(alternatives)
        self.assertTrue(any(c['jd_tdb']-origin > 10 for c in alternatives))
        self.assertTrue(all(m['separation_px'] <= 2 for c in alternatives for m in c['matches']))

    def test_real_pipeline_rejects_daylight_and_exports_evidence_without_refit(self):
        import csv
        import json
        import tempfile
        from pathlib import Path
        from PIL import Image
        from point_star_barghini import BarghiniCamera
        from point_star_planets import fit_blind_planet_epoch
        camera = BarghiniCamera.initial((400, 400), 180., np.eye(3))
        origin = 2451545.
        dates = origin+np.arange(4.)
        def planets(name, dates):
            t = np.atleast_1d(dates)-origin-1.5
            return camera.to_sky(np.c_[150+5*t, np.full(len(t), 150.)] if name == 'venus'
                                 else np.c_[np.full(len(t), 250.), 250+5*t])
        grid = {name: planets(name, dates) for name in ('venus', 'saturn')}
        sources = [dict(detection_id=i+1, x_px=x, y_px=y, saturated=False)
                   for i, (x, y) in enumerate([[150, 150], [250, 250]])]
        stellar_points = camera.project(np.array([ray(3., a) for a in range(0, 360, 45)]))
        stars = []
        for i, (x, y) in enumerate(stellar_points, 3):
            sources.append(dict(detection_id=i, x_px=x, y_px=y, saturated=False))
            stars.append(dict(detection_id=i, star_id=str(i), residual_px=0.,
                              x_px=x, y_px=y, magnitude=5.))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output/'dots').mkdir()
            for name, rows in [('dots/star_candidates.csv', sources), ('star_coordinates.csv', stars)]:
                with (output/name).open('w') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0])
                    writer.writeheader(); writer.writerows(rows)
            (output/'photometric_zenith.json').write_text(json.dumps(dict(
                status='not_identifiable', zenith_unit_vector=[0, 0, 1],
                fitted_detection_ids=[str(row['detection_id']) for row in stars])))
            source = output/'image.png'
            Image.new('L', (400, 400), 100).save(source)
            result = dict(status='point_star_fit_converged', fit=dict(count=8, rms_px=.5),
                          camera=camera.serialise(), causal_epoch_ceiling=dict(jd_tdb=origin+10))
            original = copy.deepcopy(result)
            with patch('point_star_planet_ephemeris.load_ephemeris', return_value=(dates, grid, {})), \
                 patch('point_star_planet_ephemeris.planet_vectors', side_effect=planets), \
                 patch('point_star_planet_ephemeris.sun_vectors',
                       side_effect=lambda dates: np.tile(ray(60), (len(dates), 1))):
                answer = fit_blind_planet_epoch(source, output, result)
            self.assertEqual(result, original)
            self.assertEqual(answer['status'], 'planet_epoch_inconsistent')
            self.assertEqual(answer['matches'], [])
            self.assertTrue(answer['candidates'])
            self.assertTrue(all(c['solar_evidence']['status']=='solar_inconsistent'
                                for c in answer['candidates']))
            self.assertTrue(all(c['positional_interval_jd_tdb'][0] <= c['jd_tdb'] <=
                                c['positional_interval_jd_tdb'][1] for c in answer['candidates']))
            night = json.loads((output/'night_classification.json').read_text())
            self.assertEqual(night['status'], 'night_supported')
            audit = json.loads((output/'planet_solar_evidence.json').read_text())
            self.assertEqual(len(audit['candidates']), len(answer['candidates']))
            with (output/'planet_candidates.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(all(r['solar_status']=='solar_inconsistent' for r in rows))


if __name__ == '__main__':
    unittest.main()
