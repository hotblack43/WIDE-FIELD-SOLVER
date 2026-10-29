from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Sequence

import numpy as np

from .types import AnonymousDirection


@dataclass(frozen=True)
class AnonymousObservation:
    object_id: str
    run_id: str
    source_sha256: str
    source_path: str
    night: str
    observation_time_utc: datetime
    ra_deg: float
    dec_deg: float
    sigma_ra_arcsec: float
    sigma_dec_arcsec: float


@dataclass(frozen=True)
class NightSplit:
    fit: tuple[AnonymousObservation, ...]
    withheld: tuple[AnonymousObservation, ...]
    fit_nights: tuple[str, ...]
    withheld_nights: tuple[str, ...]
    modulus: int


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid UTC exposure midpoint: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("exposure midpoint must include a UTC offset")
    return parsed.astimezone(UTC)


def directions_to_observations(
    directions: Sequence[AnonymousDirection],
) -> tuple[AnonymousObservation, ...]:
    output: list[AnonymousObservation] = []
    seen_runs: set[str] = set()
    for direction in directions:
        if direction.run_id in seen_runs:
            raise ValueError(f"duplicate anonymous run identifier: {direction.run_id}")
        unit = np.asarray(direction.icrs_unit, dtype=float)
        norm = float(np.linalg.norm(unit))
        if unit.shape != (3,) or not np.isfinite(unit).all() or not math.isclose(norm, 1.0, abs_tol=1e-10):
            raise ValueError("anonymous ICRS direction must be a unit 3-vector")
        ra_deg = math.degrees(math.atan2(float(unit[1]), float(unit[0]))) % 360.0
        dec_deg = math.degrees(math.asin(float(np.clip(unit[2], -1.0, 1.0))))
        sigma_arcsec = max(60.0, 60.0 * float(direction.stellar_fit_rms_arcmin))
        if not math.isfinite(sigma_arcsec):
            raise ValueError("anonymous direction uncertainty must be finite")
        output.append(AnonymousObservation(
            object_id=direction.object_id, run_id=direction.run_id,
            source_sha256=direction.source_sha256, source_path=direction.source_path,
            night=direction.night, observation_time_utc=_parse_utc(direction.observation_time_utc),
            ra_deg=ra_deg, dec_deg=dec_deg,
            sigma_ra_arcsec=sigma_arcsec, sigma_dec_arcsec=sigma_arcsec,
        ))
        seen_runs.add(direction.run_id)
    return tuple(sorted(output, key=lambda row: (row.observation_time_utc, row.run_id)))


def split_nights(
    observations: Sequence[AnonymousObservation], modulus: int = 5,
) -> NightSplit:
    if modulus < 2:
        raise ValueError("night withholding modulus must be at least two")
    nights = tuple(sorted({row.night for row in observations}))
    withheld_nights = tuple(night for index, night in enumerate(nights, start=1) if index % modulus == 0)
    withheld_set = set(withheld_nights)
    fit = tuple(row for row in observations if row.night not in withheld_set)
    withheld = tuple(row for row in observations if row.night in withheld_set)
    if {row.run_id for row in fit} & {row.run_id for row in withheld}:
        raise AssertionError("fit and withheld run identifiers overlap")
    return NightSplit(
        fit=fit, withheld=withheld,
        fit_nights=tuple(night for night in nights if night not in withheld_set),
        withheld_nights=withheld_nights, modulus=modulus,
    )
