"""Blind bootstrap must recover when the broad distortion search times out."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import tetra3

from point_star_barghini import BarghiniCamera, bootstrap


class BootstrapFallbackTests(unittest.TestCase):
    def test_bootstrap_keeps_usable_seed_when_refinement_is_worse(self):
        shape = (400, 400)
        size = round(min(shape)*.18)
        origin = np.array([(shape[1]-size)//2, (shape[0]-size)//2])
        xy = np.array([
            [171., 174.], [184., 170.], [199., 172.], [216., 176.],
            [227., 188.], [174., 195.], [189., 201.], [211., 197.],
            [225., 213.], [178., 224.], [198., 228.], [217., 223.],
        ])
        fov_deg = 20.
        focal = size/(2*np.tan(np.deg2rad(fov_deg)/2))
        offset = xy-(np.array(shape[::-1])-1)/2
        radius = np.linalg.norm(offset, axis=1)
        angle = radius/focal
        phase = np.arctan2(offset[:, 1], offset[:, 0])
        detector_rays = np.c_[np.sin(angle)*np.cos(phase),
                              np.sin(angle)*np.sin(phase), np.cos(angle)]
        sky = detector_rays*np.array([1., -1., 1.])
        ra = np.rad2deg(np.arctan2(sky[:, 1], sky[:, 0])) % 360.
        dec = np.rad2deg(np.arcsin(sky[:, 2]))
        answer = {
            'RA': 0., 'Dec': 90., 'Roll': 0., 'FOV': fov_deg,
            'Matches': len(xy), 'Prob': 1e-30, 'T_solve': 1.,
            'matched_centroids': ((xy-origin)[:, ::-1]+.5).tolist(),
            'matched_stars': np.c_[ra, dec, np.arange(len(xy))].tolist(),
        }

        class IdentifiedMirroredField:
            def solve_from_centroids(self, *args, **kwargs):
                return answer

        def unusable_refinement(camera, measured, identified, max_nfev=300):
            broken = BarghiniCamera.initial(camera.shape, 20., np.eye(3))
            return broken, dict(success=False, nfev=max_nfev, cost=1e9)

        with (patch.object(tetra3, 'Tetra3', return_value=IdentifiedMirroredField()),
              patch('point_star_barghini.fit_camera', side_effect=unusable_refinement)):
            camera, audit = bootstrap(xy, shape)

        error = np.linalg.norm(camera.to_sky(xy)-sky, axis=1)
        self.assertLess(error.max(), 1e-6)
        self.assertFalse(audit.get('fit_adopted'))

    def test_bootstrap_recovers_and_records_reflected_detector_parity(self):
        shape = (400, 400)
        size = round(min(shape)*.18)
        origin = np.array([(shape[1]-size)//2, (shape[0]-size)//2])
        xy = np.array([
            [171., 174.], [184., 170.], [199., 172.], [216., 176.],
            [227., 188.], [174., 195.], [189., 201.], [211., 197.],
            [225., 213.], [178., 224.], [198., 228.], [217., 223.],
        ])
        fov_deg = 20.
        focal = size/(2*np.tan(np.deg2rad(fov_deg)/2))
        offset = xy-(np.array(shape[::-1])-1)/2
        radius = np.linalg.norm(offset, axis=1)
        angle = radius/focal
        phase = np.arctan2(offset[:, 1], offset[:, 0])
        detector_rays = np.c_[np.sin(angle)*np.cos(phase),
                              np.sin(angle)*np.sin(phase), np.cos(angle)]
        sky = detector_rays*np.array([1., -1., 1.])
        ra = np.rad2deg(np.arctan2(sky[:, 1], sky[:, 0])) % 360.
        dec = np.rad2deg(np.arcsin(sky[:, 2]))
        answer = {
            'RA': 0., 'Dec': 90., 'Roll': 0., 'FOV': fov_deg,
            'Matches': len(xy), 'Prob': 1e-30, 'T_solve': 1.,
            'matched_centroids': ((xy-origin)[:, ::-1]+.5).tolist(),
            'matched_stars': np.c_[ra, dec, np.arange(len(xy))].tolist(),
        }

        class IdentifiedMirroredField:
            def solve_from_centroids(self, *args, **kwargs):
                return answer

        with patch.object(tetra3, 'Tetra3', return_value=IdentifiedMirroredField()):
            camera, audit = bootstrap(xy, shape)

        error = np.linalg.norm(camera.to_sky(xy)-sky, axis=1)
        self.assertLess(error.max(), 1e-6)
        self.assertEqual(camera.serialise().get('detector_parity'), 'mirrored')
        self.assertEqual(audit.get('detector_parity'), 'mirrored')

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
