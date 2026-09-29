import unittest

import numpy as np

from point_star_barghini import (
    BarghiniCamera,
    angular_separations_arcmin,
    fit_camera,
    select_integrated_refraction,
)
from point_star_refraction import IntegratedRefraction


class IntegratedRefractionCameraTests(unittest.TestCase):
    def setUp(self):
        self.shape = (1000, 1200)
        self.rotation = np.eye(3)
        self.base = BarghiniCamera.initial(self.shape, 520.0, self.rotation)
        centre = np.array([(self.shape[1] - 1) / 2, (self.shape[0] - 1) / 2])
        x = np.linspace(-430.0, 430.0, 19)
        y = np.linspace(-360.0, 360.0, 17)
        grid = np.array([(a, b) for b in y for a in x]) + centre
        self.xy = grid[np.linalg.norm(grid - centre, axis=1) < 450.0]

    def truth_camera(self, a_arcsec=55.0, b_arcsec=0.15):
        zenith = np.array([0.32, -0.24, 0.9165])
        zenith /= np.linalg.norm(zenith)
        return BarghiniCamera(
            self.shape,
            self.rotation,
            self.base.p.copy(),
            refraction=IntegratedRefraction(
                status="candidate",
                zenith_camera=zenith,
                refraction_a_arcsec=a_arcsec,
                refraction_b_arcsec=b_arcsec,
            ),
        )

    def test_forward_inverse_and_serialisation_include_refraction(self):
        camera = self.truth_camera()
        sky = camera.to_sky(self.xy)
        reconstructed = camera.project(sky)
        np.testing.assert_allclose(reconstructed, self.xy, atol=2.0e-6)

        restored = BarghiniCamera.from_serialised(camera.serialise())
        np.testing.assert_allclose(restored.to_sky(self.xy), sky, atol=2.0e-12)
        self.assertEqual(restored.refraction.status, "candidate")
        self.assertAlmostEqual(restored.refraction.refraction_a_arcsec, 55.0)

    def test_project_rejects_rays_outside_supported_horizon_domain(self):
        camera = self.truth_camera()
        opposite_horizon = -camera.refraction.zenith_camera[None, :]
        with self.assertRaisesRegex(ValueError, "refraction domain"):
            camera.project(opposite_horizon)

    def test_joint_fit_recovers_injected_refraction_with_outliers(self):
        truth = self.truth_camera()
        sky = truth.to_sky(self.xy)
        corrupted = sky.copy()
        angle = np.deg2rad(0.5)
        rotation = np.array(
            [[np.cos(angle), -np.sin(angle), 0.0],
             [np.sin(angle), np.cos(angle), 0.0],
             [0.0, 0.0, 1.0]]
        )
        outliers = np.arange(0, len(corrupted), 31)
        corrupted[outliers[::2]] = corrupted[outliers[::2]] @ rotation.T
        corrupted[outliers[1::2]] = corrupted[outliers[1::2]] @ rotation

        baseline, _ = fit_camera(self.base, self.xy, corrupted, max_nfev=500)
        fitted, info = fit_camera(
            self.base, self.xy, corrupted, max_nfev=1200, fit_refraction=True
        )
        clean = np.ones(len(self.xy), dtype=bool)
        clean[outliers] = False
        baseline_error = np.median(
            angular_separations_arcmin(baseline.to_sky(self.xy[clean]), sky[clean])
        )
        fitted_error = np.median(
            angular_separations_arcmin(fitted.to_sky(self.xy[clean]), sky[clean])
        )
        self.assertEqual(info["robust_loss"], "radial_soft_l1_per_star")
        self.assertLess(fitted_error, 0.35 * baseline_error)
        self.assertGreater(fitted.refraction.refraction_a_arcsec, 10.0)
        self.assertLess(fitted.refraction.refraction_a_arcsec, 120.0)

    def test_zero_refraction_remains_nested(self):
        sky = self.base.to_sky(self.xy)
        fitted, _ = fit_camera(
            self.base, self.xy, sky, max_nfev=700, fit_refraction=True
        )
        error = angular_separations_arcmin(fitted.to_sky(self.xy), sky)
        self.assertLess(float(np.max(error)), 1.0e-5)
        self.assertLess(abs(fitted.refraction.refraction_a_arcsec), 0.05)
        self.assertLess(abs(fitted.refraction.refraction_b_arcsec), 0.01)

    def test_blocked_validation_adopts_signal_and_rejects_exact_zero(self):
        truth = self.truth_camera()
        refracted_sky = truth.to_sky(self.xy)
        candidate, _ = fit_camera(
            self.base, self.xy, refracted_sky, max_nfev=900, fit_refraction=True
        )
        adopted, evidence = select_integrated_refraction(
            self.base, self.xy, refracted_sky, candidate=candidate,
            folds=3, max_nfev=350,
        )
        self.assertEqual(adopted.refraction.status, "adopted")
        self.assertTrue(evidence["adopted"])
        self.assertEqual(len(evidence["folds"]), 3)

        zero_sky = self.base.to_sky(self.xy)
        zero_candidate, _ = fit_camera(
            self.base, self.xy, zero_sky, max_nfev=500, fit_refraction=True
        )
        rejected, evidence = select_integrated_refraction(
            self.base, self.xy, zero_sky, candidate=zero_candidate,
            folds=3, max_nfev=250,
        )
        self.assertFalse(evidence["adopted"])
        self.assertTrue(rejected.refraction.is_zero)
        self.assertEqual(rejected.refraction.refraction_a_arcsec, 0.0)
        self.assertEqual(rejected.refraction.refraction_b_arcsec, 0.0)


if __name__ == "__main__":
    unittest.main()
