"""Pure numerical model for catalogue-referenced nightly extinction fits.

The module has no database or filesystem dependencies.  Loaders are responsible
for retaining rejected input rows and their audit reasons; objects accepted as
``StellarMeasurement`` instances are immutable, finite measurements.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import AbstractSet

import numpy as np


StarKey = tuple[str, str]


@dataclass(frozen=True)
class CalibrationConfig:
    max_catalogue_magnitude: float = 4.0
    min_observations_per_star: int = 10
    max_reference_airmass: float = 5.0
    min_stars_per_image: int = 30
    min_airmass_span: float = 1.0
    min_images_per_night: int = 10
    minimum_repeatability_weight: float = 1.0
    maximum_repeatability_weight: float = 10_000.0


@dataclass(frozen=True)
class StellarMeasurement:
    night: str
    source_sha256: str
    catalogue_sha256: str
    star_id: str
    channel: str
    catalogue_magnitude: float
    count_rate_adu_per_s: float
    count_rate_uncertainty_adu_per_s: float | None
    airmass: float
    saturated: bool
    measurement_method: str
    observed_utc: str

    def __post_init__(self) -> None:
        required_text = {
            "night": self.night,
            "source_sha256": self.source_sha256,
            "catalogue_sha256": self.catalogue_sha256,
            "star_id": self.star_id,
            "channel": self.channel,
            "measurement_method": self.measurement_method,
            "observed_utc": self.observed_utc,
        }
        for name, value in required_text.items():
            if not value:
                raise ValueError(f"{name} must be present")
        for name, value in (
            ("catalogue_magnitude", self.catalogue_magnitude),
            ("count_rate_adu_per_s", self.count_rate_adu_per_s),
            ("airmass", self.airmass),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.count_rate_adu_per_s <= 0.0:
            raise ValueError("count_rate_adu_per_s must be positive")
        if self.airmass <= 0.0:
            raise ValueError("airmass must be positive")
        if self.count_rate_uncertainty_adu_per_s is not None:
            if not math.isfinite(self.count_rate_uncertainty_adu_per_s):
                raise ValueError("count_rate_uncertainty_adu_per_s must be finite")
            if self.count_rate_uncertainty_adu_per_s <= 0.0:
                raise ValueError("count_rate_uncertainty_adu_per_s must be positive")

    @property
    def star_key(self) -> StarKey:
        return self.catalogue_sha256, self.star_id

    @property
    def machine_magnitude(self) -> float:
        return machine_magnitude(self.count_rate_adu_per_s)

    @property
    def delta_magnitude(self) -> float:
        return self.machine_magnitude - self.catalogue_magnitude


@dataclass(frozen=True)
class LineFit:
    status: str
    intercept: float | None
    slope: float | None
    covariance: tuple[tuple[float, float], tuple[float, float]] | None
    intercept_uncertainty: float | None
    slope_uncertainty: float | None
    rms: float | None
    residuals: tuple[float, ...]
    sample_count: int
    airmass_min: float | None
    airmass_max: float | None
    airmass_span: float | None


@dataclass(frozen=True)
class ImageFit:
    night: str
    source_sha256: str
    catalogue_sha256: str
    channel: str
    model: str
    status: str
    accepted: bool
    line: LineFit
    star_keys: tuple[StarKey, ...]


@dataclass(frozen=True)
class NightCoefficient:
    night: str
    catalogue_sha256: str
    channel: str
    model: str
    status: str
    extinction_mag_per_airmass: float | None
    scaled_mad: float | None
    minimum: float | None
    maximum: float | None
    accepted_image_count: int


@dataclass(frozen=True)
class ImageZeroPoint:
    night: str
    source_sha256: str
    catalogue_sha256: str
    channel: str
    model: str
    status: str
    zero_point_magnitude: float | None
    uncertainty_magnitude: float | None
    rms_magnitude: float | None
    sample_count: int
    extinction_mag_per_airmass: float | None


@dataclass(frozen=True)
class StarWeight:
    night: str
    catalogue_sha256: str
    star_id: str
    channel: str
    residual_scatter_magnitude: float
    clipped_scatter_magnitude: float
    weight: float
    observation_count: int


@dataclass(frozen=True)
class NightCalibrationResult:
    adopted_model: str
    image_fits: tuple[ImageFit, ...]
    sensitivity_image_fits: tuple[ImageFit, ...]
    night_coefficients: tuple[NightCoefficient, ...]
    image_zero_points: tuple[ImageZeroPoint, ...]
    star_weights: tuple[StarWeight, ...]


def machine_magnitude(count_rate_adu_per_s: float) -> float:
    """Return instrumental magnitude from a positive count rate."""

    if not math.isfinite(count_rate_adu_per_s) or count_rate_adu_per_s <= 0.0:
        raise ValueError("count_rate_adu_per_s must be positive and finite")
    return -2.5 * math.log10(count_rate_adu_per_s)


def reference_measurement_exclusion_reasons(
    measurement: StellarMeasurement,
    config: CalibrationConfig,
) -> tuple[str, ...]:
    """Return measurement-level reasons that exclude a reference observation."""

    reasons: list[str] = []
    if measurement.catalogue_magnitude >= config.max_catalogue_magnitude:
        reasons.append("catalogue_magnitude_not_bright")
    if measurement.saturated:
        reasons.append("channel_saturated")
    if measurement.measurement_method != "ordinary_aperture":
        reasons.append("not_ordinary_aperture")
    return tuple(reasons)


def _is_clean_channel_measurement(measurement: StellarMeasurement) -> bool:
    return not measurement.saturated and measurement.measurement_method == "ordinary_aperture"


def _select_star_ids_below_magnitude(
    measurements: Sequence[StellarMeasurement],
    config: CalibrationConfig,
    magnitude_limit: float,
) -> frozenset[StarKey]:
    clean_images: dict[StarKey, set[str]] = defaultdict(set)
    for row in measurements:
        if row.catalogue_magnitude >= magnitude_limit:
            continue
        if _is_clean_channel_measurement(row):
            clean_images[row.star_key].add(row.source_sha256)
    return frozenset(
        key
        for key, image_ids in clean_images.items()
        if len(image_ids) >= config.min_observations_per_star
    )


def select_reference_star_ids(
    measurements: Sequence[StellarMeasurement],
    config: CalibrationConfig,
) -> frozenset[StarKey]:
    """Select repeatably measured bright stars for one night and one channel."""

    if not measurements:
        return frozenset()
    nights = {row.night for row in measurements}
    channels = {row.channel for row in measurements}
    if len(nights) != 1 or len(channels) != 1:
        raise ValueError("reference selection requires one night and one channel")

    return _select_star_ids_below_magnitude(
        measurements,
        config,
        config.max_catalogue_magnitude,
    )


def fit_image_ols(
    measurements: Sequence[StellarMeasurement],
    reference_star_ids: AbstractSet[StarKey],
    config: CalibrationConfig,
    *,
    model: str = "reference_ols",
) -> ImageFit:
    """Fit ``delta_m = Z + k X`` for one image and channel."""

    if not measurements:
        raise ValueError("image fit requires at least one measurement")
    identity = {
        (row.night, row.source_sha256, row.catalogue_sha256, row.channel)
        for row in measurements
    }
    if len(identity) != 1:
        raise ValueError("image fit requires one night, image, catalogue, and channel")
    night, source_sha256, catalogue_sha256, channel = next(iter(identity))

    eligible_by_star: dict[StarKey, StellarMeasurement] = {}
    for row in measurements:
        if row.star_key not in reference_star_ids:
            continue
        if reference_measurement_exclusion_reasons(row, config):
            continue
        maximum_airmass = (
            math.inf if model == "full_airmass_ols" else config.max_reference_airmass
        )
        if row.airmass > maximum_airmass:
            continue
        eligible_by_star.setdefault(row.star_key, row)
    rows = [eligible_by_star[key] for key in sorted(eligible_by_star)]
    star_keys = tuple(row.star_key for row in rows)
    airmass = np.asarray([row.airmass for row in rows], dtype=float)
    sample_count = len(rows)
    airmass_min = float(np.min(airmass)) if sample_count else None
    airmass_max = float(np.max(airmass)) if sample_count else None
    airmass_span = (
        airmass_max - airmass_min
        if airmass_min is not None and airmass_max is not None
        else None
    )

    if sample_count < config.min_stars_per_image:
        status = "insufficient_reference_stars"
    elif airmass_span is None or airmass_span < config.min_airmass_span:
        status = "insufficient_airmass_span"
    else:
        status = "accepted"

    if status != "accepted":
        line = LineFit(
            status=status,
            intercept=None,
            slope=None,
            covariance=None,
            intercept_uncertainty=None,
            slope_uncertainty=None,
            rms=None,
            residuals=(),
            sample_count=sample_count,
            airmass_min=airmass_min,
            airmass_max=airmass_max,
            airmass_span=airmass_span,
        )
    else:
        delta_magnitude = np.asarray(
            [row.delta_magnitude for row in rows], dtype=float
        )
        design = np.column_stack((np.ones(sample_count, dtype=float), airmass))
        coefficients, _, rank, _ = np.linalg.lstsq(
            design, delta_magnitude, rcond=None
        )
        if rank != 2:
            raise ValueError("accepted image fit unexpectedly has rank below two")
        residual_array = delta_magnitude - design @ coefficients
        degrees_of_freedom = sample_count - 2
        residual_variance = float(
            np.dot(residual_array, residual_array) / degrees_of_freedom
        )
        covariance_array = residual_variance * np.linalg.inv(design.T @ design)
        intercept_uncertainty, slope_uncertainty = np.sqrt(
            np.maximum(np.diag(covariance_array), 0.0)
        )
        line = LineFit(
            status=status,
            intercept=float(coefficients[0]),
            slope=float(coefficients[1]),
            covariance=(
                (float(covariance_array[0, 0]), float(covariance_array[0, 1])),
                (float(covariance_array[1, 0]), float(covariance_array[1, 1])),
            ),
            intercept_uncertainty=float(intercept_uncertainty),
            slope_uncertainty=float(slope_uncertainty),
            rms=float(np.sqrt(np.mean(np.square(residual_array)))),
            residuals=tuple(float(value) for value in residual_array),
            sample_count=sample_count,
            airmass_min=airmass_min,
            airmass_max=airmass_max,
            airmass_span=airmass_span,
        )

    return ImageFit(
        night=night,
        source_sha256=source_sha256,
        catalogue_sha256=catalogue_sha256,
        channel=channel,
        model=model,
        status=status,
        accepted=status == "accepted",
        line=line,
        star_keys=star_keys,
    )


def _fit_image_weighted(
    measurements: Sequence[StellarMeasurement],
    star_ids: AbstractSet[StarKey],
    weights: dict[StarKey, float],
    config: CalibrationConfig,
    *,
    model: str,
) -> ImageFit:
    if not measurements:
        raise ValueError("image fit requires at least one measurement")
    identity = {
        (row.night, row.source_sha256, row.catalogue_sha256, row.channel)
        for row in measurements
    }
    if len(identity) != 1:
        raise ValueError("image fit requires one night, image, catalogue, and channel")
    night, source_sha256, catalogue_sha256, channel = next(iter(identity))

    eligible_by_star: dict[StarKey, StellarMeasurement] = {}
    for row in measurements:
        if row.star_key not in star_ids or row.star_key not in weights:
            continue
        if not _is_clean_channel_measurement(row):
            continue
        if row.airmass > config.max_reference_airmass:
            continue
        eligible_by_star.setdefault(row.star_key, row)
    rows = [eligible_by_star[key] for key in sorted(eligible_by_star)]
    star_keys = tuple(row.star_key for row in rows)
    airmass = np.asarray([row.airmass for row in rows], dtype=float)
    sample_count = len(rows)
    airmass_min = float(np.min(airmass)) if sample_count else None
    airmass_max = float(np.max(airmass)) if sample_count else None
    airmass_span = (
        airmass_max - airmass_min
        if airmass_min is not None and airmass_max is not None
        else None
    )
    if sample_count < config.min_stars_per_image:
        status = "insufficient_reference_stars"
    elif airmass_span is None or airmass_span < config.min_airmass_span:
        status = "insufficient_airmass_span"
    else:
        status = "accepted"

    if status != "accepted":
        line = LineFit(
            status=status,
            intercept=None,
            slope=None,
            covariance=None,
            intercept_uncertainty=None,
            slope_uncertainty=None,
            rms=None,
            residuals=(),
            sample_count=sample_count,
            airmass_min=airmass_min,
            airmass_max=airmass_max,
            airmass_span=airmass_span,
        )
    else:
        delta_magnitude = np.asarray(
            [row.delta_magnitude for row in rows], dtype=float
        )
        weight_array = np.asarray([weights[row.star_key] for row in rows], dtype=float)
        design = np.column_stack((np.ones(sample_count, dtype=float), airmass))
        root_weight = np.sqrt(weight_array)
        weighted_design = design * root_weight[:, np.newaxis]
        weighted_values = delta_magnitude * root_weight
        coefficients, _, rank, _ = np.linalg.lstsq(
            weighted_design, weighted_values, rcond=None
        )
        if rank != 2:
            raise ValueError("accepted weighted fit unexpectedly has rank below two")
        residual_array = delta_magnitude - design @ coefficients
        degrees_of_freedom = sample_count - 2
        weighted_variance = float(
            np.dot(weight_array, np.square(residual_array)) / degrees_of_freedom
        )
        covariance_array = weighted_variance * np.linalg.inv(
            design.T @ (weight_array[:, np.newaxis] * design)
        )
        intercept_uncertainty, slope_uncertainty = np.sqrt(
            np.maximum(np.diag(covariance_array), 0.0)
        )
        line = LineFit(
            status=status,
            intercept=float(coefficients[0]),
            slope=float(coefficients[1]),
            covariance=(
                (float(covariance_array[0, 0]), float(covariance_array[0, 1])),
                (float(covariance_array[1, 0]), float(covariance_array[1, 1])),
            ),
            intercept_uncertainty=float(intercept_uncertainty),
            slope_uncertainty=float(slope_uncertainty),
            rms=float(np.sqrt(np.mean(np.square(residual_array)))),
            residuals=tuple(float(value) for value in residual_array),
            sample_count=sample_count,
            airmass_min=airmass_min,
            airmass_max=airmass_max,
            airmass_span=airmass_span,
        )
    return ImageFit(
        night=night,
        source_sha256=source_sha256,
        catalogue_sha256=catalogue_sha256,
        channel=channel,
        model=model,
        status=status,
        accepted=status == "accepted",
        line=line,
        star_keys=star_keys,
    )


def _scaled_mad(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    median = float(np.median(values))
    return 1.4826 * float(np.median(np.abs(values - median)))


def _night_coefficient_from_fits(
    *,
    night: str,
    catalogue_sha256: str,
    channel: str,
    model: str,
    image_fits: Sequence[ImageFit],
    config: CalibrationConfig,
) -> NightCoefficient:
    accepted = [fit for fit in image_fits if fit.accepted]
    slopes = np.asarray(
        [fit.line.slope for fit in accepted if fit.line.slope is not None],
        dtype=float,
    )
    enough_images = len(accepted) >= config.min_images_per_night
    return NightCoefficient(
        night=night,
        catalogue_sha256=catalogue_sha256,
        channel=channel,
        model=model,
        status="accepted" if enough_images else "insufficient_accepted_images",
        extinction_mag_per_airmass=float(np.median(slopes)) if enough_images else None,
        scaled_mad=_scaled_mad(slopes),
        minimum=float(np.min(slopes)) if slopes.size else None,
        maximum=float(np.max(slopes)) if slopes.size else None,
        accepted_image_count=len(accepted),
    )


def _derive_repeatability_weights(
    measurements: Sequence[StellarMeasurement],
    sensitivity_star_ids: AbstractSet[StarKey],
    reference_fits: Sequence[ImageFit],
    config: CalibrationConfig,
) -> tuple[StarWeight, ...]:
    fit_by_source = {
        fit.source_sha256: fit
        for fit in reference_fits
        if fit.accepted and fit.line.intercept is not None and fit.line.slope is not None
    }
    residuals_by_star: dict[StarKey, list[float]] = defaultdict(list)
    identity_by_star: dict[StarKey, StellarMeasurement] = {}
    for row in measurements:
        fit = fit_by_source.get(row.source_sha256)
        if fit is None or row.star_key not in sensitivity_star_ids:
            continue
        if not _is_clean_channel_measurement(row):
            continue
        if row.airmass > config.max_reference_airmass:
            continue
        predicted = fit.line.intercept + fit.line.slope * row.airmass
        residuals_by_star[row.star_key].append(row.delta_magnitude - predicted)
        identity_by_star.setdefault(row.star_key, row)

    star_weights: list[StarWeight] = []
    for star_key in sorted(residuals_by_star):
        residuals = np.asarray(residuals_by_star[star_key], dtype=float)
        centred = residuals - np.median(residuals)
        scatter = _scaled_mad(centred)
        raw_scatter = float(scatter) if scatter is not None else 0.0
        if raw_scatter <= 0.0:
            raw_weight = math.inf
        else:
            raw_weight = 1.0 / (raw_scatter * raw_scatter)
        weight = min(
            config.maximum_repeatability_weight,
            max(config.minimum_repeatability_weight, raw_weight),
        )
        row = identity_by_star[star_key]
        star_weights.append(
            StarWeight(
                night=row.night,
                catalogue_sha256=row.catalogue_sha256,
                star_id=row.star_id,
                channel=row.channel,
                residual_scatter_magnitude=raw_scatter,
                clipped_scatter_magnitude=1.0 / math.sqrt(weight),
                weight=weight,
                observation_count=len(residuals),
            )
        )
    return tuple(star_weights)


def _fixed_slope_zero_point(
    rows: Sequence[StellarMeasurement],
    reference_star_ids: AbstractSet[StarKey],
    config: CalibrationConfig,
    coefficient: NightCoefficient,
) -> ImageZeroPoint:
    first = rows[0]
    if coefficient.extinction_mag_per_airmass is None:
        return ImageZeroPoint(
            night=first.night,
            source_sha256=first.source_sha256,
            catalogue_sha256=first.catalogue_sha256,
            channel=first.channel,
            model=coefficient.model,
            status="missing_nightly_extinction",
            zero_point_magnitude=None,
            uncertainty_magnitude=None,
            rms_magnitude=None,
            sample_count=0,
            extinction_mag_per_airmass=None,
        )

    eligible_by_star: dict[StarKey, StellarMeasurement] = {}
    for row in rows:
        if row.star_key not in reference_star_ids:
            continue
        if reference_measurement_exclusion_reasons(row, config):
            continue
        if row.airmass > config.max_reference_airmass:
            continue
        eligible_by_star.setdefault(row.star_key, row)
    eligible = [eligible_by_star[key] for key in sorted(eligible_by_star)]
    if len(eligible) < config.min_stars_per_image:
        return ImageZeroPoint(
            night=first.night,
            source_sha256=first.source_sha256,
            catalogue_sha256=first.catalogue_sha256,
            channel=first.channel,
            model=coefficient.model,
            status="insufficient_reference_stars",
            zero_point_magnitude=None,
            uncertainty_magnitude=None,
            rms_magnitude=None,
            sample_count=len(eligible),
            extinction_mag_per_airmass=coefficient.extinction_mag_per_airmass,
        )

    offsets = np.asarray(
        [
            row.delta_magnitude
            - coefficient.extinction_mag_per_airmass * row.airmass
            for row in eligible
        ],
        dtype=float,
    )
    zero_point = float(np.mean(offsets))
    residuals = offsets - zero_point
    rms = float(np.sqrt(np.mean(np.square(residuals))))
    if len(eligible) > 1:
        uncertainty = float(np.std(residuals, ddof=1) / math.sqrt(len(eligible)))
    else:  # unreachable with the adopted defaults, but explicit for custom configs
        uncertainty = None
    return ImageZeroPoint(
        night=first.night,
        source_sha256=first.source_sha256,
        catalogue_sha256=first.catalogue_sha256,
        channel=first.channel,
        model=coefficient.model,
        status="accepted",
        zero_point_magnitude=zero_point,
        uncertainty_magnitude=uncertainty,
        rms_magnitude=rms,
        sample_count=len(eligible),
        extinction_mag_per_airmass=coefficient.extinction_mag_per_airmass,
    )


def calibrate_night(
    measurements: Sequence[StellarMeasurement],
    config: CalibrationConfig,
) -> NightCalibrationResult:
    """Calibrate each catalogue/channel group in one observing night."""

    if not measurements:
        raise ValueError("night calibration requires at least one measurement")
    nights = {row.night for row in measurements}
    if len(nights) != 1:
        raise ValueError("calibrate_night requires exactly one observing night")

    grouped: dict[
        tuple[str, str, str], list[StellarMeasurement]
    ] = defaultdict(list)
    for row in measurements:
        grouped[(row.night, row.catalogue_sha256, row.channel)].append(row)

    all_image_fits: list[ImageFit] = []
    all_sensitivity_fits: list[ImageFit] = []
    coefficients: list[NightCoefficient] = []
    zero_points: list[ImageZeroPoint] = []
    all_star_weights: list[StarWeight] = []
    for (night, catalogue_sha256, channel), group_rows in sorted(grouped.items()):
        reference_ids = select_reference_star_ids(group_rows, config)
        sensitivity_ids = _select_star_ids_below_magnitude(
            group_rows, config, 5.0
        )
        by_image: dict[str, list[StellarMeasurement]] = defaultdict(list)
        for row in group_rows:
            by_image[row.source_sha256].append(row)
        image_fits = [
            fit_image_ols(by_image[source], reference_ids, config)
            for source in sorted(by_image)
        ]
        all_image_fits.extend(image_fits)
        coefficient = _night_coefficient_from_fits(
            night=night,
            catalogue_sha256=catalogue_sha256,
            channel=channel,
            model="reference_ols",
            image_fits=image_fits,
            config=config,
        )
        coefficients.append(coefficient)

        star_weights = _derive_repeatability_weights(
            group_rows, sensitivity_ids, image_fits, config
        )
        all_star_weights.extend(star_weights)
        weight_by_star = {
            (item.catalogue_sha256, item.star_id): item.weight
            for item in star_weights
        }
        bright_weighted = [
            _fit_image_weighted(
                by_image[source],
                reference_ids,
                weight_by_star,
                config,
                model="bright_weighted",
            )
            for source in sorted(by_image)
        ]
        faint_weighted = [
            _fit_image_weighted(
                by_image[source],
                sensitivity_ids,
                weight_by_star,
                config,
                model="faint_weighted",
            )
            for source in sorted(by_image)
        ]
        full_airmass = [
            fit_image_ols(
                by_image[source],
                reference_ids,
                config,
                model="full_airmass_ols",
            )
            for source in sorted(by_image)
        ]
        for model, fits in (
            ("bright_weighted", bright_weighted),
            ("faint_weighted", faint_weighted),
            ("full_airmass_ols", full_airmass),
        ):
            all_sensitivity_fits.extend(fits)
            coefficients.append(
                _night_coefficient_from_fits(
                    night=night,
                    catalogue_sha256=catalogue_sha256,
                    channel=channel,
                    model=model,
                    image_fits=fits,
                    config=config,
                )
            )

        zero_points.extend(
            _fixed_slope_zero_point(
                by_image[source], reference_ids, config, coefficient
            )
            for source in sorted(by_image)
        )

    return NightCalibrationResult(
        adopted_model="reference_ols",
        image_fits=tuple(all_image_fits),
        sensitivity_image_fits=tuple(all_sensitivity_fits),
        night_coefficients=tuple(coefficients),
        image_zero_points=tuple(zero_points),
        star_weights=tuple(all_star_weights),
    )


def correct_magnitude(
    machine_mag: float,
    zero_point_mag: float,
    extinction_mag_per_airmass: float,
    airmass: float,
) -> float:
    """Apply a stellar-derived zero point and nightly extinction coefficient."""

    values = (machine_mag, zero_point_mag, extinction_mag_per_airmass, airmass)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("magnitude correction inputs must be finite")
    if airmass <= 0.0:
        raise ValueError("airmass must be positive")
    return machine_mag - zero_point_mag - extinction_mag_per_airmass * airmass
