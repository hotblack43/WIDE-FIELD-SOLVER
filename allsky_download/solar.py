from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

import astropy.units as u
from astropy.coordinates import (
    AltAz,
    EarthLocation,
    get_body,
    get_sun,
    solar_system_ephemeris,
)
from astropy.time import Time

from .model import Candidate, Site


def _earth_location(site: Site, *, purpose: str = "solar-altitude") -> EarthLocation:
    if site.latitude_deg is None or site.longitude_deg is None:
        raise ValueError(
            f"{purpose} filtering requires latitude and longitude for "
            f"{site.source_id}/{site.camera_id}"
        )
    return EarthLocation.from_geodetic(
        lon=site.longitude_deg * u.deg,
        lat=site.latitude_deg * u.deg,
        height=(site.elevation_m or 0.0) * u.m,
    )


def validate_solar_site(site: Site) -> None:
    """Fail unless a site has enough metadata for solar-altitude filtering."""
    _earth_location(site)


def validate_moon_site(site: Site) -> None:
    """Fail unless a site has enough metadata for Moon-altitude filtering."""
    _earth_location(site, purpose="moon-down")


def solar_altitude_deg(site: Site, observed_at: datetime) -> float:
    """Return the geometric altitude of the Sun's centre at a site."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("solar-altitude time must be timezone-aware")
    instant = Time(observed_at)
    frame = AltAz(obstime=instant, location=_earth_location(site), pressure=0 * u.hPa)
    return float(get_sun(instant).transform_to(frame).alt.to_value(u.deg))


def moon_altitude_deg(site: Site, observed_at: datetime) -> float:
    """Return the topocentric geometric altitude of the Moon's centre."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("moon-altitude time must be timezone-aware")
    instant = Time(observed_at)
    location = _earth_location(site, purpose="moon-down")
    frame = AltAz(obstime=instant, location=location, pressure=0 * u.hPa)
    with solar_system_ephemeris.set("builtin"):
        moon = get_body("moon", instant, location)
    return float(moon.transform_to(frame).alt.to_value(u.deg))


def filter_by_solar_altitude(
    candidates: Iterable[Candidate],
    sites: Mapping[tuple[str, str], Site],
    *,
    sun_below_deg: float,
) -> tuple[Candidate, ...]:
    """Keep candidates for which the geometric solar altitude is below a limit."""
    items = tuple(candidates)
    grouped: dict[tuple[str, str], list[int]] = {}
    for index, candidate in enumerate(items):
        key = (candidate.source_id, candidate.camera_id)
        grouped.setdefault(key, []).append(index)

    keep = [False] * len(items)
    for key, indices in grouped.items():
        try:
            site = sites[key]
        except KeyError as exc:
            raise ValueError(
                f"no site metadata for {key[0]}/{key[1]}"
            ) from exc
        instants = Time([items[index].observed_at for index in indices])
        frame = AltAz(
            obstime=instants,
            location=_earth_location(site),
            pressure=0 * u.hPa,
        )
        altitudes = get_sun(instants).transform_to(frame).alt.to_value(u.deg)
        for index, altitude in zip(indices, altitudes, strict=True):
            keep[index] = float(altitude) < sun_below_deg
    return tuple(item for item, retained in zip(items, keep, strict=True) if retained)


def filter_by_moon_altitude(
    candidates: Iterable[Candidate],
    sites: Mapping[tuple[str, str], Site],
) -> tuple[Candidate, ...]:
    """Keep candidates with the Moon's geometric centre below the horizon."""
    items = tuple(candidates)
    grouped: dict[tuple[str, str], list[int]] = {}
    for index, candidate in enumerate(items):
        key = (candidate.source_id, candidate.camera_id)
        grouped.setdefault(key, []).append(index)

    keep = [False] * len(items)
    for key, indices in grouped.items():
        try:
            site = sites[key]
        except KeyError as exc:
            raise ValueError(
                f"no site metadata for {key[0]}/{key[1]}"
            ) from exc
        location = _earth_location(site, purpose="moon-down")
        instants = Time([items[index].observed_at for index in indices])
        frame = AltAz(
            obstime=instants,
            location=location,
            pressure=0 * u.hPa,
        )
        with solar_system_ephemeris.set("builtin"):
            moon = get_body("moon", instants, location)
        altitudes = moon.transform_to(frame).alt.to_value(u.deg)
        for index, altitude in zip(indices, altitudes, strict=True):
            keep[index] = float(altitude) < 0.0
    return tuple(item for item, retained in zip(items, keep, strict=True) if retained)
