"""Reproducible v5/v6 timing and scientific comparison helpers."""
import copy
import unittest


class BenchmarkTests(unittest.TestCase):
    def candidate(self):
        return {
            'status': 'planet_epoch_not_identifiable',
            'refined_visit_count': 3,
            'joint_trial_count': 1,
            'candidates': [{
                'jd_tdb': 2451545.123,
                'rms_px': .25,
                'matches': [{'planet': 'Mars', 'detection_id': 7,
                             'separation_px': .25, 'predicted_x_px': 12.,
                             'predicted_y_px': 13., 'predicted_altitude_deg': 20.}],
            }],
            'source_candidates': [{'planet': 'Mars', 'detection_id': 7,
                                   'jd_tdb': 2451545.123, 'separation_px': .25}],
            'visibility_sources': [{'detection_id': 7, 'visible': True,
                                    'altitude_deg': 20.}],
            'negative_evidence': {'contradicted_candidates': 0},
            'planet_search_performance': {'seconds': {'total_planet_stage': 1.}},
        }

    def test_timing_summary_uses_medians_and_v5_over_v6_ratio(self):
        from scripts.benchmark_planet_search import timing_summary
        summary = timing_summary([9., 11., 10.], [4., 5., 6.])
        self.assertEqual(summary['v5_median_seconds'], 10.)
        self.assertEqual(summary['v6_median_seconds'], 5.)
        self.assertEqual(summary['speedup_ratio'], 2.)

    def test_scientific_comparison_allows_only_tiny_exact_numeric_differences(self):
        from scripts.benchmark_planet_search import compare_science
        v5 = self.candidate()
        v6 = copy.deepcopy(v5)
        v6['planet_search_performance']['seconds']['total_planet_stage'] = 99.
        v6['candidates'][0]['jd_tdb'] += .2/86400
        v6['candidates'][0]['rms_px'] += 1e-8
        comparison = compare_science(v5, v6)
        self.assertTrue(comparison['equivalent'])
        self.assertLessEqual(comparison['max_epoch_difference_seconds'], .25)

        for mutation in ('status', 'identity', 'date', 'residual', 'prediction',
                         'altitude', 'source_candidate', 'negative_evidence'):
            changed = copy.deepcopy(v6)
            if mutation == 'status':
                changed['status'] = 'conditional_planet_epoch'
            elif mutation == 'identity':
                changed['candidates'][0]['matches'][0]['planet'] = 'Venus'
            elif mutation == 'date':
                changed['candidates'][0]['jd_tdb'] += 1./86400
            elif mutation == 'residual':
                changed['candidates'][0]['rms_px'] += 1e-4
            elif mutation == 'prediction':
                changed['candidates'][0]['matches'][0]['predicted_x_px'] += .01
            elif mutation == 'altitude':
                changed['visibility_sources'][0]['altitude_deg'] += .01
            elif mutation == 'source_candidate':
                changed['source_candidates'][0]['detection_id'] = 8
            else:
                changed['negative_evidence']['contradicted_candidates'] = 1
            with self.subTest(mutation=mutation):
                self.assertFalse(compare_science(v5, changed)['equivalent'])


if __name__ == '__main__':
    unittest.main()
