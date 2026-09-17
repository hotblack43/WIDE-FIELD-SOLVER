import unittest

from scripts import plot_repeated_star_airmass as repeated


class PlotLimitTests(unittest.TestCase):
    def test_full_limits_expand_a_degenerate_range(self):
        full_limits = getattr(repeated, "full_limits", None)
        self.assertIsNotNone(full_limits, "full_limits() is not implemented")

        lower, upper = full_limits([5.0, 5.0])

        self.assertLess(lower, 5.0)
        self.assertGreater(upper, 5.0)


if __name__ == "__main__":
    unittest.main()
