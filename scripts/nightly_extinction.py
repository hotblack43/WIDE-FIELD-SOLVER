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

    clean_images: dict[StarKey, set[str]] = defaultdict(set)
    for row in measurements:
        if not reference_measurement_exclusion_reasons(row, config):
            clean_images[row.star_key].add(row.source_sha256)
    return frozenset(
        key
        for key, image_ids in clean_images.items()
        if len(image_ids) >= config.min_observations_per_star
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
