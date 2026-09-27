import math
import unittest
from dataclasses import replace

from scripts.nightly_extinction import (
    CalibrationConfig,
    ImageZeroPoint,
    NightCalibrationResult,
    NightCoefficient,
    StarWeight,
    StellarMeasurement,
    calibrate_night,
    correct_magnitude,
    fit_image_ols,
    fit_image_robust,
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


def synthetic_night(
    image_count: int,
    *,
    slopes: list[float] | None = None,
    zero_points: list[float] | None = None,
    narrow_images: frozenset[int] = frozenset(),
) -> list[StellarMeasurement]:
    slopes = slopes or [0.10 + 0.01 * image for image in range(image_count)]
    zero_points = zero_points or [
        -6.2 + 0.04 * ((3 * image) % 7) for image in range(image_count)
    ]
    rows: list[StellarMeasurement] = []
    for image in range(image_count):
        for star in range(30):
            airmass = (
                1.2 + 0.2 * star / 29.0
                if image in narrow_images
                else 1.0 + 3.0 * star / 29.0
            )
            catalogue_magnitude = 2.0 + star / 100.0
            delta_magnitude = zero_points[image] + slopes[image] * airmass
            instrumental_magnitude = catalogue_magnitude + delta_magnitude
            rows.append(
                StellarMeasurement(
                    night="2026-09-25",
                    source_sha256=f"{image + 1:064x}",
                    catalogue_sha256=CATALOGUE_SHA,
                    star_id=f"night-star-{star:02d}",
                    channel="R",
                    catalogue_magnitude=catalogue_magnitude,
                    count_rate_adu_per_s=10.0
                    ** (-0.4 * instrumental_magnitude),
                    count_rate_uncertainty_adu_per_s=0.1,
                    airmass=airmass,
                    saturated=False,
                    measurement_method="ordinary_aperture",
                    observed_utc=f"2026-09-25T{image:02d}:00:00+00:00",
                )
            )
    return rows


def sensitivity_rows(
    *,
    star_prefix: str,
    catalogue_magnitude: float,
    minimum_airmass: float,
    maximum_airmass: float,
    intercept: float,
    slope: float,
) -> list[StellarMeasurement]:
    rows: list[StellarMeasurement] = []
    for image in range(10):
        for star in range(30):
            airmass = minimum_airmass + (maximum_airmass - minimum_airmass) * star / 29
            delta_magnitude = intercept + slope * airmass
            instrumental_magnitude = catalogue_magnitude + delta_magnitude
            rows.append(
                StellarMeasurement(
                    night="2026-09-25",
                    source_sha256=f"{image + 1:064x}",
                    catalogue_sha256=CATALOGUE_SHA,
                    star_id=f"{star_prefix}-{star:02d}",
                    channel="R",
                    catalogue_magnitude=catalogue_magnitude,
                    count_rate_adu_per_s=10.0
                    ** (-0.4 * instrumental_magnitude),
                    count_rate_uncertainty_adu_per_s=0.1,
                    airmass=airmass,
                    saturated=False,
                    measurement_method="ordinary_aperture",
                    observed_utc=f"2026-09-25T{image:02d}:00:00+00:00",
                )
            )
    return rows


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

    def test_image_robust_fit_resists_one_severe_photometric_outlier(self) -> None:
        rows = [fitted_measurement(i, 1.0 + 3.0 * i / 29.0) for i in range(30)]
        outlier = rows[-1]
        rows[-1] = replace(
            outlier,
            count_rate_adu_per_s=10.0
            ** (-0.4 * (outlier.machine_magnitude + 12.0)),
        )
        reference_ids = frozenset(row.star_key for row in rows)

        result = fit_image_robust(rows, reference_ids, CalibrationConfig())

        self.assertTrue(result.accepted)
        self.assertEqual(result.model, "reference_theil_sen")
        self.assertAlmostEqual(result.line.intercept, -6.0, places=12)
        self.assertAlmostEqual(result.line.slope, 0.24, places=12)
        self.assertEqual(result.line.sample_count, 30)

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

    def test_nightly_median_tracks_image_extinction_while_fixed_zero_points_track_transparency(
        self,
    ) -> None:
        slopes = [0.10 + 0.01 * image for image in range(10)]
        zero_points = [-6.2 + 0.04 * ((3 * image) % 7) for image in range(10)]

        result = calibrate_night(
            synthetic_night(10, slopes=slopes, zero_points=zero_points),
            CalibrationConfig(),
        )

        self.assertIsInstance(result, NightCalibrationResult)
        self.assertEqual(result.adopted_model, "reference_theil_sen")
        coefficient = result.night_coefficients[0]
        self.assertIsInstance(coefficient, NightCoefficient)
        self.assertEqual(coefficient.status, "accepted")
        self.assertAlmostEqual(coefficient.extinction_mag_per_airmass, 0.145, 12)
        self.assertEqual(coefficient.accepted_image_count, 10)
        self.assertAlmostEqual(coefficient.minimum, 0.10, 12)
        self.assertAlmostEqual(coefficient.maximum, 0.19, 12)

        zero_point_by_source = {
            item.source_sha256: item for item in result.image_zero_points
        }
        mean_airmass = 2.5
        for image, (slope, true_zero_point) in enumerate(
            zip(slopes, zero_points, strict=True)
        ):
            fitted = zero_point_by_source[f"{image + 1:064x}"]
            self.assertIsInstance(fitted, ImageZeroPoint)
            self.assertEqual(fitted.status, "accepted")
            expected = true_zero_point + (slope - 0.145) * mean_airmass
            self.assertAlmostEqual(fitted.zero_point_magnitude, expected, 12)

    def test_night_requires_ten_accepted_images_without_fallback(self) -> None:
        result = calibrate_night(
            synthetic_night(10, narrow_images=frozenset({9})),
            CalibrationConfig(),
        )

        coefficient = result.night_coefficients[0]
        self.assertEqual(coefficient.status, "insufficient_accepted_images")
        self.assertIsNone(coefficient.extinction_mag_per_airmass)
        self.assertEqual(coefficient.accepted_image_count, 9)
        self.assertTrue(result.image_fits)
        self.assertEqual(sum(fit.accepted for fit in result.image_fits), 9)
        self.assertTrue(result.image_zero_points)
        self.assertTrue(
            all(
                item.status == "missing_nightly_extinction"
                and item.zero_point_magnitude is None
                for item in result.image_zero_points
            )
        )

    def test_fixed_slope_zero_point_is_robust_to_one_bad_star(self) -> None:
        rows = synthetic_night(
            10,
            slopes=[0.2] * 10,
            zero_points=[-6.0] * 10,
        )
        contaminated = []
        for row in rows:
            if row.star_id == "night-star-29":
                row = replace(
                    row,
                    count_rate_adu_per_s=10.0
                    ** (-0.4 * (row.machine_magnitude + 12.0)),
                )
            contaminated.append(row)

        result = calibrate_night(contaminated, CalibrationConfig())

        self.assertEqual(result.adopted_model, "reference_theil_sen")
        self.assertTrue(result.image_zero_points)
        for zero_point in result.image_zero_points:
            self.assertAlmostEqual(zero_point.zero_point_magnitude, -6.0, 12)

    def test_unknown_intrinsic_object_is_corrected_from_stellar_solution(self) -> None:
        machine_mag = 7.35
        corrected = correct_magnitude(
            machine_mag,
            zero_point_mag=-6.1,
            extinction_mag_per_airmass=0.145,
            airmass=2.2,
        )
        self.assertAlmostEqual(corrected, 13.131, 12)

    def test_weighted_and_faint_sensitivities_never_replace_reference(self) -> None:
        reference_rows = synthetic_night(10)
        reference_only = calibrate_night(reference_rows, CalibrationConfig())
        with_faint = calibrate_night(
            reference_rows
            + sensitivity_rows(
                star_prefix="faint",
                catalogue_magnitude=4.5,
                minimum_airmass=1.0,
                maximum_airmass=4.0,
                intercept=-3.0,
                slope=2.0,
            ),
            CalibrationConfig(),
        )

        reference_coefficient = reference_only.night_coefficients[0]
        by_model = {item.model: item for item in with_faint.night_coefficients}
        self.assertEqual(with_faint.adopted_model, "reference_theil_sen")
        self.assertIn("reference_ols", by_model)
        self.assertIn("bright_weighted", by_model)
        self.assertIn("faint_weighted", by_model)
        self.assertAlmostEqual(
            by_model["reference_theil_sen"].extinction_mag_per_airmass,
            reference_coefficient.extinction_mag_per_airmass,
            12,
        )
        self.assertNotAlmostEqual(
            by_model["faint_weighted"].extinction_mag_per_airmass,
            by_model["reference_theil_sen"].extinction_mag_per_airmass,
            3,
        )
        reference_zeros = [
            item.zero_point_magnitude for item in reference_only.image_zero_points
        ]
        faint_zeros = [item.zero_point_magnitude for item in with_faint.image_zero_points]
        self.assertEqual(reference_zeros, faint_zeros)

    def test_weight_floor_and_cap_prevent_single_star_domination(self) -> None:
        config = CalibrationConfig()
        noisy_rows: list[StellarMeasurement] = []
        for row in synthetic_night(10):
            image = int(row.source_sha256, 16) - 1
            star = int(row.star_id.rsplit("-", 1)[1])
            noise = (
                0.12 if image % 2 else -0.12
            ) if star == 29 else 0.0
            new_machine_magnitude = row.machine_magnitude + noise
            noisy_rows.append(
                replace(
                    row,
                    count_rate_adu_per_s=10.0 ** (-0.4 * new_machine_magnitude),
                )
            )

        result = calibrate_night(noisy_rows, config)
        self.assertTrue(result.star_weights)
        self.assertTrue(all(isinstance(item, StarWeight) for item in result.star_weights))
        weights = [item.weight for item in result.star_weights]
        self.assertTrue(all(math.isfinite(value) and value > 0.0 for value in weights))
        self.assertLessEqual(max(weights), config.maximum_repeatability_weight)
        self.assertGreaterEqual(min(weights), config.minimum_repeatability_weight)
        stable = next(item for item in result.star_weights if item.star_id == "night-star-00")
        self.assertEqual(stable.weight, config.maximum_repeatability_weight)
        noisy = next(item for item in result.star_weights if item.star_id == "night-star-29")
        self.assertLess(noisy.weight, stable.weight)

    def test_full_airmass_fit_is_diagnostic_only(self) -> None:
        reference_rows = synthetic_night(10)
        reference_only = calibrate_night(reference_rows, CalibrationConfig())
        with_high_airmass = calibrate_night(
            reference_rows
            + sensitivity_rows(
                star_prefix="high-x",
                catalogue_magnitude=3.0,
                minimum_airmass=5.5,
                maximum_airmass=8.0,
                intercept=-3.0,
                slope=1.5,
            ),
            CalibrationConfig(),
        )

        by_model = {item.model: item for item in with_high_airmass.night_coefficients}
        self.assertIn("full_airmass_ols", by_model)
        self.assertAlmostEqual(
            by_model["reference_theil_sen"].extinction_mag_per_airmass,
            reference_only.night_coefficients[0].extinction_mag_per_airmass,
            12,
        )
        self.assertNotAlmostEqual(
            by_model["full_airmass_ols"].extinction_mag_per_airmass,
            by_model["reference_theil_sen"].extinction_mag_per_airmass,
            3,
        )
        self.assertEqual(with_high_airmass.adopted_model, "reference_theil_sen")


if __name__ == "__main__":
    unittest.main()
