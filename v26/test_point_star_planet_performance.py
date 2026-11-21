"""Planet search telemetry is explicit and scientifically inert."""
import unittest


class FakeClock:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class PlanetSearchPerformanceTests(unittest.TestCase):
    def test_named_stages_worker_counts_and_cache_serialize(self):
        from point_star_planet_performance import PlanetSearchPerformance
        performance = PlanetSearchPerformance(
            requested_workers=4,
            cache={'source': 'bundled', 'bytes': 123, 'digest': 'abc'},
            clock=FakeClock([10., 10.5, 20., 20.75]))
        performance.start('coarse_scan')
        performance.finish('coarse_scan')
        performance.start('exact_refinement')
        performance.finish('exact_refinement')
        performance.used_workers = 2
        performance.providers.update(exact_calls=7, exact_dates=27,
                                     interpolated_calls=3, interpolated_dates=9)
        performance.counts.update(refined_visits=3, joint_trials=5,
                                  source_candidates=2, retained_candidates=1)
        saved = performance.serialise(total_planet_stage=1.25)
        self.assertEqual(saved['schema_version'], 1)
        self.assertEqual(saved['workers']['requested'], 4)
        self.assertEqual(saved['workers']['used'], 2)
        self.assertEqual(saved['cache']['source'], 'bundled')
        self.assertEqual(saved['providers']['exact_dates'], 27)
        self.assertEqual(saved['counts']['refined_visits'], 3)
        self.assertEqual(saved['seconds']['coarse_scan'], .5)
        self.assertEqual(saved['seconds']['exact_refinement'], .75)
        self.assertEqual(saved['seconds']['total_planet_stage'], 1.25)

    def test_finish_requires_a_started_stage(self):
        from point_star_planet_performance import PlanetSearchPerformance
        performance = PlanetSearchPerformance(clock=FakeClock([1.]))
        with self.assertRaises(ValueError):
            performance.finish('missing')


if __name__ == '__main__':
    unittest.main()
