"""Planet colour-colour plots use matched, fully corrected RGB measurements."""
from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest


class PlanetColourPlotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _write_channel(self, channel, rows):
        path = self.root / channel / "planet_extinction_corrected_distance_measurements.csv"
        path.parent.mkdir(parents=True)
        fields = [
            "run_id", "source_sha256", "observation_time_utc", "camera_label",
            "planet", "detection_id", "channel", "machine_magnitude",
            "extinction_corrected_magnitude",
            "extinction_corrected_distance_magnitude", "hours_past_local_noon",
        ]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({**row, "channel": channel})
        return path

    def test_writes_b_minus_g_against_b_minus_r_from_matched_corrected_rows(self):
        from scripts import plot_planet_colours as colours

        common = [
            {
                "run_id": "run-mars", "source_sha256": "a" * 64,
                "observation_time_utc": "2026-09-20T01:00:00Z",
                "camera_label": "MMTO skycam", "planet": "Mars",
                "detection_id": "4", "hours_past_local_noon": "6.0",
            },
            {
                "run_id": "run-saturn", "source_sha256": "b" * 64,
                "observation_time_utc": "2026-09-20T03:00:00Z",
                "camera_label": "MMTO skycam", "planet": "Saturn",
                "detection_id": "7", "hours_past_local_noon": "8.0",
            },
        ]
        corrected = {
            "R": ((99.0, 9.0, 1.0), (98.0, 8.0, 2.5)),
            "G": ((88.0, 8.0, 2.5), (87.0, 7.0, 4.0)),
            "B": ((77.0, 7.0, 4.0), (76.0, 6.0, 6.0)),
        }
        paths = {}
        for channel in "RGB":
            rows = []
            for base, values in zip(common, corrected[channel]):
                machine, extinction_only, fully_corrected = values
                rows.append({
                    **base,
                    "machine_magnitude": machine,
                    "extinction_corrected_magnitude": extinction_only,
                    "extinction_corrected_distance_magnitude": fully_corrected,
                })
            paths[channel] = self._write_channel(channel, rows)

        rows = colours.load_colour_measurements(paths)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["planet"], "Mars")
        self.assertAlmostEqual(rows[0]["b_minus_g"], 1.5, 12)
        self.assertAlmostEqual(rows[0]["b_minus_r"], 3.0, 12)
        self.assertAlmostEqual(rows[1]["b_minus_g"], 2.0, 12)
        self.assertAlmostEqual(rows[1]["b_minus_r"], 3.5, 12)

        output = self.root / "output"
        summary = colours.write_outputs(rows, output)

        self.assertEqual(summary["measurement_count"], 2)
        self.assertEqual(summary["planets"], ["Mars", "Saturn"])
        self.assertTrue((output / "planet_colour_colour.png").is_file())
        self.assertFalse((output / "planet_colour_colour.pdf").exists())
        with (output / "planet_colour_colour.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual(
            [(float(row["b_minus_g"]), float(row["b_minus_r"])) for row in exported],
            [(1.5, 3.0), (2.0, 3.5)],
        )

        figure, axis = colours.build_figure(rows)
        self.addCleanup(figure.clear)
        self.assertEqual(axis.get_xlabel(), "B − G [mag]")
        self.assertEqual(axis.get_ylabel(), "B − R [mag]")
        self.assertEqual(len(axis.collections), 2)
        self.assertNotEqual(
            axis.collections[0].get_paths()[0].vertices.tolist(),
            axis.collections[1].get_paths()[0].vertices.tolist(),
        )
        self.assertIn("Hours past latest local noon", figure.axes[1].get_ylabel())
        self.assertLess(axis.get_xlim()[0], 1.5)
        self.assertGreater(axis.get_xlim()[1], 2.0)
        self.assertLess(axis.get_ylim()[0], 3.0)
        self.assertGreater(axis.get_ylim()[1], 3.5)

    def test_omits_measurements_without_all_three_corrected_channels(self):
        from scripts import plot_planet_colours as colours

        base = {
            "run_id": "run", "source_sha256": "c" * 64,
            "observation_time_utc": "2026-09-20T01:00:00Z",
            "camera_label": "MMTO skycam", "planet": "Mars",
            "detection_id": "4", "hours_past_local_noon": "6.0",
            "machine_magnitude": "99", "extinction_corrected_magnitude": "9",
            "extinction_corrected_distance_magnitude": "1",
        }
        paths = {
            channel: self._write_channel(channel, [base] if channel != "G" else [])
            for channel in "RGB"
        }

        self.assertEqual(colours.load_colour_measurements(paths), [])


if __name__ == "__main__":
    unittest.main()
