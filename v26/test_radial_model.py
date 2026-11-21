"""Geometric checks for nested radius-dependent Barghini models."""
from __future__ import annotations

import unittest

import numpy as np

from barghini_model import (
    extended_radial_du_dr,
    extended_radial_u,
    radial_u,
)
from point_star_barghini import BarghiniCamera
from radial_model import ExtendedBarghiniCamera


class RadialMappingTests(unittest.TestCase):
    def setUp(self):
        self.baseline = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))
        self.parameters = self.baseline.physical
        self.scale = self.baseline.scale

    def test_empty_extension_is_exactly_the_baseline_mapping(self):
        radius = np.linspace(0.0, self.scale, 31)
        expected = radial_u(
            radius,
            self.parameters.v,
            self.parameters.s,
            self.parameters.d,
        )
        actual = extended_radial_u(radius, self.parameters, self.scale, [])
        np.testing.assert_array_equal(actual, expected)

    def test_coefficients_add_normalised_odd_powers(self):
        radius = np.array([0.0, 0.25, 0.75, 1.1]) * self.scale
        coefficients = np.array([0.013, -0.004])
        baseline = radial_u(
            radius,
            self.parameters.v,
            self.parameters.s,
            self.parameters.d,
        )
        rho = radius / self.scale
        expected = baseline + coefficients[0] * rho**3 + coefficients[1] * rho**5
        np.testing.assert_allclose(
            extended_radial_u(radius, self.parameters, self.scale, coefficients),
            expected,
            atol=1e-15,
        )

    def test_analytic_derivative_matches_central_difference(self):
        coefficients = np.array([0.013, -0.004, 0.001])
        radius = np.linspace(20.0, self.scale, 17)
        step = 1e-3
        finite = (
            extended_radial_u(radius + step, self.parameters, self.scale, coefficients)
            - extended_radial_u(radius - step, self.parameters, self.scale, coefficients)
        ) / (2.0 * step)
        analytic = extended_radial_du_dr(
            radius, self.parameters, self.scale, coefficients
        )
        np.testing.assert_allclose(analytic, finite, rtol=2e-8, atol=2e-10)

    def test_camera_forward_inverse_round_trip(self):
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline, coefficients=[0.008, -0.001]
        )
        xy = np.array(
            [
                [499.5, 399.5],
                [50.0, 60.0],
                [949.0, 70.0],
                [900.0, 735.0],
                [110.0, 720.0],
            ]
        )
        np.testing.assert_allclose(camera.project(camera.to_sky(xy)), xy, atol=1e-7)

    def test_serialisation_describes_the_extension_and_validity(self):
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline, coefficients=[0.008, -0.001]
        )
        saved = camera.serialise()
        extension = saved["radial_extension"]
        self.assertEqual(extension["powers"], [3, 5])
        self.assertEqual(extension["coefficients_rad"], [0.008, -0.001])
        self.assertEqual(extension["coefficient_units"], "radian")
        self.assertEqual(extension["normalised_radius"], "r / scale_px")
        self.assertEqual(extension["scale_px"], camera.scale)
        self.assertTrue(saved["radial_validation"]["valid"])
        self.assertGreater(saved["radial_validation"]["minimum_derivative"], 0.0)


class InvalidRadialModelTests(unittest.TestCase):
    def setUp(self):
        self.baseline = BarghiniCamera.initial((800, 1000), 520.0, np.eye(3))

    def test_dense_grid_finds_interior_non_monotonic_region(self):
        # The derivative is still positive at the origin and detector endpoint;
        # checking only those two inherited locations would miss the turnover.
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline,
            coefficients=[-2.0, 1.4],
        )
        _, derivative = camera.radial_derivative_grid()
        self.assertGreater(derivative[0], 0.0)
        self.assertGreater(derivative[-1], 0.0)
        self.assertLess(np.min(derivative[1:-1]), 0.0)
        validation = camera.is_valid()
        self.assertFalse(validation.valid)
        self.assertEqual(validation.reason, "non_monotonic")

    def test_endpoint_beyond_unique_angular_domain_is_rejected(self):
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline,
            coefficients=[3.5],
        )
        validation = camera.is_valid()
        self.assertFalse(validation.valid)
        self.assertEqual(validation.reason, "inverse_domain")
        self.assertGreaterEqual(validation.endpoint_angle_rad, np.pi)

    def test_active_field_can_be_valid_when_unused_corner_crosses_antipode(self):
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline,
            coefficients=[3.5],
        )
        self.assertFalse(camera.is_valid().valid)
        validation = camera.is_valid(radius_limit_px=150.0)
        self.assertTrue(validation.valid)
        self.assertLess(validation.endpoint_angle_rad, np.pi)

    def test_non_finite_coefficient_has_its_own_failure_reason(self):
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline,
            coefficients=[np.nan],
        )
        validation = camera.is_valid()
        self.assertFalse(validation.valid)
        self.assertEqual(validation.reason, "non_finite_coefficients")
        self.assertIsNone(validation.minimum_derivative)

    def test_inverse_projection_accepts_targets_inside_monotonic_active_field(self):
        camera = ExtendedBarghiniCamera.from_camera(
            self.baseline,
            coefficients=[3.5],
        )
        xy = np.array([[499.5, 399.5], [610.0, 410.0]])
        np.testing.assert_allclose(camera.project(camera.to_sky(xy)), xy, atol=1e-7)


if __name__ == "__main__":
    unittest.main()
