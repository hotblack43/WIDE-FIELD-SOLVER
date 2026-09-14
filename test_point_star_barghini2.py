import unittest

import numpy as np

from point_star_barghini2 import (
    SUPPORTED_LIMITS2,
    association_stages2,
    catalogue_indices2,
)


class WideSolver2Tests(unittest.TestCase):
    def test_supported_limits_are_modest_and_ordered(self):
        self.assertEqual(SUPPORTED_LIMITS2, (7.5, 8.0, 8.5))

    def test_association_schedule_only_reaches_requested_depth(self):
        schedule75 = association_stages2(7.5)
        schedule80 = association_stages2(8.0)
        schedule85 = association_stages2(8.5)

        self.assertEqual([stage[1] for stage in schedule75],
                         [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 7.5])
        self.assertEqual([stage[1] for stage in schedule80],
                         [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 7.5, 8.0])
        self.assertEqual([stage[1] for stage in schedule85],
                         [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 7.5, 8.0, 8.5])
        self.assertEqual(schedule85[-2:], ((1.0, 8.0, 3.0), (1.0, 8.5, 3.0)))

    def test_association_schedule_rejects_unsupported_limit(self):
        for value in (7.0, 7.6, 9.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "supported"):
                    association_stages2(value)

    def test_catalogue_indices_exclude_stars_beyond_selected_limit(self):
        magnitudes = np.array([7.499, 7.5, 7.501, 8.0, 8.5, 8.501])
        np.testing.assert_array_equal(
            catalogue_indices2(magnitudes, 7.5),
            np.array([0, 1]),
        )
        np.testing.assert_array_equal(
            catalogue_indices2(magnitudes, 8.5),
            np.array([0, 1, 2, 3, 4]),
        )


if __name__ == "__main__":
    unittest.main()
