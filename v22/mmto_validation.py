"""Post-fit MMTO site/time checks that never alter the blind solution."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, FK5, ICRS, SkyCoord
from astropy.time import Time
from astropy.utils import iers


MMTO_LATITUDE_DEG = 31.6866666667
MMTO_LONGITUDE_DEG = -110.8841666667
MMTO_ELEVATION_M = 2616.0

iers.conf.auto_download = False
iers.conf.auto_max_age = None


def _time(value: datetime | str | Time) -> Time:
    return value if isinstance(value, Time) else Time(value)


def mmto_location() -> EarthLocation:
    return EarthLocation.from_geodetic(
        lon=MMTO_LONGITUDE_DEG * u.deg,
        lat=MMTO_LATITUDE_DEG * u.deg,
        height=MMTO_ELEVATION_M * u.m,
    )


def known_zenith_unit_vector(midpoint_utc: datetime | str | Time) -> np.ndarray:
    """Return the mean-equator/equinox zenith direction transformed to ICRS."""

    instant = _time(midpoint_utc)
    equinox = Time(instant.jyear, format="jyear")
    zenith = SkyCoord(
        ra=instant.sidereal_time("mean", longitude=MMTO_LONGITUDE_DEG * u.deg),
        dec=MMTO_LATITUDE_DEG * u.deg,
        frame=FK5(equinox=equinox),
    ).transform_to(ICRS())
    vector = np.asarray(zenith.cartesian.xyz.value, dtype=float)
    return vector / np.linalg.norm(vector)


def validate_blind_zenith(
    blind_unit_vector: Any, midpoint_utc: datetime | str | Time
) -> dict[str, float | bool | str]:
    vector = np.asarray(blind_unit_vector, dtype=float)
    if vector.shape != (3,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-12:
        raise ValueError("blind zenith must be a finite three-dimensional vector")
    vector /= np.linalg.norm(vector)
    instant = _time(midpoint_utc)
    predicted = known_zenith_unit_vector(instant)
    separation = math.degrees(math.acos(float(np.clip(vector @ predicted, -1.0, 1.0))))
    blind = SkyCoord(
        x=vector[0], y=vector[1], z=vector[2],
        representation_type="cartesian", frame=ICRS(),
    ).transform_to(FK5(equinox=Time(instant.jyear, format="jyear")))
    latitude = float(blind.spherical.lat.deg)
    return {
        "used_in_fit": False,
        "validation_stage": "post_blind_fit",
        "known_latitude_deg": MMTO_LATITUDE_DEG,
        "known_longitude_deg": MMTO_LONGITUDE_DEG,
        "known_elevation_m": MMTO_ELEVATION_M,
        "derived_latitude_deg": latitude,
        "latitude_minus_known_deg": latitude - MMTO_LATITUDE_DEG,
        "zenith_separation_deg": separation,
        "known_zenith_x": float(predicted[0]),
        "known_zenith_y": float(predicted[1]),
        "known_zenith_z": float(predicted[2]),
    }


def _kasten_young_airmass(altitude_deg: float) -> float | None:
    if not math.isfinite(altitude_deg) or altitude_deg < 0.0 or altitude_deg > 90.0:
        return None
    z = 90.0 - altitude_deg
    return 1.0 / (math.cos(math.radians(z)) + 0.50572 * (96.07995 - z) ** -1.6364)


def known_airmass(
    ra_deg: float, dec_deg: float, midpoint_utc: datetime | str | Time
) -> dict[str, float | None | bool | str]:
    instant = _time(midpoint_utc)
    coordinate = SkyCoord(ra=float(ra_deg) * u.deg, dec=float(dec_deg) * u.deg, frame=ICRS())
    apparent = coordinate.transform_to(
        AltAz(obstime=instant, location=mmto_location(), pressure=0 * u.hPa)
    )
    altitude = float(apparent.alt.deg)
    vector = known_zenith_unit_vector(instant)
    zenith = SkyCoord(
        x=vector[0], y=vector[1], z=vector[2],
        representation_type="cartesian", frame=ICRS(),
    )
    refraction_direction = float(coordinate.position_angle(zenith).to_value(u.deg))
    return {
        "used_in_fit": False,
        "validation_stage": "post_blind_fit",
        "altitude_deg": altitude,
        "airmass": _kasten_young_airmass(altitude),
        "parallactic_angle_deg": refraction_direction,
        "refraction_toward_zenith_position_angle_deg": refraction_direction,
    }


def stellar_epoch_comparison(
    fitted_jyear: float | None, midpoint_utc: datetime | str | Time
) -> dict[str, float | bool | str | None]:
    if fitted_jyear is None or not math.isfinite(float(fitted_jyear)):
        return {
            "used_in_fit": False,
            "validation_stage": "post_blind_fit",
            "stellar_epoch_jyear": None,
            "stellar_minus_header_years": None,
            "absolute_difference_days": None,
        }
    fitted = Time(float(fitted_jyear), format="jyear")
    header = _time(midpoint_utc)
    delta_days = float((fitted.tdb - header.tdb).to_value(u.day))
    return {
        "used_in_fit": False,
        "validation_stage": "post_blind_fit",
        "stellar_epoch_jyear": float(fitted_jyear),
        "stellar_minus_header_years": float(fitted.jyear - header.jyear),
        "absolute_difference_days": abs(delta_days),
    }


def planet_epoch_comparison(
    planet_record: dict[str, Any], midpoint_utc: datetime | str | Time
) -> list[dict[str, Any]]:
    """Compare saved blind candidates with the header time without reranking them."""

    preserved = deepcopy(planet_record)
    header = _time(midpoint_utc).tdb
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(preserved.get("candidates") or (), 1):
        jd = candidate.get("jd_tdb")
        if jd is None:
            try:
                candidate_time = Time(str(candidate.get("epoch_tdb", "")).replace(" TDB", ""), scale="tdb")
            except (TypeError, ValueError):
                offset = None
            else:
                offset = float((candidate_time - header).to_value(u.s))
        else:
            try:
                offset = float((Time(float(jd), format="jd", scale="tdb") - header).to_value(u.s))
            except (TypeError, ValueError):
                offset = None
        rows.append({
            "candidate_rank": rank,
            "blind_status": preserved.get("status"),
            "blind_metadata_used": bool(preserved.get("metadata_used", False)),
            "candidate_epoch_tdb": candidate.get("epoch_tdb"),
            "candidate_jd_tdb": jd,
            "planet_minus_header_seconds": offset,
            "absolute_difference_seconds": abs(offset) if offset is not None else None,
            "match_count": candidate.get("match_count"),
            "rms_arcmin": candidate.get("rms_arcmin"),
            "used_in_fit": False,
            "selection_changed": False,
            "validation_stage": "post_blind_fit",
        })
    return rows
