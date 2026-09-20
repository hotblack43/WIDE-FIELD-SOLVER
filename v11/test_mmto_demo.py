"""Regression tests for the permitted native-colour MMTO release example."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.check_mmto_demo import check_result


SOURCE_SHA256 = "d7278337c18a87e19b4254dbd053769cc10233732f1ce686a44b235a567fa960"
CATALOGUE_SHA256 = "766a5cbfc9c1f935a9b67a083ca1e86e09c1201cb00011f139f8ddf751a9d4a0"
BASELINE = {
    "source_sha256": SOURCE_SHA256,
    "catalogue_sha256": CATALOGUE_SHA256,
    "acceptance": {
        "minimum_detections": 1500,
        "minimum_associated_stars": 1380,
        "maximum_rms_px": 0.4,
        "maximum_median_px": 0.3,
        "maximum_p90_px": 0.65,
        "maximum_rms_arcmin": 3.0,
        "minimum_broad_or_saturated_objects": 5,
        "exposure_seconds": 20.0,
    },
}
GOOD_RESULT = {
    "status": "point_star_fit_converged",
    "source_sha256": SOURCE_SHA256,
    "catalogue_sha256": CATALOGUE_SHA256,
    "metadata_used": False,
    "trails_used": False,
    "withheld_stars": 0,
    "detection_count": 1526,
    "broad_or_saturated_objects": 8,
    "fit": {
        "count": 1409,
        "rms_px": 0.32894,
        "median_px": 0.22741,
        "p90_px": 0.51415,
        "rms_arcmin": 2.54337,
    },
    "camera": {
        "shape": [1411, 1422],
        "detector_parity": "mirrored",
        "monotonic_on_detector": True,
    },
    "input_image": {
        "format": "fits",
        "plane_names": ["R", "G", "B"],
        "native_depth_preserved": True,
        "source_compression": "bz2",
        "exposure": {"status": "available", "seconds": 20.0},
    },
}


class MMTODemoChecks(unittest.TestCase):
    def test_accepts_reference_result(self):
        self.assertEqual(check_result(GOOD_RESULT, BASELINE), [])

    def test_rejects_changed_pixels_metadata_use_and_counts(self):
        bad = copy.deepcopy(GOOD_RESULT)
        bad["source_sha256"] = "0" * 64
        bad["metadata_used"] = True
        bad["fit"]["count"] = BASELINE["acceptance"]["minimum_associated_stars"] - 1
        failures = check_result(bad, BASELINE)
        self.assertIn("approved MMTO input checksum", failures)
        self.assertIn("blind stellar fit", failures)
        self.assertIn("association count", failures)

    def test_rejects_non_native_or_non_rgb_input(self):
        bad = copy.deepcopy(GOOD_RESULT)
        bad["input_image"]["plane_names"] = ["L"]
        bad["input_image"]["native_depth_preserved"] = False
        self.assertIn("native RGB planes", check_result(bad, BASELINE))
        self.assertIn("native depth preserved", check_result(bad, BASELINE))


class MMTODemoRunnerTests(unittest.TestCase):
    def test_runner_uses_bundled_rgb_fits_and_offline_catalogue(self):
        from scripts.run_mmto_demo import ROOT, run_demo

        output = Path("/tmp/mmto-release-demo-test")
        with patch("scripts.run_mmto_demo.subprocess.run") as run:
            run_demo(output)
        self.assertEqual(run.call_count, 2)
        solver = run.call_args_list[0].args[0]
        self.assertEqual(
            solver[2],
            str(ROOT/"examples/mmto/2026_09_19__02_20_01.fits.bz2"),
        )
        self.assertEqual(solver[solver.index("--output") + 1], str(output.resolve()))
        self.assertEqual(
            solver[solver.index("--catalog") + 1],
            str(ROOT/"data/stars_gaia_dr3_g75.csv"),
        )
        self.assertIn("--offline", solver)
        self.assertIn("--overwrite", solver)
        self.assertEqual(
            solver[solver.index("--names-cache") + 1],
            str(ROOT/"data/display_names.json"),
        )
        self.assertTrue(run.call_args_list[0].kwargs["check"])
        checker = run.call_args_list[1].args[0]
        self.assertEqual(checker[-1], str(output.resolve()))
        self.assertTrue(run.call_args_list[1].kwargs["check"])


if __name__ == "__main__":
    unittest.main()
