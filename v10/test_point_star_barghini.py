"""Independent geometric checks for the untrailed Barghini calibration."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from point_star_barghini import (
    BarghiniCamera, angular_separations_arcmin, associate, astrometric_stats,
    fit_camera, plate_scale_summary, prepare_output, radial_soft_l1_residuals,
    resolved_association_gate_arcmin, select_labels, tangent_residuals_arcmin,
)


class BarghiniPointTests(unittest.TestCase):
    def test_radial_robust_loss_is_invariant_to_tangent_direction(self):
        radius = 8.
        residuals = np.array([[radius, 0.],
                              [radius/np.sqrt(2.), radius/np.sqrt(2.)]])
        transformed = radial_soft_l1_residuals(residuals, scale=3.)

        costs = .5*np.sum(transformed**2, axis=1)
        np.testing.assert_allclose(costs, [costs[0], costs[0]], atol=1e-12)

    def test_radial_robust_cost_is_continuous_across_tangent_basis_switch(self):
        angle = np.deg2rad(8./60.)
        references = np.array([
            [np.sqrt(1.-z*z), 0., z] for z in (.9-1e-9, .9+1e-9)
        ])
        predicted = references @ Rotation.from_rotvec([0., angle, 0.]).as_matrix().T
        residuals = tangent_residuals_arcmin(predicted, references)
        transformed = radial_soft_l1_residuals(residuals, scale=3.)

        costs = .5*np.sum(transformed**2, axis=1)
        self.assertAlmostEqual(float(costs[0]), float(costs[1]), places=9)

    def test_tangent_residual_does_not_treat_an_antipode_as_a_perfect_fit(self):
        reference = np.array([[1., 0., 0.]])
        residual = tangent_residuals_arcmin(-reference, reference)

        self.assertAlmostEqual(float(np.linalg.norm(residual[0])), 180.*60.)

    def test_angular_association_gate_is_independent_of_detector_resolution(self):
        decisions = []
        measured_offsets_px = []
        for size in (200, 2000):
            camera = BarghiniCamera.initial((size, size), size/2., np.eye(3))
            measured = np.array([[(size-1)/2., (size-1)/2.]])
            ray = camera.to_sky(measured)
            angle = np.deg2rad(10./60.)
            rotation = Rotation.from_rotvec([0., angle, 0.]).as_matrix()
            catalogue = ray @ rotation.T
            measured_offsets_px.append(float(np.linalg.norm(camera.project(catalogue)-measured)))
            inside = associate(camera, measured, catalogue, gate_arcmin=10.1)
            outside = associate(camera, measured, catalogue, gate_arcmin=9.9)
            decisions.append((len(inside[0]), len(outside[0])))
            np.testing.assert_allclose(
                angular_separations_arcmin(ray, catalogue), [10.], atol=1e-9)

        self.assertEqual(decisions, [(1, 0), (1, 0)])
        self.assertGreater(measured_offsets_px[1], 9.*measured_offsets_px[0])

    def test_robust_camera_fit_has_resolution_independent_angular_weighting(self):
        rng = np.random.default_rng(911)
        offsets = rng.uniform(-.3, .3, (40, 2))
        fitted_centre_rays = []
        for size in (400, 4000):
            centre = np.array([(size-1)/2., (size-1)/2.])
            measured = centre+size*offsets
            truth = BarghiniCamera.initial((size, size), size/2., np.eye(3))
            catalogue = truth.to_sky(measured)
            catalogue[-1] = catalogue[-1] @ Rotation.from_rotvec(
                [0., np.deg2rad(1.), 0.]).as_matrix().T
            initial = BarghiniCamera.initial(
                (size, size), size/2., Rotation.from_rotvec([.002, -.001, .001]).as_matrix())

            fitted, info = fit_camera(initial, measured, catalogue, max_nfev=600)

            self.assertTrue(info['success'])
            fitted_centre_rays.append(fitted.to_sky(centre[None, :]))

        separation = angular_separations_arcmin(
            fitted_centre_rays[0], fitted_centre_rays[1])[0]
        self.assertLess(separation, .05)

    def test_astrometric_stats_keep_pixels_but_make_angular_error_primary(self):
        angular_rms = []
        pixel_rms = []
        centre_scales = []
        for size in (200, 2000):
            camera = BarghiniCamera.initial((size, size), size/2., np.eye(3))
            centre = np.array([[(size-1)/2., (size-1)/2.]])
            measured_ray = camera.to_sky(centre)
            catalogue = measured_ray @ Rotation.from_rotvec(
                [0., np.deg2rad(10./60.), 0.]).as_matrix().T

            score = astrometric_stats(camera, centre, catalogue)
            scale = plate_scale_summary(camera)

            angular_rms.append(score['rms_arcmin'])
            pixel_rms.append(score['rms_px'])
            centre_scales.append(scale['centre_arcmin_per_px'])

        np.testing.assert_allclose(angular_rms, [10., 10.], atol=1e-9)
        self.assertGreater(pixel_rms[1], 9.*pixel_rms[0])
        self.assertGreater(centre_scales[0], 9.*centre_scales[1])

    def test_angular_gate_includes_coarse_camera_sampling_without_becoming_pixel_based(self):
        coarse = BarghiniCamera.initial((200, 200), 100., np.eye(3))
        fine = BarghiniCamera.initial((2000, 2000), 1000., np.eye(3))

        coarse_gate = resolved_association_gate_arcmin(coarse, physical_floor_arcmin=8.1)
        fine_gate = resolved_association_gate_arcmin(fine, physical_floor_arcmin=8.1)

        self.assertGreater(coarse_gate, 30.)
        self.assertAlmostEqual(fine_gate, 8.1)

    def test_serialised_camera_without_parity_defaults_to_normal(self):
        camera = BarghiniCamera.initial((100, 120), 60., np.eye(3))
        saved = camera.serialise()
        saved.pop('detector_parity')

        restored = BarghiniCamera.from_serialised(saved)

        self.assertEqual(restored.detector_parity, 1)

    def test_camera_rejects_invalid_detector_parity(self):
        with self.assertRaisesRegex(ValueError, 'detector parity'):
            BarghiniCamera.initial((100, 120), 60., np.eye(3), detector_parity=0)

    def test_existing_output_is_replaced_by_default(self):
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent)/'solution'
            output.mkdir()
            (output/'stale.txt').write_text('old result')

            prepare_output(output)

            self.assertTrue(output.is_dir())
            self.assertFalse((output/'stale.txt').exists())

    def test_no_overwrite_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent)/'solution'
            output.mkdir()
            stale = output/'stale.txt'
            stale.write_text('old result')

            with self.assertRaises(FileExistsError):
                prepare_output(output, overwrite=False)

            self.assertEqual(stale.read_text(), 'old result')

    def test_repository_root_cannot_be_output(self):
        repository = Path(__file__).resolve().parent

        with self.assertRaises(ValueError):
            prepare_output(repository)

    def test_repository_ancestor_cannot_be_output(self):
        repository_parent = Path(__file__).resolve().parent.parent

        with self.assertRaises(ValueError):
            prepare_output(repository_parent, overwrite=False)

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
