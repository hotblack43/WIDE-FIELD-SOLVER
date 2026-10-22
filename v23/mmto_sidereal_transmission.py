"""Same-sidereal-time exposure pairing and measured-point transmission deltas."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Sequence

import numpy as np
from astropy import units as u
from astropy.time import Time
from astropy.utils import iers

from .mmto_validation import MMTO_LONGITUDE_DEG


iers.conf.auto_download = False
iers.conf.auto_max_age = None


def apparent_sidereal_hours(midpoint_utc: str | datetime | Time) -> float:
    instant = midpoint_utc if isinstance(midpoint_utc, Time) else Time(midpoint_utc)
    return float(instant.sidereal_time("apparent", longitude=MMTO_LONGITUDE_DEG * u.deg).hour % 24.0)


def sidereal_separation_minutes(first_hours: float, second_hours: float) -> float:
    difference = abs((float(second_hours) - float(first_hours)) % 24.0)
    return min(difference, 24.0 - difference) * 60.0


@dataclass(frozen=True)
class Exposure:
    source_sha256: str
    night: str
    midpoint_utc: str
    apparent_sidereal_hours: float


@dataclass(frozen=True)
class ExposurePair:
    first: Exposure
    second: Exposure
    separation_minutes: float


def select_sidereal_pairs(exposures: Sequence[Exposure], *, tolerance_minutes: float = 5.0) -> tuple[ExposurePair, ...]:
    """Greedily take the closest deterministic distinct-night one-to-one pairs."""

    if tolerance_minutes < 0 or not math.isfinite(tolerance_minutes):
        raise ValueError("tolerance_minutes must be finite and non-negative")
    ordered = sorted(exposures, key=lambda item: (item.midpoint_utc, item.source_sha256))
    if len({item.source_sha256 for item in ordered}) != len(ordered):
        raise ValueError("exposure source digests must be unique")
    candidates = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if first.night == second.night:
                continue
            separation = sidereal_separation_minutes(first.apparent_sidereal_hours, second.apparent_sidereal_hours)
            if separation <= tolerance_minutes + 1e-9:
                candidates.append((separation, first.midpoint_utc, second.midpoint_utc, first.source_sha256, second.source_sha256, first, second))
    used: set[str] = set(); pairs = []
    for separation, _, _, _, _, first, second in sorted(candidates):
        if first.source_sha256 in used or second.source_sha256 in used:
            continue
        used.update((first.source_sha256, second.source_sha256))
        pairs.append(ExposurePair(first, second, separation))
    return tuple(pairs)


@dataclass(frozen=True)
class TransmissionMeasurement:
    star_key: tuple[str, str]
    channel: str
    corrected_magnitude: float
    x_px: float
    y_px: float


@dataclass(frozen=True)
class DifferentialRow:
    star_key: tuple[str, str]
    channel: str
    x_px: float
    y_px: float
    second_x_px: float
    second_y_px: float
    raw_difference_magnitude: float
    pair_grey_median_magnitude: float
    grey_centred_difference_magnitude: float
    status: str


@dataclass(frozen=True)
class DifferentialResult:
    rows: tuple[DifferentialRow, ...]
    status_by_channel: dict[str, str]
    common_count_by_channel: dict[str, int]


def differential_transmission(
    first: Sequence[TransmissionMeasurement], second: Sequence[TransmissionMeasurement],
    *, min_common_stars: int = 20,
) -> DifferentialResult:
    if min_common_stars < 1:
        raise ValueError("min_common_stars must be positive")
    first_map = {(row.channel, row.star_key): row for row in first}
    second_map = {(row.channel, row.star_key): row for row in second}
    if len(first_map) != len(first) or len(second_map) != len(second):
        raise ValueError("duplicate star/channel measurement")
    common = sorted(set(first_map) & set(second_map))
    by_channel: dict[str, list[tuple[tuple[str, str], float]]] = {}
    for channel, key in common:
        difference = second_map[(channel, key)].corrected_magnitude - first_map[(channel, key)].corrected_magnitude
        by_channel.setdefault(channel, []).append((key, float(difference)))
    rows = []; statuses = {}; counts = {}
    for channel in sorted(by_channel):
        values = by_channel[channel]
        median = float(np.median([difference for _, difference in values]))
        status = "accepted" if len(values) >= min_common_stars else "insufficient_coverage"
        statuses[channel] = status; counts[channel] = len(values)
        for key, difference in values:
            a = first_map[(channel, key)]; b = second_map[(channel, key)]
            rows.append(DifferentialRow(
                star_key=key, channel=channel, x_px=a.x_px, y_px=a.y_px,
                second_x_px=b.x_px, second_y_px=b.y_px,
                raw_difference_magnitude=difference,
                pair_grey_median_magnitude=median,
                grey_centred_difference_magnitude=difference - median,
                status=status,
            ))
    return DifferentialResult(tuple(rows), statuses, counts)
