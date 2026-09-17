import csv
from pathlib import Path
import tempfile
import unittest

from scripts import plot_repeated_star_colours as colours


class RepeatedStarColourOutputTests(unittest.TestCase):
    def test_write_outputs_creates_three_plots_and_measurement_csv(self):
        rows = []
        for star_number, catalogue_colour in ((1, 0.5), (2, 1.5)):
            for image_number, offset in ((1, 0.0), (2, 0.2)):
                rows.append(
                    colours.ColourMeasurement(
                        run_id=f"run-{image_number}",
                        source_path=f"/images/subaru_{image_number}.jpg",
                        source_sha256=f"image-{image_number}",
                        catalogue_sha256="catalogue",
                        star_id=f"Gaia DR3 {star_number}",
                        detection_id=str(star_number),
                        airmass=1.0 + image_number / 10,
                        machine_b_minus_g=catalogue_colour + 0.5 + offset,
                        machine_g_minus_r=catalogue_colour + 0.3 + offset,
                        machine_b_minus_r=2 * catalogue_colour + 0.8 + offset,
                        gaia_bp_minus_g=catalogue_colour,
                        gaia_g_minus_rp=catalogue_colour,
                        gaia_bp_minus_rp=2 * catalogue_colour,
                    )
                )

        write_outputs = getattr(colours, "write_outputs", None)
        self.assertIsNotNone(write_outputs, "write_outputs() is not implemented")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = write_outputs(rows, output)

            self.assertEqual(summary.star_count, 2)
            self.assertEqual(summary.measurement_count, 4)
            for filename in (
                "subaru_repeated_stars_machine_BG_vs_gaia_BPG.png",
                "subaru_repeated_stars_machine_GR_vs_gaia_GRP.png",
                "subaru_repeated_stars_machine_BR_vs_gaia_BPRP.png",
            ):
                path = output / filename
                self.assertGreater(path.stat().st_size, 1_000)
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

            table = output / "subaru_repeated_star_colours.csv"
            with table.open(newline="") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 4)
            self.assertEqual(
                {row["star_id"] for row in saved},
                {"Gaia DR3 1", "Gaia DR3 2"},
            )


if __name__ == "__main__":
    unittest.main()
