"""Authoritative observation timing for known MMTO Skywatch FITS headers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from astropy.io import fits


UTC = timezone.utc
ARIZONA = ZoneInfo("America/Phoenix")
MMTO_LATITUDE_DEG = 31.6866666667
MMTO_LONGITUDE_DEG = -110.8841666667
MMTO_ELEVATION_M = 2616.0
MMTO_INSTRUMENT = "ZWO ASI294MC Pro"
CLOCK_TOLERANCE_SECONDS = 0.1
CREATION_LAG_LIMIT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class MMTOObservation:
    start_utc: datetime
    midpoint_utc: datetime
    exposure_seconds: float
    schema: str
    provenance: str
    instrument: str

    def __post_init__(self) -> None:
        for name, value in (
            ("start_utc", self.start_utc),
            ("midpoint_utc", self.midpoint_utc),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not math.isfinite(self.exposure_seconds) or self.exposure_seconds <= 0:
            raise ValueError("exposure_seconds must be positive and finite")


def _sexagesimal(value: object) -> float:
    parts = str(value).strip().split(":")
    if len(parts) != 4 or float(parts[3]) != 0.0:
        raise ValueError(f"unrecognised MMTO coordinate format: {value!r}")
    sign = -1.0 if parts[0].startswith("-") else 1.0
    return sign * (
        abs(float(parts[0])) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0
    )


def _datetime(value: object, *, default_timezone) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone)
    return parsed.astimezone(UTC)


def _exposure_seconds(header: fits.Header) -> float:
    if float(header.get("STACKNB", 1)) != 1.0:
        raise ValueError("stacked MMTO exposure duration is not established")
    value = header.get("EXPOSURE", header.get("EXPTIME"))
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("missing or invalid exposure duration") from exc
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise ValueError("missing or invalid exposure duration")
    return seconds


def _validate_camera(header: fits.Header) -> str:
    instrument = str(header.get("INSTRUME", "")).strip()
    if re.fullmatch(r"ZWO ASI294MC Pro(?: \(\d+\))?", instrument) is None:
        raise ValueError(f"unrecognised MMTO instrument: {instrument!r}")
    for key, expected in (
        ("SITELAT", MMTO_LATITUDE_DEG),
        ("SITELONG", MMTO_LONGITUDE_DEG),
    ):
        if key not in header or abs(_sexagesimal(header[key]) - expected) > 0.0001:
            raise ValueError(f"{key} differs from verified MMTO site")
    return instrument


def _clock_seconds(value: object) -> float:
    parsed = time.fromisoformat(str(value).strip())
    if parsed.tzinfo is not None:
        raise ValueError("UT clock unexpectedly includes a timezone")
    return (
        parsed.hour * 3600.0
        + parsed.minute * 60.0
        + parsed.second
        + parsed.microsecond / 1_000_000.0
    )


def _circular_clock_difference(first: float, second: float) -> float:
    difference = abs(first - second) % 86400.0
    return min(difference, 86400.0 - difference)


def _old_observation(
    header: fits.Header, exposure_seconds: float, instrument: str
) -> MMTOObservation:
    if "UT" not in header or "DATE" not in header:
        raise ValueError("old MMTO header requires UT and DATE clock checks")
    raw_start = str(header["DATE-OBS"]).strip()
    parsed_local = datetime.fromisoformat(raw_start)
    if parsed_local.tzinfo is not None:
        raise ValueError("old MMTO DATE-OBS must be a naive Arizona-local clock")
    date_clock = (
        parsed_local.hour * 3600.0
        + parsed_local.minute * 60.0
        + parsed_local.second
        + parsed_local.microsecond / 1_000_000.0
    )
    if _circular_clock_difference(date_clock, _clock_seconds(header["UT"])) > CLOCK_TOLERANCE_SECONDS:
        raise ValueError("UT disagrees with local DATE-OBS")
    start = parsed_local.replace(tzinfo=ARIZONA).astimezone(UTC)
    end = start + timedelta(seconds=exposure_seconds)
    created = _datetime(header["DATE"], default_timezone=UTC)
    lag = (created - end).total_seconds()
    if not 0.0 <= lag <= CREATION_LAG_LIMIT_SECONDS:
        raise ValueError(
            "DATE disagrees with local DATE-OBS and exposure duration: "
            f"post-exposure lag {lag:.3f}s"
        )
    return MMTOObservation(
        start_utc=start,
        midpoint_utc=start + timedelta(seconds=exposure_seconds / 2.0),
        exposure_seconds=exposure_seconds,
        schema="mmto_skywatch_local_date_obs",
        provenance=(
            "FITS DATE-OBS and UT interpreted as America/Phoenix exposure start; "
            "cross-checked against UTC FITS DATE; midpoint=start+EXPTIME/2"
        ),
        instrument=instrument,
    )


def _new_observation(
    header: fits.Header, exposure_seconds: float, instrument: str
) -> MMTOObservation:
    if "DATE-END" not in header or "DATE-OBS" not in header:
        raise ValueError("new MMTO header requires DATE-END and local DATE-OBS checks")
    start = _datetime(header["DATE-BEG"], default_timezone=UTC)
    end = _datetime(header["DATE-END"], default_timezone=UTC)
    expected_end = start + timedelta(seconds=exposure_seconds)
    if abs((end - expected_end).total_seconds()) > CLOCK_TOLERANCE_SECONDS:
        raise ValueError("DATE-END disagrees with DATE-BEG plus exposure duration")
    raw_local = datetime.fromisoformat(str(header["DATE-OBS"]).strip())
    if raw_local.tzinfo is not None:
        raise ValueError("new MMTO DATE-OBS must be a naive Arizona-local clock")
    local_as_utc = raw_local.replace(tzinfo=ARIZONA).astimezone(UTC)
    if abs((local_as_utc - start).total_seconds()) > CLOCK_TOLERANCE_SECONDS:
        raise ValueError("DATE-OBS local clock disagrees with UTC DATE-BEG")
    return MMTOObservation(
        start_utc=start,
        midpoint_utc=start + timedelta(seconds=exposure_seconds / 2.0),
        exposure_seconds=exposure_seconds,
        schema="mmto_skywatch_utc_date_beg",
        provenance=(
            "FITS DATE-BEG interpreted as UTC exposure start; cross-checked against "
            "DATE-END and America/Phoenix DATE-OBS; midpoint=start+EXPTIME/2"
        ),
        instrument=instrument,
    )


def read_mmto_observation(path: Path) -> MMTOObservation:
    """Read a recognised MMTO FITS exposure without consulting its filename."""

    path = Path(path)
    try:
        with fits.open(path, memmap=False, do_not_scale_image_data=True) as hdus:
            header = hdus[0].header.copy()
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"cannot read MMTO FITS header: {exc}") from exc
    instrument = _validate_camera(header)
    seconds = _exposure_seconds(header)
    if "DATE-BEG" in header:
        return _new_observation(header, seconds, instrument)
    if "DATE-OBS" in header:
        return _old_observation(header, seconds, instrument)
    raise ValueError("recognised MMTO FITS header has no supported exposure start")
