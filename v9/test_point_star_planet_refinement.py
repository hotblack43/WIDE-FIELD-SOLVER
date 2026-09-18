"""Batched planet refinement preserves independent exact minima."""
import os
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize_scalar


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def exact(self, name, dates):
        dates = np.asarray(dates, dtype=float)
        self.calls.append(dates.copy())
        return np.c_[dates, np.ones(len(dates)), np.zeros(len(dates))]

    def interpolated(self, name, dates):
        dates = np.asarray(dates, dtype=float)
        self.calls.append(('interpolated', dates.copy()))
        return np.c_[dates, np.ones(len(dates)), np.zeros(len(dates))]

    def counts(self):
        exact = [row for row in self.calls if not isinstance(row, tuple)]
        interpolated = [row[1] for row in self.calls if isinstance(row, tuple)]
        return {'exact_calls': len(exact), 'exact_dates': sum(map(len, exact)),
                'interpolated_calls': len(interpolated),
                'interpolated_dates': sum(map(len, interpolated))}


class BatchedMinimaTests(unittest.TestCase):
    def test_matches_independent_bounded_minima_and_batches_active_visits(self):
        from point_star_planet_refinement import Visit, batched_exact_minima
        targets = np.array([.1234567, 2.7, 9.1, 12.])
        visits = [Visit('mercury', i, start, stop, start, stop)
                  for i, (start, stop) in enumerate([(0., 1.), (2., 4.), (8., 10.), (12., 13.)])]
        provider = RecordingProvider()

        def objective(dates, vectors, active):
            return np.array([(date-targets[visit.source])**2
                             for date, visit in zip(dates, active)])

        dates, costs = batched_exact_minima(
            provider, 'mercury', visits, objective, xatol=1e-7)
        expected = np.array([minimize_scalar(
            lambda value, target=targets[i]: (value-target)**2,
            bounds=(visit.start, visit.stop), method='bounded',
            options={'xatol': 1e-7}).x for i, visit in enumerate(visits)])
        np.testing.assert_allclose(dates[:3], expected[:3], atol=1e-7, rtol=0)
        self.assertEqual(dates[3], 12.)  # Boundary minimum remains in its bracket.
        self.assertTrue(np.all(costs >= 0.))
        self.assertTrue(all(visit.start <= date <= visit.stop
                            for visit, date in zip(visits, dates)))
        self.assertLess(len(provider.calls), 80)
        self.assertTrue(any(len(call) == 2*len(visits) for call in provider.calls))

    def test_rejects_mismatched_names_and_invalid_brackets(self):
        from point_star_planet_refinement import Visit, batched_exact_minima
        provider = RecordingProvider()
        objective = lambda dates, vectors, visits: np.zeros(len(dates))
        cases = [
            [Visit('mars', 0, 0., 1., 0., 1.)],
            [Visit('mercury', 0, 1., 1., 0., 1.)],
            [Visit('mercury', 0, np.nan, 1., 0., 1.)],
        ]
        for visits in cases:
            with self.subTest(visits=visits), self.assertRaises(ValueError):
                batched_exact_minima(provider, 'mercury', visits, objective)


class WorkerSelectionTests(unittest.TestCase):
    def test_worker_count_is_bounded_and_serial_override_is_explicit(self):
        from point_star_planet_refinement import planet_worker_count
        with patch('os.cpu_count', return_value=8):
            self.assertEqual(planet_worker_count({}, 7), 4)
            self.assertEqual(planet_worker_count({}, 2), 2)
            self.assertEqual(planet_worker_count({}, 0), 1)
            self.assertEqual(planet_worker_count({'WFS_PLANET_WORKERS': '1'}, 7), 1)
            self.assertEqual(planet_worker_count({'WFS_PLANET_WORKERS': '20'}, 3), 3)
        for value in ('0', '-1', 'x', '1.5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                planet_worker_count({'WFS_PLANET_WORKERS': value}, 3)

    def test_two_processes_reproduce_serial_passages(self):
        from point_star_barghini import BarghiniCamera
        from point_star_planet_ephemeris import planet_vectors
        from point_star_planet_refinement import (
            RefinementContext, Visit, refine_all_planets)
        jd = 2451545.+np.arange(10.)
        names = ('mercury', 'mars')
        tracks = {name: planet_vectors(name, jd) for name in names}
        camera = BarghiniCamera.initial((300, 400), 180., np.eye(3))
        targets = [jd[4]+.2, jd[5]+.3]
        xy = np.array([camera.project(planet_vectors(name, [target]))[0]
                       for name, target in zip(names, targets)])
        groups = {
            name: [Visit(name, source, target-.7, target+.7,
                         target-.7, target+.7)]
            for source, (name, target) in enumerate(zip(names, targets))
        }
        context = RefinementContext(camera, xy, np.array([0., 0., 1.]))
        reference = (jd, tracks, planet_vectors)
        serial = refine_all_planets(groups, context, reference, workers=1)
        parallel = refine_all_planets(groups, context, reference, workers=2)
        self.assertEqual([result.name for result in serial],
                         [result.name for result in parallel])
        for left, right in zip(serial, parallel):
            self.assertEqual(left.passages, right.passages)
            self.assertEqual(left.counters, right.counters)


class CubicProposalTests(unittest.TestCase):
    def test_refinement_minimizes_great_circle_not_distorted_detector_distance(self):
        from point_star_planet_refinement import RefinementContext, Visit, refine_planet_visits

        class NonuniformCamera:
            shape = (300, 400)

            def project(self, vectors):
                vectors = np.asarray(vectors, dtype=float)
                u = vectors[:, 0]/vectors[:, 2]
                v = vectors[:, 1]/vectors[:, 2]
                return np.c_[u, v*(1.+4.*u)]

            def to_sky(self, points):
                points = np.asarray(points, dtype=float)
                rays = np.c_[points[:, 0], points[:, 1], np.ones(len(points))]
                return rays/np.linalg.norm(rays, axis=1)[:, None]

        class Provider(RecordingProvider):
            @staticmethod
            def _vectors(dates):
                u = np.asarray(dates, dtype=float)-.5
                rays = np.c_[u, np.full(len(u), .2), np.ones(len(u))]
                return rays/np.linalg.norm(rays, axis=1)[:, None]

            def exact(self, name, dates):
                dates = np.asarray(dates, dtype=float)
                self.calls.append(dates.copy())
                return self._vectors(dates)

            def interpolated(self, name, dates):
                dates = np.asarray(dates, dtype=float)
                self.calls.append(('interpolated', dates.copy()))
                return self._vectors(dates)

        result = refine_planet_visits(
            'uranus', [Visit('uranus', 0, 0., 1., 0., 1.)],
            RefinementContext(NonuniformCamera(), np.array([[0., 0.]])), Provider())

        self.assertAlmostEqual(result.passages[0].date, .5, places=5)

    def test_interpolated_optimizer_proposes_a_date_for_exact_evaluation(self):
        from point_star_barghini import BarghiniCamera
        from point_star_planet_refinement import RefinementContext, Visit, refine_planet_visits
        camera = BarghiniCamera.initial((300, 400), 180., np.eye(3))
        target = .37

        class Provider(RecordingProvider):
            def _vectors(self, dates):
                return camera.to_sky(np.c_[150+10*(dates-target),
                                           np.full(len(dates), 130.)])
            def exact(self, name, dates):
                dates = np.asarray(dates, dtype=float)
                self.calls.append(dates.copy())
                return self._vectors(dates)
            def interpolated(self, name, dates):
                dates = np.asarray(dates, dtype=float)
                self.calls.append(('interpolated', dates.copy()))
                return self._vectors(dates)

        provider = Provider()
        visit = Visit('mercury', 0, 0., 1., 0., 1.)
        result = refine_planet_visits(
            'mercury', [visit],
            RefinementContext(camera, np.array([[150., 130.]]), np.array([0., 0., 1.])),
            provider)
        interpolated_dates = np.concatenate(
            [row[1] for row in provider.calls if isinstance(row, tuple)])
        exact_dates = np.concatenate(
            [row for row in provider.calls if not isinstance(row, tuple)])
        self.assertLess(np.min(abs(interpolated_dates-target)), 1e-3)
        self.assertLess(np.min(abs(exact_dates-target)), 1e-3)
        self.assertGreater(result.counters['interpolated_dates'], 1)


if __name__ == '__main__':
    unittest.main()
