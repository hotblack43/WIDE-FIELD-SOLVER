"""Independent geometric checks for the untrailed Barghini calibration."""
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from point_star_barghini import BarghiniCamera, fit_camera, select_labels


class BarghiniPointTests(unittest.TestCase):
    def test_labels_spread_out_and_exclude_poor_matches(self):
        rows = [dict(x_px=500., y_px=500., magnitude=-1., residual_px=.1,
                     source_class='compact', star_id='centre')]
        for i in range(12):
            angle = i*np.pi/6
            rows.append(dict(x_px=500+400*np.cos(angle), y_px=500+400*np.sin(angle),
                             magnitude=3., residual_px=.2, source_class='compact', star_id=f'ring{i}'))
        for i in range(100):
            rows.append(dict(x_px=495+i%10, y_px=495+i//10, magnitude=1.,
                             residual_px=.1, source_class='compact', star_id=f'crowded{i}'))
        rows.append(dict(x_px=0., y_px=0., magnitude=-2., residual_px=3.,
                         source_class='compact', star_id='bad'))
        selected = select_labels(rows, 12)
        self.assertEqual(len(selected), 12)
        self.assertGreaterEqual(sum(r['star_id'].startswith('ring') for r in selected), 10)
        self.assertNotIn('bad', [r['star_id'] for r in selected])

    def test_equidistant_coordinates_and_inverse(self):
        camera = BarghiniCamera.initial((800, 1000), 500., np.eye(3))
        xy = np.array([[499.5, 399.5], [599.5, 399.5], [499.5, 499.5]])
        expected = [[0, 0, 1], [np.sin(.2), 0, np.cos(.2)],
                    [0, np.sin(.2), np.cos(.2)]]
        np.testing.assert_allclose(camera.to_sky(xy), expected, atol=1e-12)
        np.testing.assert_allclose(camera.project(np.array(expected)), xy, atol=1e-7)

    def test_recovers_distorted_field_on_unfitted_stars(self):
        rng = np.random.default_rng(611)
        radius = np.sqrt(rng.uniform(0, 1, 100))*360
        phase = rng.uniform(-np.pi, np.pi, 100)
        xy = np.c_[492+radius*np.cos(phase), 407+radius*np.sin(phase)]
        angle = .0018*radius + .018*np.expm1(.003*radius)
        rays = np.c_[np.sin(angle)*np.cos(phase), np.sin(angle)*np.sin(phase), np.cos(angle)]
        sky = rays @ Rotation.from_rotvec([.025, -.02, .01]).as_matrix().T
        camera = BarghiniCamera.initial((800, 1000), 520., np.eye(3))
        fitted, info = fit_camera(camera, xy[:80], sky[:80], max_nfev=600)
        error = np.linalg.norm(fitted.project(sky[80:])-xy[80:], axis=1)
        self.assertLess(np.max(error), .02)
        self.assertTrue(fitted.is_monotonic())


if __name__ == '__main__':
    unittest.main()
