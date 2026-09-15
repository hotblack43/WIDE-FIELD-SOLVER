"""Blind time search recovers measured positions and preserves date aliases."""
import unittest
import numpy as np
from point_star_barghini import BarghiniCamera


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
                                    gate_px=1., positional_sigma_px=.2)

    def test_two_planets_recover_date_from_positions_without_epoch_hint(self):
        tracks = {'saturn': lambda t: np.c_[120+2*(t-4.3), np.full(len(t), 100.)],
                  'jupiter': lambda t: np.c_[np.full(len(t), 270.), 170+3*(t-4.3)]}
        result = self.search(tracks, [(120., 100.), (270., 170.)])
        self.assertEqual(result['match_count'], 2)
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin, 4.3, places=4)
        self.assertFalse(result['metadata_used'])
        self.assertEqual(len({r['detection_id'] for r in result['matches']}), 2)
        self.assertTrue(all(r['saturated'] for r in result['matches']))

    def test_fast_planet_between_daily_samples_is_not_missed(self):
        tracks = {'mercury': lambda t: np.c_[150+30*(t-.37), np.full(len(t), 130.)]}
        result = self.search(tracks, [(150., 130.)], stop=1.)
        self.assertEqual(result['match_count'], 1)
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin, .37, places=4)
        self.assertEqual(result['status'], 'planet_epoch_ambiguous')

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
        self.assertAlmostEqual(result['best_candidate_jd_tdb']-self.origin, 5., places=4)

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
        self.assertAlmostEqual(best[0]['jd_tdb']-self.origin, 5.68627451, places=5)

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
                   catalogue_star_id='wrong-star', catalogue_residual_px=3.)
        result = search_planet_epochs(self.camera, [row], dates, {'saturn': vectors('saturn', dates)},
                                     vectors, gate_px=1., positional_sigma_px=.5)
        self.assertEqual(result['match_count'], 1)
        self.assertEqual(result['matches'][0]['catalogue_star_id'], 'wrong-star')
        self.assertGreater(result['matches'][0]['improvement_over_star_chi2'], 9.)
        row['catalogue_residual_px'] = .1
        result = search_planet_epochs(self.camera, [row], dates, {'saturn': vectors('saturn', dates)},
                                     vectors, gate_px=1., positional_sigma_px=.5)
        self.assertEqual(result['match_count'], 0)

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
                result = {'camera': self.camera.serialise(), 'fit': {'rms_px': .5},
                          'source': f'/poison/warwick_{year}.jpg',
                          'observation': {'time_utc': year, 'latitude_deg': 999},
                          'stellar_epoch': {'epoch_jyear': 1800+index*300}}
                with patch('point_star_planet_ephemeris.load_ephemeris', return_value=(dates, grid, {})) as load, \
                     patch('point_star_planet_ephemeris.planet_vectors', side_effect=vectors), \
                     patch('point_star_planets._plot_candidates'), \
                     patch('point_star_report.observation_metadata', side_effect=AssertionError('Metadata read')):
                    answers.append(fit_blind_planet_epoch(result['source'], output, result))
                load.assert_called_once_with(1850., 2150.)
            self.assertEqual(answers[0], answers[1])

    def test_printed_epoch_list_and_plot_preserve_all_candidates(self):
        import contextlib, io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from point_star_planets import write_epoch_diagnostics
        answer = {'status': 'planet_epoch_ambiguous', 'candidates': [
            {'epoch_tdb': '2000-01-01T00:00:00 TDB', 'jd_tdb': self.origin, 'rms_px': .2,
             'conditional_time_sigma_minutes': 60., 'matches': [{'planet': 'Saturn', 'detection_id': 4}]},
            {'epoch_tdb': '2030-01-01T00:00:00 TDB', 'jd_tdb': self.origin+10957., 'rms_px': .4,
             'conditional_time_sigma_minutes': 120., 'matches': [{'planet': 'Mars', 'detection_id': 8}]}]}
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as printed:
            with patch('point_star_plotting.save_png') as save:
                write_epoch_diagnostics(Path(tmp), answer)
            self.assertIn('2000-01-01', printed.getvalue())
            self.assertIn('2030-01-01', printed.getvalue())
            self.assertIn('Saturn', printed.getvalue())
            self.assertIn('Mars', printed.getvalue())
            self.assertEqual(save.call_args.args[1].name, 'planet_epoch_candidates.png')
            self.assertTrue((Path(tmp)/'planet_epoch_candidates.txt').is_file())

    def test_no_match_and_empty_sources_are_explicit(self):
        tracks = {'saturn': lambda t: np.c_[100+t, np.full(len(t), 100.)]}
        for positions in ([], [(250., 230.)]):
            result = self.search(tracks, positions)
            self.assertEqual(result['status'], 'no_planet_match')
            self.assertEqual(result['matches'], [])

if __name__ == '__main__':
    unittest.main()
