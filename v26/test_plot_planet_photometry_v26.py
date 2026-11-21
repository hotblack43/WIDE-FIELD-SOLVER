"""V26 saturated-wing planet-photometry regressions."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import unittest


def _load_plotter():
    name = "_test_v26_plot_planet_photometry"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / "scripts" / "plot_planet_photometry.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    original_path = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


class SaturatedWingPlanetPhotometryTests(unittest.TestCase):
    def test_accepted_wing_fit_replaces_clipped_saturated_aperture(self):
        plotter = _load_plotter()
        rate, magnitude, reason, method = plotter._quality(
            {
                "exposure_seconds": "20",
                "saturation_known": "True",
                "G_saturated": "True",
                "G_photometry_usable": "True",
                "G_measurement_method": "saturated_aperture_lower_bound",
                "G_count_rate_adu_per_s": "79513.4",
                "G_wing_fit_status": "modelled_from_unsaturated_wings",
                "G_wing_fit_count_rate_adu_per_s": "189859.87352337723",
            },
            "G",
        )

        self.assertAlmostEqual(rate, 189859.87352337723)
        self.assertAlmostEqual(magnitude, -2.5 * math.log10(rate))
        self.assertEqual(reason, "")
        self.assertEqual(method, "psf_wing_model")

    def test_wing_model_uses_conservative_method_uncertainty_floor(self):
        plotter = _load_plotter()
        uncertainty = plotter._measurement_uncertainty(
            {"measurement_method": "psf_wing_model"},
            {
                "machine_magnitude_uncertainty": 0.02,
                "uncertainty_status": "available",
                "uncertainty_source": "background-only aperture variance",
            },
        )

        self.assertEqual(uncertainty["machine_magnitude_uncertainty"], 1.8)
        self.assertEqual(
            uncertainty["uncertainty_status"],
            "available_with_psf_wing_model_floor",
        )
        self.assertIn("1.8 mag", uncertainty["uncertainty_source"])


if __name__ == "__main__":
    unittest.main()
