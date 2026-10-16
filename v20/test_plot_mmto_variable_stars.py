"""Tests for v20 chronological variable-star products."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from v20.scripts.plot_mmto_variable_stars import (
    PlotPoint,
    StarSeries,
    generate_products,
    make_time_series_page,
)


UTC = timezone.utc
CROSSMATCH_FIELDS = (
    "catalogue_filename", "catalogue_sha256", "star_id",
    "local_ra_j2000_deg", "local_dec_j2000_deg", "vsx_oid", "vsx_name",
    "vsx_flag", "vsx_type", "period_days", "vsx_ra_j2000_deg",
    "vsx_dec_j2000_deg", "match_distance_arcsec", "candidate_oid_count",
    "selection_status",
)
CORRECTED_FIELDS = (
    "night", "channel", "observed_utc", "source_sha256",
    "catalogue_sha256", "star_id", "catalogue_magnitude",
    "count_rate_adu_per_s", "machine_magnitude", "airmass",
    "extinction_mag_per_airmass", "nightly_scaled_mad_mag_per_airmass",
    "zero_point_magnitude", "zero_point_uncertainty_magnitude",
    "corrected_magnitude", "status",
)


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _crossmatch_row(star_id: str, oid: str, period: object, *, flag: str = "0", catalogue: str = "cat-a") -> dict[str, object]:
    return {
        "catalogue_filename": "stars.csv", "catalogue_sha256": catalogue,
        "star_id": star_id, "local_ra_j2000_deg": "1", "local_dec_j2000_deg": "2",
        "vsx_oid": oid, "vsx_name": f"Variable {oid}", "vsx_flag": flag,
        "vsx_type": "EA", "period_days": period, "vsx_ra_j2000_deg": "1",
        "vsx_dec_j2000_deg": "2", "match_distance_arcsec": "0.2",
        "candidate_oid_count": "1", "selection_status": "eligible_catalogue_variable" if flag == "0" else "vsx_flag_not_confirmed_variable",
    }


def _measurement(
    star_id: str,
    observed: str,
    channel: str = "G",
    corrected: object = "1.25",
    *,
    catalogue: str = "cat-a",
    status: str = "accepted",
    catalogue_magnitude: object = "4.5",
) -> dict[str, object]:
    return {
        "night": observed[:10], "channel": channel, "observed_utc": observed,
        "source_sha256": f"source-{star_id}-{channel}-{observed}",
        "catalogue_sha256": catalogue, "star_id": star_id,
        "catalogue_magnitude": catalogue_magnitude, "count_rate_adu_per_s": "100",
        "machine_magnitude": "-5.0", "airmass": "1.4",
        "extinction_mag_per_airmass": "0.2",
        "nightly_scaled_mad_mag_per_airmass": "0.01",
        "zero_point_magnitude": "9999", "zero_point_uncertainty_magnitude": "0.02",
        "corrected_magnitude": corrected, "status": status,
    }


class ProductFixture:
    def __init__(self, root: Path, crossmatch: list[dict[str, object]], measurements: list[dict[str, object]]):
        self.crossmatch = root / "vsx.csv"
        self.provenance = root / "vsx.json"
        self.corrected = root / "corrected.csv"
        self.output = root / "output"
        _write_csv(self.crossmatch, CROSSMATCH_FIELDS, crossmatch)
        _write_csv(self.corrected, CORRECTED_FIELDS, measurements)
        self.provenance.write_text(json.dumps({
            "catalogue": "VSX fixture", "catalogue_version": "test",
            "match_radius_arcsec": 1.0,
            "output_csv_sha256": hashlib.sha256(self.crossmatch.read_bytes()).hexdigest(),
        }))

    def generate(self, **kwargs: object) -> dict[str, object]:
        return generate_products(
            self.corrected, self.crossmatch, self.provenance, self.output, **kwargs
        )


class VariableStarSelectionTests(unittest.TestCase):
    def test_same_night_measurements_are_flux_averaged_into_one_point(self):
        measurements = [
            _measurement("star", "2026-08-01T01:00:00Z", "G", "0"),
            _measurement("star", "2026-08-01T03:00:00Z", "G", "5"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(
                Path(temporary),
                [_crossmatch_row("star", "1", "10")],
                measurements,
            )
            summary = fixture.generate()
            with (fixture.output / "variable_star_measurements.csv").open() as source:
                plotted = list(csv.DictReader(source))

        self.assertEqual(len(plotted), 1)
        self.assertEqual(plotted[0]["night"], "2026-08-01")
        self.assertEqual(plotted[0]["observed_utc"], "2026-08-01T02:00:00Z")
        self.assertEqual(plotted[0]["channel"], "G")
        self.assertEqual(plotted[0]["contributing_measurement_count"], "2")
        self.assertAlmostEqual(
            float(plotted[0]["flux_averaged_corrected_magnitude"]),
            0.7417715547033465,
            places=12,
        )
        self.assertEqual(summary["plotted_point_count"], 1)
        self.assertEqual(summary["contributing_measurement_count"], 2)

    def test_preserves_corrected_values_rgb_and_chronological_order(self):
        crossmatch = [
            _crossmatch_row("TYC 1", "101", "12.5"),
            _crossmatch_row("Gaia 1", "101", "12.5", catalogue="cat-b"),
        ]
        measurements = [
            _measurement("TYC 1", "2026-08-03T00:00:00Z", "B", "1.23456789"),
            _measurement("TYC 1", "2026-08-01T00:00:00Z", "R", "2.5"),
            _measurement("Gaia 1", "2026-08-02T00:00:00Z", "G", "3.5", catalogue="cat-b"),
            _measurement("TYC 1", "2026-03-15T00:00:00Z", "R", "4.5"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(Path(temporary), crossmatch, measurements)
            summary = fixture.generate()
            with (fixture.output / "variable_star_measurements.csv").open() as source:
                plotted = list(csv.DictReader(source))
            with (fixture.output / "variable_star_measurement_audit.csv").open() as source:
                audit = list(csv.DictReader(source))

        self.assertEqual(summary["selected_star_count"], 1)
        self.assertEqual([row["channel"] for row in plotted], ["R", "G", "B"])
        self.assertAlmostEqual(
            float(plotted[-1]["flux_averaged_corrected_magnitude"]),
            1.23456789,
            places=12,
        )
        self.assertEqual({row["channel"] for row in plotted}, {"R", "G", "B"})
        march = [row for row in audit if row["observed_utc"].startswith("2026-03")]
        self.assertEqual(march[0]["plot_status"], "excluded")
        self.assertEqual(march[0]["exclusion_reason"], "before_start_utc")

    def test_period_boundary_and_flag_are_strict(self):
        periods = ("5", "5.001", "29.999", "30", "nan", "inf")
        crossmatch = [
            _crossmatch_row(f"star-{index}", str(index), period)
            for index, period in enumerate(periods)
        ]
        crossmatch.append(_crossmatch_row("suspected", "99", "10", flag="1"))
        measurements = [
            _measurement(row["star_id"], "2026-08-01T00:00:00Z")
            for row in crossmatch
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(Path(temporary), crossmatch, measurements)
            summary = fixture.generate()

        self.assertEqual(summary["selected_star_count"], 2)
        self.assertEqual(summary["plotted_point_count"], 2)
        self.assertEqual(summary["min_period_days_exclusive"], 5.0)
        self.assertEqual(summary["max_period_days_exclusive"], 30.0)

    def test_catalogue_magnitude_must_be_strictly_brighter_than_five(self):
        crossmatch = [
            _crossmatch_row("bright", "1", "10"),
            _crossmatch_row("boundary", "2", "10"),
        ]
        measurements = [
            _measurement(
                "bright", "2026-08-01T00:00:00Z",
                catalogue_magnitude="4.999",
            ),
            _measurement(
                "boundary", "2026-08-01T00:00:00Z",
                catalogue_magnitude="5.0",
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(Path(temporary), crossmatch, measurements)
            summary = fixture.generate()
            with (fixture.output / "variable_star_measurement_audit.csv").open() as source:
                audit = list(csv.DictReader(source))

        self.assertEqual(summary["selected_star_count"], 1)
        self.assertEqual(summary["max_catalogue_magnitude_exclusive"], 5.0)
        boundary = [row for row in audit if row["star_id"] == "boundary"]
        self.assertEqual(boundary[0]["plot_status"], "excluded")
        self.assertEqual(
            boundary[0]["exclusion_reason"],
            "catalogue_magnitude_not_brighter_than_limit",
        )

    def test_malformed_or_naive_utc_fails_explicitly(self):
        for observed in ("not-a-time", "2026-08-01T00:00:00"):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as temporary:
                fixture = ProductFixture(
                    Path(temporary),
                    [_crossmatch_row("star", "1", "10")],
                    [_measurement("star", observed)],
                )
                with self.assertRaisesRegex(ValueError, "timezone|observation time"):
                    fixture.generate()


class VariableStarOutputTests(unittest.TestCase):
    def test_fixed_period_sine_fit_recovers_brightest_phase(self):
        corrected_magnitudes = (
            "2.0",
            "1.6464466094067263",
            "1.5",
            "1.6464466094067263",
            "2.0",
            "2.353553390593274",
            "2.5",
            "2.353553390593274",
        )
        measurements = [
            _measurement(
                "star",
                f"2026-08-{day:02d}T00:00:00Z",
                "G",
                magnitude,
            )
            for day, magnitude in enumerate(corrected_magnitudes, 1)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(
                Path(temporary),
                [_crossmatch_row("star", "1", "8")],
                measurements,
            )
            summary = fixture.generate()
            fit_path = fixture.output / "variable_star_sine_fits.csv"
            self.assertTrue(fit_path.is_file())
            with fit_path.open() as source:
                fits = list(csv.DictReader(source))

        self.assertEqual(len(fits), 1)
        fit = fits[0]
        self.assertEqual(fit["status"], "fitted")
        self.assertEqual(fit["channel"], "G")
        self.assertEqual(fit["nightly_point_count"], "8")
        self.assertEqual(fit["reference_utc"], "2026-08-01T00:00:00Z")
        self.assertAlmostEqual(float(fit["phase_offset_cycles_brightest"]), 0.25, places=12)
        self.assertAlmostEqual(float(fit["phase_offset_days_brightest"]), 2.0, places=12)
        self.assertEqual(fit["brightest_epoch_utc"], "2026-08-03T00:00:00Z")
        self.assertAlmostEqual(float(fit["mean_corrected_magnitude"]), 2.0, places=12)
        self.assertAlmostEqual(float(fit["semi_amplitude_magnitude"]), 0.5, places=12)
        self.assertAlmostEqual(float(fit["rms_magnitude"]), 0.0, places=12)
        self.assertEqual(summary["fitted_channel_count"], 1)

    def test_fixed_period_sine_fit_audits_fewer_than_three_nights(self):
        measurements = [
            _measurement("star", "2026-08-01T00:00:00Z", "R", "1.0"),
            _measurement("star", "2026-08-02T00:00:00Z", "R", "2.0"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(
                Path(temporary),
                [_crossmatch_row("star", "1", "8")],
                measurements,
            )
            summary = fixture.generate()
            with (fixture.output / "variable_star_sine_fits.csv").open() as source:
                fits = list(csv.DictReader(source))

        self.assertEqual(fits[0]["status"], "insufficient_nightly_points")
        self.assertEqual(fits[0]["phase_offset_cycles_brightest"], "")
        self.assertEqual(summary["fitted_channel_count"], 0)

    def test_fixed_period_sine_fit_audits_repeated_identical_phases(self):
        measurements = [
            _measurement("star", observed, "B", "2.0")
            for observed in (
                "2026-08-01T00:00:00Z",
                "2026-08-09T00:00:00Z",
                "2026-08-17T00:00:00Z",
            )
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(
                Path(temporary),
                [_crossmatch_row("star", "1", "8")],
                measurements,
            )
            fixture.generate()
            with (fixture.output / "variable_star_sine_fits.csv").open() as source:
                fits = list(csv.DictReader(source))

        self.assertEqual(fits[0]["status"], "insufficient_independent_phases")
        self.assertEqual(fits[0]["phase_offset_cycles_brightest"], "")

    def test_page_has_four_by_three_inverted_magnitude_panels(self):
        series = [
            StarSeries(
                vsx_oid=str(index), vsx_name=f"Star {index}", vsx_type="EA",
                period_days=float(index + 1),
                points=(PlotPoint(datetime(2026, 8, 1, tzinfo=UTC), "G", 2.0, "s", "c", "id"),),
            )
            for index in range(12)
        ]

        figure = make_time_series_page(series)

        self.assertEqual(len(figure.axes), 12)
        grid = figure.axes[0].get_subplotspec().get_gridspec()
        self.assertEqual((grid.nrows, grid.ncols), (4, 3))
        self.assertTrue(all(axis.yaxis_inverted() for axis in figure.axes))
        title = figure._suptitle.get_text()
        self.assertIn("nightly flux-averaged", title)
        self.assertIn("5 < P < 30 d", title)
        self.assertIn("catalogue mag < 5", title)

    def test_page_overlays_fixed_period_sine_and_labels_brightest_phase(self):
        points = tuple(
            PlotPoint(
                datetime(2026, 8, day, tzinfo=UTC),
                "R",
                magnitude,
                f"source-{day}",
                "catalogue",
                "star",
            )
            for day, magnitude in ((1, 2.0), (3, 1.5), (5, 2.0), (7, 2.5))
        )
        series = [StarSeries(
            vsx_oid="1", vsx_name="Sine", vsx_type="ACV", period_days=8.0,
            points=points,
        )]

        figure = make_time_series_page(series)

        self.assertEqual(len(figure.axes[0].lines), 1)
        self.assertEqual(figure.axes[0].lines[0].get_color(), "#d62728")
        annotations = [text.get_text() for text in figure.axes[0].texts]
        self.assertIn("bright phase: R=0.250", annotations)
        self.assertIn("solid curves: fixed-period sine fits", figure._suptitle.get_text())

    def test_single_timestamp_panel_uses_two_day_window_not_multiple_years(self):
        series = [StarSeries(
            vsx_oid="1", vsx_name="Sparse", vsx_type="EA", period_days=2.0,
            points=(PlotPoint(datetime(2026, 8, 1, tzinfo=UTC), "G", 2.0, "s", "c", "id"),),
        )]

        figure = make_time_series_page(series)
        minimum, maximum = figure.axes[0].get_xlim()

        self.assertLessEqual(maximum - minimum, 2.01)

    def test_thirteen_objects_make_two_pages_without_dropping_stars(self):
        crossmatch = [_crossmatch_row(f"star-{i}", str(i), str(i + 6)) for i in range(13)]
        measurements = [
            _measurement(f"star-{i}", "2026-08-01T00:00:00Z") for i in range(13)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(Path(temporary), crossmatch, measurements)
            summary = fixture.generate()
            pdf_info = subprocess.run(
                ["pdfinfo", str(fixture.output / "variable_star_time_series.pdf")],
                check=True, text=True, stdout=subprocess.PIPE,
            ).stdout

        self.assertEqual(summary["selected_star_count"], 13)
        self.assertEqual(summary["page_count"], 2)
        self.assertIn("Pages:           2", pdf_info)

    def test_empty_selection_writes_schema_valid_explanatory_products(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(
                Path(temporary),
                [_crossmatch_row("star", "1", "30")],
                [_measurement("star", "2026-08-01T00:00:00Z")],
            )
            summary = fixture.generate()
            with (fixture.output / "variable_star_measurements.csv").open() as source:
                rows = list(csv.DictReader(source))
            pdf = fixture.output / "variable_star_time_series.pdf"
            pdf_size = pdf.stat().st_size

        self.assertEqual(summary["selected_star_count"], 0)
        self.assertEqual(summary["page_count"], 1)
        self.assertEqual(rows, [])
        self.assertGreater(pdf_size, 0)

    def test_summary_hashes_outputs_and_refuses_nonempty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductFixture(
                Path(temporary),
                [_crossmatch_row("star", "1", "10")],
                [_measurement("star", "2026-08-01T00:00:00Z")],
            )
            summary = fixture.generate()
            self.assertEqual(
                summary["inputs"]["corrected_csv_sha256"],
                hashlib.sha256(fixture.corrected.read_bytes()).hexdigest(),
            )
            self.assertIn("variable_star_time_series.pdf", summary["output_sha256"])
            with self.assertRaises(FileExistsError):
                fixture.generate()


if __name__ == "__main__":
    unittest.main()
