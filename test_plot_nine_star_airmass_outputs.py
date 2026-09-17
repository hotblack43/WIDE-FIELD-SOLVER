import csv
import inspect
import json
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

    def test_g_writer_creates_nine_panel_machine_minus_catalogue_plot(self):
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
                        machine_g_minus_gaia_g=-14.2 + 0.2 * airmass,
                    )
                )

        writer = getattr(colours, "write_nine_star_channel_airmass", None)
        self.assertIsNotNone(
            writer, "write_nine_star_channel_airmass() is not implemented"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            selected = writer(rows, output, channel="G")

            self.assertEqual(len(selected), 9)
            plot = output / "subaru_nine_well_observed_stars_G_airmass.png"
            self.assertGreater(plot.stat().st_size, 1_000)
            self.assertEqual(plot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            table = output / "subaru_nine_well_observed_stars_G_airmass.csv"
            with table.open(newline="") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 27)
            self.assertEqual({row["panel"] for row in saved}, {str(i) for i in range(1, 10)})

    def test_shared_range_g_writer_excludes_airmass_above_five(self):
        rows = []
        for star_number in range(1, 10):
            for image_number, airmass in (
                (1, 1.1), (2, 2.1), (3, 3.1), (4, 4.9), (5, 5.1)
            ):
                rows.append(
                    colours.ColourMeasurement(
                        run_id=f"run-{star_number}-{image_number}",
                        source_path=f"/images/subaru_{image_number}.jpg",
                        source_sha256=f"image-{star_number}-{image_number}",
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
                        machine_g_minus_gaia_g=(
                            -14.2 + 0.2 * airmass if airmass <= 5 else -50.0
                        ),
                    )
                )

        writer = getattr(
            colours, "write_nine_star_g_airmass_shared_ranges", None
        )
        self.assertIsNotNone(
            writer,
            "write_nine_star_g_airmass_shared_ranges() is not implemented",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            selected = writer(rows, output, max_airmass=5.0)

            self.assertEqual(len(selected), 9)
            self.assertEqual({len(star_rows) for _star, star_rows in selected}, {4})
            plot = (
                output
                / "subaru_nine_well_observed_stars_G_airmass_shared_ranges_le5.png"
            )
            self.assertGreater(plot.stat().st_size, 1_000)
            self.assertEqual(plot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            table = (
                output
                / "subaru_nine_well_observed_stars_G_airmass_shared_ranges_le5.csv"
            )
            with table.open(newline="") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 36)
            self.assertLessEqual(max(float(row["airmass"]) for row in saved), 5.0)
            self.assertGreater(min(float(row["machine_g_minus_gaia_g"]) for row in saved), -20)
            limits = json.loads(
                (
                    output
                    / "subaru_nine_well_observed_stars_G_airmass_shared_ranges_le5.json"
                ).read_text()
            )
            self.assertEqual(limits["x_limits"], [0.0, 5.0])
            self.assertEqual(limits["panel_count"], 9)
            self.assertEqual(limits["excluded_above_max_airmass"], 9)

    def test_shared_range_writer_can_balance_brightness_and_repeat_coverage(self):
        rows = []
        star_specs = [(number, 6, 4.0 + number / 10) for number in range(1, 10)]
        star_specs.append((10, 3, 1.0))
        for star_number, count, gaia_g in star_specs:
            for image_number in range(1, count + 1):
                airmass = 1.0 + image_number / 10
                residual = -14.0 + image_number / 100
                rows.append(
                    colours.ColourMeasurement(
                        run_id=f"run-{star_number}-{image_number}",
                        source_path=f"/images/subaru_{image_number}.jpg",
                        source_sha256=f"image-{star_number}-{image_number}",
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
                        machine_g_mag=gaia_g + residual,
                        machine_g_minus_gaia_g=residual,
                    )
                )

        writer = colours.write_nine_star_g_airmass_shared_ranges
        self.assertIn(
            "selection_mode", inspect.signature(writer).parameters,
            "shared-range writer cannot select bright well-observed stars",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            selected = writer(
                rows, output, max_airmass=5.0,
                selection_mode="bright_balanced",
            )

            self.assertEqual(len(selected), 9)
            self.assertNotIn(
                "Gaia DR3 10", {star_id for star_id, _star_rows in selected}
            )
            stem = (
                "subaru_nine_bright_well_observed_stars_G_airmass_"
                "shared_ranges_le5"
            )
            self.assertGreater((output / f"{stem}.png").stat().st_size, 1_000)
            audit = json.loads((output / f"{stem}.json").read_text())
            self.assertEqual(audit["selection_mode"], "bright_balanced")
            self.assertEqual(audit["minimum_observations"], 4)


if __name__ == "__main__":
    unittest.main()
