"""Blind bootstrap must recover when the broad distortion search times out."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import tetra3

from point_star_barghini import bootstrap


class BootstrapFallbackTests(unittest.TestCase):
    def test_measured_pixels_solve_after_distortion_search_exhaustion(self):
        fixture = json.loads((Path(__file__).parent / 'tests/fixtures/bootstrap_pixels.json').read_text())
        xy = np.asarray(fixture['xy'])
        original = xy.copy()
        real_solve = tetra3.Tetra3.solve_from_centroids

        def bounded_solve(solver, centroids, shape, **kwargs):
            # The actual 15 range-search failures are recorded in the diagnosis.
            # Simulate only their timeout here, avoiding >75 s of repeated lookup;
            # the fallback still performs real all-sky identification and fitting.
            if isinstance(kwargs.get('distortion'), (list, tuple)):
                return {'RA': None, 'Matches': None, 'Prob': None, 'T_solve': 5000.}
            return real_solve(solver, centroids, shape, **kwargs)

        with patch.object(tetra3.Tetra3, 'solve_from_centroids', bounded_solve):
            try:
                camera, audit = bootstrap(xy, fixture['shape'])
            except RuntimeError as error:
                self.fail(f'Blind bootstrap did not recover the measured field: {error}')
        # Trying the fallback first would change the seeds of previously working
        # images: all 15 established patch attempts must have their chance first.
        attempts = audit['attempts']
        self.assertEqual(len(attempts), 16)
        self.assertTrue(all(a['distortion_hypothesis'] == [-.2, .2]
                            for a in attempts[:-1]))
        self.assertEqual(attempts[-1]['distortion_hypothesis'], 0.)
        self.assertTrue(all(a['solve_time_ms'] is not None for a in attempts))
        self.assertGreaterEqual(audit['seed_stars'], 8)
        self.assertLess(audit['attempts'][-1]['probability'], 1e-6)
        self.assertFalse(audit['metadata_used'])
        self.assertTrue(camera.is_monotonic())
        self.assertTrue(np.isfinite(camera.to_sky(xy)).all())
        np.testing.assert_array_equal(xy, original)


if __name__ == '__main__':
    unittest.main()
