import unittest

from analyse_image2 import association_stability2, validate_limits2


class AnalyseImage2Tests(unittest.TestCase):
    def test_validate_limits_accepts_only_ordered_unique_supported_values(self):
        self.assertEqual(validate_limits2([7.5, 8.0, 8.5]), (7.5, 8.0, 8.5))
        for values in ([8.0, 7.5], [7.5, 7.5], [7.5, 9.0], []):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    validate_limits2(values)

    def test_association_stability_counts_stars_pairs_and_reassignments(self):
        previous = [
            {"detection_id": "1", "star_id": "A"},
            {"detection_id": "2", "star_id": "B"},
            {"detection_id": "3", "star_id": "C"},
        ]
        current = [
            {"detection_id": "1", "star_id": "A"},
            {"detection_id": "2", "star_id": "X"},
            {"detection_id": "4", "star_id": "C"},
            {"detection_id": "5", "star_id": "D"},
        ]

        self.assertEqual(
            association_stability2(previous, current),
            {
                "previous_associations": 3,
                "current_associations": 4,
                "retained_star_ids": 2,
                "gained_star_ids": 2,
                "lost_star_ids": 1,
                "stable_detector_star_pairs": 1,
                "reassigned_detections": 1,
                "retained_star_id_values": ["A", "C"],
                "gained_star_id_values": ["D", "X"],
                "lost_star_id_values": ["B"],
            },
        )


if __name__ == "__main__":
    unittest.main()
