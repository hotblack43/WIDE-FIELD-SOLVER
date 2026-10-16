import importlib.util
import inspect
from pathlib import Path
import tempfile
import unittest

from astropy.io import fits
import numpy as np


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "focus_checker_in_fitsfiles.py"


def load_focus_checker():
    spec = importlib.util.spec_from_file_location("focus_checker_in_fitsfiles", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_star(
    shape=(25, 25),
    *,
    sigma_major=2.4,
    sigma_minor=1.2,
    theta_deg=31.0,
    amplitude=900.0,
    background=120.0,
    slope_x=0.12,
    slope_y=-0.08,
):
    yy, xx = np.indices(shape, dtype=float)
    x0 = (shape[1] - 1) / 2 + 0.23
    y0 = (shape[0] - 1) / 2 - 0.31
    theta = np.deg2rad(theta_deg)
    dx = xx - x0
    dy = yy - y0
    along = np.cos(theta) * dx + np.sin(theta) * dy
    across = -np.sin(theta) * dx + np.cos(theta) * dy
    pixels = (
        background
        + slope_x * dx
        + slope_y * dy
        + amplitude
        * np.exp(
            -0.5
            * (
                (along / sigma_major) ** 2
                + (across / sigma_minor) ** 2
            )
        )
    )
    return pixels, (x0, y0)


class EllipticalGaussianFitTests(unittest.TestCase):
    def test_recovers_rotated_unequal_axes_with_sloping_background(self):
        checker = load_focus_checker()
        pixels, centre = synthetic_star()

        result = checker.fit_elliptical_gaussian(pixels)

        self.assertTrue(result["fit_ok"], result.get("rejection_reason"))
        self.assertAlmostEqual(result["x_fit_px"], centre[0], delta=0.05)
        self.assertAlmostEqual(result["y_fit_px"], centre[1], delta=0.05)
        self.assertAlmostEqual(result["sigma_major_px"], 2.4, delta=0.06)
        self.assertAlmostEqual(result["sigma_minor_px"], 1.2, delta=0.06)
        self.assertAlmostEqual(result["axis_ratio"], 2.0, delta=0.08)
        angle_difference = abs(((result["theta_major_deg"] - 31.0 + 90) % 180) - 90)
        self.assertLess(angle_difference, 1.0)

    def test_rejects_a_fit_whose_core_contains_saturated_pixels(self):
        checker = load_focus_checker()
        pixels, _ = synthetic_star()
        saturated = np.zeros(pixels.shape, dtype=bool)
        saturated[pixels.shape[0] // 2, pixels.shape[1] // 2] = True

        result = checker.fit_elliptical_gaussian(
            pixels, saturated_mask=saturated
        )

        self.assertFalse(result["fit_ok"])
        self.assertEqual(result["rejection_reason"], "saturated_cutout")


class FocusInputAndSummaryTests(unittest.TestCase):
    def test_sensor_blur_normalisation_is_invariant_to_image_rotation(self):
        checker = load_focus_checker()

        landscape = checker.sensor_blur_um(1.5, (2249, 3371), 36.0)
        portrait = checker.sensor_blur_um(1.5, (3371, 2249), 36.0)

        self.assertAlmostEqual(landscape, portrait)
        self.assertAlmostEqual(landscape, 1.5 / 3371 * 36000.0)

    def test_loads_detection_functions_from_frozen_v17_runtime(self):
        checker = load_focus_checker()

        load_image, detect_stars = checker.load_v17_focus_tools()

        self.assertIn("/v17/point_star_image.py", inspect.getsourcefile(load_image))
        self.assertIn("/v17/point_star_detection.py", inspect.getsourcefile(detect_stars))
        self.assertIn("valid_mask", inspect.signature(detect_stars).parameters)

    def test_discovers_only_fits_exposures_strictly_longer_than_threshold(self):
        checker = load_focus_checker()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "camera" / "eight_seconds.fits"
            selected.parent.mkdir()
            fits.PrimaryHDU(
                np.ones((21, 21)), header=fits.Header({"EXPTIME": 8.0})
            ).writeto(selected)
            boundary = root / "five_seconds.fits"
            fits.PrimaryHDU(
                np.ones((21, 21)), header=fits.Header({"EXPOSURE": 5.0})
            ).writeto(boundary)
            short = root / "four_seconds.fits"
            fits.PrimaryHDU(
                np.ones((21, 21)), header=fits.Header({"EXPTIME": 4.0})
            ).writeto(short)

            records = checker.discover_focus_inputs([root], min_exposure=5.0)

        self.assertEqual([record["path"] for record in records], [selected])
        self.assertEqual(records[0]["exposure_s"], 8.0)

    def test_image_summary_uses_minor_axis_as_primary_focus_width(self):
        checker = load_focus_checker()
        rows = [
            {
                "fit_ok": True,
                "fwhm_minor_px": 2.0,
                "fwhm_major_px": 4.0,
                "axis_ratio": 2.0,
                "theta_major_deg": 10.0,
            },
            {
                "fit_ok": True,
                "fwhm_minor_px": 2.4,
                "fwhm_major_px": 5.0,
                "axis_ratio": 2.1,
                "theta_major_deg": 12.0,
            },
            {
                "fit_ok": False,
                "fwhm_minor_px": 20.0,
                "fwhm_major_px": 40.0,
                "axis_ratio": 2.0,
                "theta_major_deg": 11.0,
            },
        ]

        summary = checker.summarise_image_fits(rows)

        self.assertEqual(summary["gaussian_fits_ok"], 2)
        self.assertAlmostEqual(summary["focus_fwhm_minor_median_px"], 2.2)
        self.assertAlmostEqual(summary["fwhm_major_median_px"], 4.5)
        self.assertAlmostEqual(summary["axis_ratio_median"], 2.05)

    def test_selects_bright_unsaturated_sources_across_the_field(self):
        checker = load_focus_checker()
        detections = []
        for y in (10.0, 90.0):
            for x in (10.0, 90.0):
                for rank in range(4):
                    detections.append(
                        {
                            "detection_id": len(detections) + 1,
                            "x_px": x + rank,
                            "y_px": y,
                            "peak_snr": 100.0 - rank,
                            "saturated": False,
                            "major_sigma_px": 1.5,
                        }
                    )
        detections.append(
            {
                "detection_id": 99,
                "x_px": 50.0,
                "y_px": 50.0,
                "peak_snr": 1000.0,
                "saturated": True,
                "major_sigma_px": 1.5,
            }
        )

        selected = checker.select_focus_detections(
            detections, (101, 101), max_sources=8, grid_shape=(2, 2)
        )

        self.assertEqual(len(selected), 8)
        self.assertNotIn(99, {row["detection_id"] for row in selected})
        occupied = {
            (int(row["x_px"] >= 50), int(row["y_px"] >= 50)) for row in selected
        }
        self.assertEqual(len(occupied), 4)

    def test_fits_detected_source_and_returns_global_coordinates(self):
        checker = load_focus_checker()
        pixels = np.full((61, 61), 100.0)
        star, _ = synthetic_star(
            shape=(25, 25), sigma_major=2.0, sigma_minor=1.1, theta_deg=-24.0
        )
        pixels[18:43, 19:44] += star - 120.0
        detections = [
            {
                "detection_id": 7,
                "x_px": 31.2,
                "y_px": 29.7,
                "peak_snr": 80.0,
                "saturated": False,
                "major_sigma_px": 2.0,
                "axis_ratio": 1.8,
                "source_class": "compact",
            }
        ]

        rows = checker.fit_detected_sources(
            pixels, np.zeros(pixels.shape, dtype=bool), detections
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["fit_ok"], rows[0].get("rejection_reason"))
        self.assertEqual(rows[0]["detection_id"], 7)
        self.assertAlmostEqual(rows[0]["x_fit_image_px"], 31.23, delta=0.08)
        self.assertAlmostEqual(rows[0]["y_fit_image_px"], 29.69, delta=0.08)
        self.assertAlmostEqual(rows[0]["fwhm_minor_px"], 2.59, delta=0.12)

    def test_writes_auditable_batch_products_and_camera_comparison(self):
        checker = load_focus_checker()
        image_rows = [
            {
                "filename": "ra_8s_RGB.fits.bz2",
                "path": "/data/Ra/ra_8s_RGB.fits.bz2",
                "camera": "Canon EOS Ra",
                "date_obs": "2026-10-12T19:30:00",
                "exposure_s": 8.0,
                "image_width_px": 3371,
                "detected_sources": 800,
                "gaussian_fits_attempted": 200,
                "gaussian_fits_ok": 180,
                "focus_fwhm_minor_median_px": 2.0,
                "focus_fwhm_minor_p25_px": 1.8,
                "focus_fwhm_minor_p75_px": 2.2,
                "fwhm_major_median_px": 3.0,
                "axis_ratio_median": 1.5,
                "theta_major_median_deg": 10.0,
                "focus_mode": 3,
                "focus_range": 1,
                "focal_length_mm": 15.0,
                "f_number": 2.8,
                "solver_success": True,
            },
            {
                "filename": "r6_8s_RGB.fits.bz2",
                "path": "/data/R6m2/r6_8s_RGB.fits.bz2",
                "camera": "Canon EOS R6m2",
                "date_obs": "2026-10-12T20:30:00",
                "exposure_s": 8.0,
                "image_width_px": 2999,
                "detected_sources": 300,
                "gaussian_fits_attempted": 150,
                "gaussian_fits_ok": 120,
                "focus_fwhm_minor_median_px": 3.0,
                "focus_fwhm_minor_p25_px": 2.7,
                "focus_fwhm_minor_p75_px": 3.3,
                "fwhm_major_median_px": 4.0,
                "axis_ratio_median": 1.33,
                "theta_major_median_deg": 12.0,
                "focus_mode": 3,
                "focus_range": 1,
                "focal_length_mm": 15.0,
                "f_number": 2.8,
                "solver_success": False,
            },
        ]
        source_rows = [
            {
                "filename": "ra_8s_RGB.fits.bz2",
                "camera": "Canon EOS Ra",
                "exposure_s": 8.0,
                "detection_id": 1,
                "fit_ok": True,
                "fwhm_minor_px": 2.0,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            products = checker.write_focus_outputs(image_rows, source_rows, output)

            for name in (
                "focus_images.csv",
                "focus_sources.csv",
                "focus_summary.json",
                "focus_report.md",
                "focus_by_image.png",
                "focus_camera_comparison.png",
            ):
                self.assertTrue((output / name).is_file(), name)
                self.assertGreater((output / name).stat().st_size, 0)
            report = (output / "focus_report.md").read_text()
        self.assertIn("minor-axis FWHM", report)
        self.assertIn("Canon EOS Ra", report)
        self.assertIn("Canon EOS R6m2", report)
        self.assertIn("Manual Focus", report)
        self.assertIn("not equally affected", report)
        self.assertIn("cannot distinguish", report)
        self.assertEqual(products["images"], 2)


if __name__ == "__main__":
    unittest.main()
