import unittest

from scripts import plot_repeated_star_colours as colours


def measurement(star, image, airmass):
    return colours.ColourMeasurement(
        run_id=f"run-{image}",
        source_path=f"/images/subaru_{image}.jpg",
        source_sha256=f"image-{image}",
        catalogue_sha256="catalogue",
        star_id=star,
        detection_id=image,
        airmass=airmass,
        machine_b_minus_g=0.1,
        machine_g_minus_r=0.2,
        machine_b_minus_r=0.3,
        gaia_bp_minus_g=0.4,
        gaia_g_minus_rp=0.5,
        gaia_bp_minus_rp=0.9,
    )


class NineStarSelectionTests(unittest.TestCase):
    def test_selection_prefers_observation_count_then_airmass_span(self):
        rows = []
        for star_number in range(1, 12):
            count = star_number
            span = 0.1 if star_number != 10 else 2.0
            for image in range(count):
                fraction = image / max(1, count - 1)
                rows.append(
                    measurement(
                        f"Gaia DR3 {star_number}",
                        f"{star_number}-{image}",
                        1.0 + span * fraction,
                    )
                )

        selector = getattr(colours, "select_well_observed", None)
        self.assertIsNotNone(selector, "select_well_observed() is not implemented")
        selected = selector(rows, count=9)

        self.assertEqual(len(selected), 9)
        self.assertEqual(selected[0][0], "Gaia DR3 11")
        self.assertEqual(selected[1][0], "Gaia DR3 10")
        self.assertNotIn("Gaia DR3 1", {star_id for star_id, _rows in selected})

    def test_bright_balanced_selection_requires_sixty_percent_of_maximum_coverage(self):
        rows = []
        stars = (
            ("many-faint", 10, 7.0),
            ("bright-covered", 6, 4.0),
            ("middle-covered", 6, 5.0),
            ("bright-too-few", 5, 3.0),
        )
        for star_id, count, gaia_g in stars:
            for image in range(count):
                row = measurement(star_id, f"{star_id}-{image}", 1.0 + image / 10)
                rows.append(
                    colours.ColourMeasurement(
                        **{
                            **row.__dict__,
                            "machine_g_mag": gaia_g - 14.0 + image / 100,
                            "machine_g_minus_gaia_g": -14.0 + image / 100,
                        }
                    )
                )

        selector = getattr(colours, "select_bright_well_observed", None)
        self.assertIsNotNone(
            selector, "select_bright_well_observed() is not implemented"
        )
        selected = selector(rows, count=2, coverage_fraction=0.6)

        self.assertEqual(
            [star_id for star_id, _star_rows in selected],
            ["bright-covered", "middle-covered"],
        )


if __name__ == "__main__":
    unittest.main()
