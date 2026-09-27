import math
import unittest

from scripts.nightly_extinction import (
    CalibrationConfig,
    StellarMeasurement,
    fit_image_ols,
    machine_magnitude,
    select_reference_star_ids,
)


CATALOGUE_SHA = "c" * 64


def measurement(
    image_number: int,
    *,
    star_id: str = "star-1",
    channel: str = "R",
    catalogue_magnitude: float = 3.0,
    saturated: bool = False,
    measurement_method: str = "ordinary_aperture",
) -> StellarMeasurement:
    return StellarMeasurement(
        night="2026-09-25",
        source_sha256=f"{image_number:064x}",
        catalogue_sha256=CATALOGUE_SHA,
        star_id=star_id,
        channel=channel,
        catalogue_magnitude=catalogue_magnitude,
        count_rate_adu_per_s=100.0 + image_number,
        count_rate_uncertainty_adu_per_s=1.0,
        airmass=1.0 + 0.15 * image_number,
        saturated=saturated,
        measurement_method=measurement_method,
        observed_utc=f"2026-09-25T{image_number:02d}:00:00+00:00",
    )


def fitted_measurement(index: int, airmass: float) -> StellarMeasurement:
    catalogue_magnitude = 3.0
    delta_magnitude = -6.0 + 0.24 * airmass
    instrumental_magnitude = catalogue_magnitude + delta_magnitude
    return StellarMeasurement(
        night="2026-09-25",
        source_sha256="a" * 64,
        catalogue_sha256=CATALOGUE_SHA,
        star_id=f"fit-star-{index:02d}",
        channel="R",
        catalogue_magnitude=catalogue_magnitude,
        count_rate_adu_per_s=10.0 ** (-0.4 * instrumental_magnitude),
        count_rate_uncertainty_adu_per_s=0.1,
        airmass=airmass,
        saturated=False,
        measurement_method="ordinary_aperture",
        observed_utc="2026-09-25T05:00:00+00:00",
    )


class NightlyExtinctionModelTests(unittest.TestCase):
    def test_machine_magnitude_uses_count_rate_not_flux(self) -> None:
        self.assertAlmostEqual(machine_magnitude(100.0), -5.0, places=12)
        self.assertAlmostEqual(machine_magnitude(10.0), -2.5, places=12)
        with self.assertRaises(ValueError):
            machine_magnitude(0.0)
        with self.assertRaises(ValueError):
            machine_magnitude(math.nan)

    def test_reference_selection_requires_ten_clean_bright_observations(self) -> None:
        config = CalibrationConfig()
        self.assertEqual(config.max_catalogue_magnitude, 4.0)
        self.assertEqual(config.min_observations_per_star, 10)
        self.assertEqual(config.max_reference_airmass, 5.0)
        self.assertEqual(config.min_stars_per_image, 30)
        self.assertEqual(config.min_airmass_span, 1.0)
        self.assertEqual(config.min_images_per_night, 10)

        rows = [measurement(i, star_id="accepted") for i in range(10)]
        rows.extend(measurement(i, star_id="only-nine") for i in range(9))
        rows.extend(
            measurement(i, star_id="boundary", catalogue_magnitude=4.0)
            for i in range(10)
        )
        selected = select_reference_star_ids(rows, config)
        self.assertEqual(selected, frozenset({(CATALOGUE_SHA, "accepted")}))

    def test_channel_saturation_excludes_only_that_channel(self) -> None:
        config = CalibrationConfig()
        r_rows = [measurement(i, channel="R") for i in range(10)]
        g_rows = [measurement(i, channel="G", saturated=True) for i in range(10)]

        self.assertEqual(
            select_reference_star_ids(r_rows, config),
            frozenset({(CATALOGUE_SHA, "star-1")}),
        )
        self.assertEqual(select_reference_star_ids(g_rows, config), frozenset())

    def test_image_ols_recovers_known_intercept_and_slope(self) -> None:
        rows = [fitted_measurement(i, 1.0 + 3.0 * i / 29.0) for i in range(30)]
        reference_ids = frozenset(row.star_key for row in rows)

        result = fit_image_ols(rows, reference_ids, CalibrationConfig())

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.line.status, "accepted")
        self.assertAlmostEqual(result.line.intercept, -6.0, places=12)
        self.assertAlmostEqual(result.line.slope, 0.24, places=12)
        self.assertEqual(result.line.sample_count, 30)
        self.assertAlmostEqual(result.line.airmass_span, 3.0, places=12)
        self.assertEqual(len(result.line.residuals), 30)
        self.assertIsNotNone(result.line.covariance)

    def test_image_ols_reports_insufficient_count_and_airmass_span(self) -> None:
        count_rows = [
            fitted_measurement(i, 1.0 + 3.0 * i / 28.0) for i in range(29)
        ]
        count_result = fit_image_ols(
            count_rows,
            frozenset(row.star_key for row in count_rows),
            CalibrationConfig(),
        )
        self.assertFalse(count_result.accepted)
        self.assertEqual(count_result.status, "insufficient_reference_stars")
        self.assertEqual(count_result.line.status, "insufficient_reference_stars")
        self.assertEqual(count_result.line.sample_count, 29)

        span_rows = [
            fitted_measurement(i, 1.0 + 0.5 * i / 29.0) for i in range(30)
        ]
        span_result = fit_image_ols(
            span_rows,
            frozenset(row.star_key for row in span_rows),
            CalibrationConfig(),
        )
        self.assertFalse(span_result.accepted)
        self.assertEqual(span_result.status, "insufficient_airmass_span")
        self.assertEqual(span_result.line.status, "insufficient_airmass_span")
        self.assertEqual(span_result.line.sample_count, 30)


if __name__ == "__main__":
    unittest.main()
