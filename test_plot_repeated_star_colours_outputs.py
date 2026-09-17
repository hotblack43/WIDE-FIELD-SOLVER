import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts import plot_repeated_star_colours as colours


class RepeatedStarColourOutputTests(unittest.TestCase):
    def test_colour_plot_excludes_extreme_residual_but_keeps_csv_measurement(self):
        rows = []
        for star_number in range(1, 21):
            catalogue_colour = star_number / 10
            for image_number, offset in enumerate((-0.03, 0.0, 0.03), 1):
                machine_colour = 0.2 + 0.4 * catalogue_colour + offset
                rows.append(
                    colours.ColourMeasurement(
                        run_id=f"run-{star_number}-{image_number}",
                        source_path=f"/images/subaru_{image_number}.jpg",
                        source_sha256=f"image-{star_number}-{image_number}",
                        catalogue_sha256="catalogue",
                        star_id=f"Gaia DR3 {star_number}",
                        detection_id=str(star_number),
                        airmass=1.0,
                        machine_b_minus_g=machine_colour,
                        machine_g_minus_r=machine_colour,
                        machine_b_minus_r=machine_colour,
                        gaia_bp_minus_g=catalogue_colour,
                        gaia_g_minus_rp=catalogue_colour,
                        gaia_bp_minus_rp=catalogue_colour,
                        machine_r_mag=10.0 + catalogue_colour,
                        machine_g_mag=10.2 + catalogue_colour,
                        machine_b_mag=10.4 + catalogue_colour,
                        machine_r_minus_gaia_rp=1.0 + offset,
                        machine_g_minus_gaia_g=1.0 + offset,
                        machine_b_minus_gaia_bp=1.0 + offset,
                    )
                )
        rows.append(
            colours.ColourMeasurement(
                run_id="extreme",
                source_path="/images/subaru_extreme.jpg",
                source_sha256="image-extreme",
                catalogue_sha256="catalogue",
                star_id="Gaia DR3 10",
                detection_id="extreme",
                airmass=1.0,
                machine_b_minus_g=20.0,
                machine_g_minus_r=20.0,
                machine_b_minus_r=20.0,
                gaia_bp_minus_g=1.0,
                gaia_g_minus_rp=1.0,
                gaia_bp_minus_rp=1.0,
                machine_r_mag=11.0,
                machine_g_mag=11.2,
                machine_b_mag=11.4,
                machine_r_minus_gaia_rp=1.0,
                machine_g_minus_gaia_g=1.0,
                machine_b_minus_gaia_bp=1.0,
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = colours.write_outputs(rows, output)

            self.assertEqual(summary.measurement_count, 61)
            with (output / "subaru_repeated_star_colours.csv").open(
                newline=""
            ) as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 61)
            audit_path = (
                output
                / "subaru_repeated_stars_machine_BR_vs_gaia_BPRP.json"
            )
            audit = json.loads(audit_path.read_text())
            self.assertEqual(audit["input_observations"], 61)
            self.assertEqual(audit["plotted_observations"], 60)
            self.assertEqual(audit["excluded_extreme_residuals"], 1)
            self.assertLess(audit["y_limits"][1], 2.0)

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

    def test_four_star_writer_selects_most_observed_and_writes_rgb_pair_grid(self):
        rows = []
        observation_counts = {1: 7, 2: 6, 3: 5, 4: 4, 5: 3}
        for star_number, count in observation_counts.items():
            for image_number in range(1, count + 1):
                airmass = 1.0 + image_number / 10
                r_mag = 10.0 + star_number / 10 + image_number / 50
                g_mag = r_mag + 0.4 + airmass / 100
                b_mag = g_mag + 0.6 + airmass / 80
                rows.append(
                    colours.ColourMeasurement(
                        run_id=f"run-{star_number}-{image_number}",
                        source_path=f"/images/subaru_{image_number}.jpg",
                        source_sha256=f"image-{star_number}-{image_number}",
                        catalogue_sha256="catalogue",
                        star_id=f"Gaia DR3 {star_number}",
                        detection_id=str(star_number),
                        airmass=airmass,
                        machine_b_minus_g=b_mag - g_mag,
                        machine_g_minus_r=g_mag - r_mag,
                        machine_b_minus_r=b_mag - r_mag,
                        gaia_bp_minus_g=0.5,
                        gaia_g_minus_rp=0.4,
                        gaia_bp_minus_rp=0.9,
                        machine_r_mag=r_mag,
                        machine_g_mag=g_mag,
                        machine_b_mag=b_mag,
                    )
                )

        writer = getattr(colours, "write_four_star_rgb_pairs", None)
        self.assertIsNotNone(
            writer, "write_four_star_rgb_pairs() is not implemented"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            selected = writer(rows, output)

            self.assertEqual(
                [(star_id, len(star_rows)) for star_id, star_rows in selected],
                [
                    ("Gaia DR3 1", 7),
                    ("Gaia DR3 2", 6),
                    ("Gaia DR3 3", 5),
                    ("Gaia DR3 4", 4),
                ],
            )
            plot = output / "subaru_four_well_observed_stars_rgb_pairs.png"
            self.assertGreater(plot.stat().st_size, 1_000)
            self.assertEqual(plot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            table = output / "subaru_four_well_observed_stars_rgb_pairs.csv"
            with table.open(newline="") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 22)
            self.assertEqual({row["panel_row"] for row in saved}, {"1", "2", "3", "4"})
            self.assertNotIn("Gaia DR3 5", {row["star_id"] for row in saved})


if __name__ == "__main__":
    unittest.main()
