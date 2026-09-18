import unittest

import numpy as np
from astropy.time import Time

from make_figures import (
    discover_planet_detections,
    fitted_horizon_radius,
    load_context,
    published_planet_positions,
    refine_epoch,
)


class ManuscriptFigureAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = load_context()

    def test_saved_solution_and_planet_results_refer_to_same_image(self):
        self.assertEqual(self.context.solution["source_sha256"], self.context.report["source_sha256"])
        self.assertEqual(self.context.solution["fit"]["count"], 1213)
        self.assertEqual(
            {row["planet"] for row in self.context.recoveries},
            {"mars", "jupiter", "saturn"},
        )

    def test_fitted_ninety_degree_radius_matches_saved_camera(self):
        self.assertAlmostEqual(fitted_horizon_radius(self.context.camera), 441.165131, places=5)

    def test_planet_positions_use_saved_measured_and_predicted_coordinates(self):
        positions = published_planet_positions(self.context)
        np.testing.assert_allclose(positions["mars"].measured_xy, [208.5376709634, 489.8782934821], atol=1e-9)
        np.testing.assert_allclose(positions["mars"].predicted_xy, [208.6018737092, 489.8832349929], atol=1e-9)
        np.testing.assert_allclose(positions["jupiter"].measured_xy, [495.0988338469, 434.9728010429], atol=1e-9)
        np.testing.assert_allclose(positions["saturn"].predicted_xy, [239.8518641058, 474.7603205041], atol=1e-9)

    def test_blind_daily_date_recovers_three_planet_detection_ids(self):
        detections = discover_planet_detections(
            self.context,
            Time("2018-04-15", scale="tdb"),
            ("mars", "jupiter", "saturn"),
            maximum_separation_deg=0.25,
        )
        self.assertEqual(
            {planet: match.detection_id for planet, match in detections.items()},
            {"mars": 36, "jupiter": 8, "saturn": 54},
        )

    def test_continuous_refinement_reproduces_saved_minimum(self):
        matches = discover_planet_detections(
            self.context,
            Time("2018-04-15", scale="tdb"),
            ("mars", "jupiter", "saturn"),
            maximum_separation_deg=0.25,
        )
        best_time, best_rms = refine_epoch(self.context, matches)
        expected = Time("2018-04-15T07:08:16.463", scale="utc")
        self.assertLess(abs((best_time - expected).sec), 0.2)
        self.assertAlmostEqual(best_rms, 0.0460155055, places=8)


if __name__ == "__main__":
    unittest.main()
