"""Earth-only heliocentric and MMTO topocentric observer states.

Longitude is degrees east (MMTO is negative/east-of-Greenwich convention),
latitude is geodetic north, and Cartesian axes follow the ICRS/BCRS-aligned
axes returned by ERFA and Astropy GCRS position/velocity routines.
"""

from __future__ import annotations

import math
from typing import Sequence

from astropy import units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy.utils import iers
import erfa
import numpy as np

from .types import AnonymousDirection, Observation, ObserverState


MMTO_LONGITUDE_DEG_EAST = -110.8841666667
MMTO_LATITUDE_DEG_NORTH = 31.6866666667
MMTO_ELEVATION_M = 2616.0
MMTO = EarthLocation.from_geodetic(
    lon=MMTO_LONGITUDE_DEG_EAST * u.deg,
    lat=MMTO_LATITUDE_DEG_NORTH * u.deg,
    height=MMTO_ELEVATION_M * u.m,
)

# Orbit fitting must be offline and reproducible.  Bundled IERS data suffice at
# the arcminute observational scale and avoid hidden network state.
iers.conf.auto_download = False


def _tuple3(values: np.ndarray) -> tuple[float, float, float]:
    array = np.asarray(values, dtype=float)
    if array.shape != (3,) or not np.isfinite(array).all():
        raise ValueError("observer state component must be a finite 3-vector")
    return tuple(float(value) for value in array)


def utc_midpoint_to_tdb_jd(value: str) -> float:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("exposure midpoint must be an explicit UTC timestamp ending in Z")
    try:
        time = Time(value, scale="utc")
    except Exception as error:
        raise ValueError(f"invalid UTC exposure midpoint: {value!r}") from error
    jd_tdb = float(time.tdb.jd)
    if not math.isfinite(jd_tdb):
        raise ValueError("TDB Julian date must be finite")
    return jd_tdb


def earth_heliocentric_state_epv00(jd_tdb: float) -> tuple[np.ndarray, np.ndarray]:
    if not math.isfinite(jd_tdb):
        raise ValueError("TDB Julian date must be finite")
    time = Time(jd_tdb, format="jd", scale="tdb")
    heliocentric, _ = erfa.epv00(time.jd1, time.jd2)
    return (
        np.asarray(heliocentric["p"], dtype=float).copy(),
        np.asarray(heliocentric["v"], dtype=float).copy(),
    )


def mmto_heliocentric_state(jd_tdb: float) -> ObserverState:
    time = Time(jd_tdb, format="jd", scale="tdb")
    earth_position, earth_velocity = earth_heliocentric_state_epv00(jd_tdb)
    topocentre_position, topocentre_velocity = MMTO.get_gcrs_posvel(time)
    topocentre_position_au = topocentre_position.xyz.to_value(u.au)
    topocentre_velocity_au_per_day = topocentre_velocity.xyz.to_value(u.au / u.day)
    position = earth_position + topocentre_position_au
    velocity = earth_velocity + topocentre_velocity_au_per_day
    return ObserverState(
        jd_tdb=float(jd_tdb),
        position_au=_tuple3(position),
        velocity_au_per_day=_tuple3(velocity),
        earth_position_au=_tuple3(earth_position),
        earth_velocity_au_per_day=_tuple3(earth_velocity),
        topocentre_position_au=_tuple3(topocentre_position_au),
        topocentre_velocity_au_per_day=_tuple3(topocentre_velocity_au_per_day),
    )


def build_observations(
    directions: Sequence[AnonymousDirection],
) -> list[Observation]:
    observations: list[Observation] = []
    for direction in directions:
        measured = np.asarray(direction.icrs_unit, dtype=float)
        if measured.shape != (3,) or not np.isfinite(measured).all():
            raise ValueError("measured ICRS direction must be a finite 3-vector")
        if not math.isclose(float(np.linalg.norm(measured)), 1.0, abs_tol=1e-12):
            raise ValueError("measured ICRS direction must have unit norm")
        jd_tdb = utc_midpoint_to_tdb_jd(direction.observation_time_utc)
        observations.append(
            Observation(
                direction=direction,
                jd_tdb=jd_tdb,
                measured_unit=_tuple3(measured),
                sigma_arcmin=max(1.0, float(direction.stellar_fit_rms_arcmin)),
                observer=mmto_heliocentric_state(jd_tdb),
            )
        )
    return observations
