import csv
from pathlib import Path
import tempfile
import unittest

from scripts import plot_repeated_star_colours as colours


class NineStarAirmassOutputTests(unittest.TestCase):
    def test_writer_creates_nine_panel_plot_and_selected_measurement_table(self):
        rows = []
        for star_number in range(1, 10):
            for image_number, airmass in ((1, 1.1), (2, 2.1), (3, 3.1)):
                rows.append(
                    colours.ColourMeasurement(
                        run_id=f"run-{image_number}",
                        source_path=f"/images/subaru_{image_number}.jpg",
                        source_sha256=f"image-{image_number}",
                        catalogue_sha256="catalogue",
                        star_id=f"Gaia DR3 {star_number}",
                        detection_id=str(star_number),
                        airmass=airmass,
                        machine_b_minus_g=0.1,
                        machine_g_minus_r=0.2,
                        machine_b_minus_r=0.3,
                        gaia_bp_minus_g=0.4,
                        gaia_g_minus_rp=0.5,
                        gaia_bp_minus_rp=0.9,
                        machine_r_minus_gaia_rp=-14.0 + 0.1 * airmass,
                        machine_g_minus_gaia_g=-14.2 + 0.2 * airmass,
                        machine_b_minus_gaia_bp=-14.4 + 0.3 * airmass,
                    )
                )

        writer = getattr(colours, "write_nine_star_airmass", None)
        self.assertIsNotNone(writer, "write_nine_star_airmass() is not implemented")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            selected = writer(rows, output)

            self.assertEqual(len(selected), 9)
            plot = output / "subaru_nine_well_observed_stars_airmass.png"
            self.assertGreater(plot.stat().st_size, 1_000)
            self.assertEqual(plot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            table = output / "subaru_nine_well_observed_stars_airmass.csv"
            with table.open(newline="") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 27)
            self.assertEqual({row["panel"] for row in saved}, {str(i) for i in range(1, 10)})


if __name__ == "__main__":
    unittest.main()
