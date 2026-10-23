#!/usr/bin/env python3
"""Fail-open matching for public MMTO summit weather telemetry."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from typing import Callable, Literal
from urllib.parse import urlencode
from urllib.request import Request, urlopen


UTC = timezone.utc
HISTORY_ENDPOINT = "https://api.mmto.arizona.edu/APIv1/history"
OUTSIDE_HUMIDITY_SENSORS = (
    "vaisala2_relative_humidity",
    "vaisala4_relative_humidity",
)


def _as_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WeatherSample:
    sensor: str
    observed_utc: datetime
    humidity_percent: float

    def __post_init__(self) -> None:
        if not self.sensor:
            raise ValueError("sensor must not be empty")
        object.__setattr__(
            self,
            "observed_utc",
            _as_utc(self.observed_utc, name="observed_utc"),
        )
        humidity = float(self.humidity_percent)
        if not math.isfinite(humidity) or not 0.0 <= humidity <= 100.0:
            raise ValueError("humidity_percent must be finite and between 0 and 100")
        object.__setattr__(self, "humidity_percent", humidity)


@dataclass(frozen=True, slots=True)
class WeatherDecision:
    status: Literal["accept", "skip", "unknown"]
    humidity_percent: float | None
    sample_utc: datetime | None
    age_seconds: float | None
    sensor: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class MmtoWeatherHistory:
    samples: tuple[WeatherSample, ...] = ()
    errors: tuple[str, ...] = ()

    @classmethod
    def fetch(
        cls,
        start_utc: datetime,
        end_utc: datetime,
        *,
        opener: Callable[..., object] | None = None,
        timeout: float = 20.0,
        endpoint: str = HISTORY_ENDPOINT,
    ) -> "MmtoWeatherHistory":
        start = _as_utc(start_utc, name="start_utc")
        end = _as_utc(end_utc, name="end_utc")
        if end <= start:
            raise ValueError("end_utc must follow start_utc")
        timeout_seconds = float(timeout)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
            raise ValueError("timeout must be positive and finite")
        if opener is None:
            opener = lambda request, request_timeout: urlopen(
                request, timeout=request_timeout
            )

        samples: list[WeatherSample] = []
        errors: list[str] = []
        for sensor in OUTSIDE_HUMIDITY_SENSORS:
            body = urlencode(
                {
                    "table": "measurements",
                    "fields": sensor,
                    "start": int(start.timestamp()),
                    "end": int(end.timestamp()),
                }
            ).encode("ascii")
            request = Request(
                endpoint,
                data=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "WIDE-FIELD-SOLVER-mmto-weather/0.23",
                },
                method="POST",
            )
            try:
                with opener(request, timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise ValueError("history response must be a JSON array")
            except Exception as exc:
                errors.append(f"{sensor}: {type(exc).__name__}: {exc}")
                continue

            for index, item in enumerate(payload):
                try:
                    if not isinstance(item, dict):
                        raise TypeError("sample must be an object")
                    timestamp_ms = float(item["timestamp"])
                    if not math.isfinite(timestamp_ms):
                        raise ValueError("timestamp must be finite")
                    samples.append(
                        WeatherSample(
                            sensor=sensor,
                            observed_utc=datetime.fromtimestamp(
                                timestamp_ms / 1000.0, tz=UTC
                            ),
                            humidity_percent=float(item["value"]),
                        )
                    )
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    errors.append(
                        f"{sensor}[{index}]: {type(exc).__name__}: {exc}"
                    )

        samples.sort(key=lambda item: (item.observed_utc, item.sensor))
        return cls(tuple(samples), tuple(errors))

    def decide(
        self,
        observed_utc: datetime,
        *,
        max_humidity_percent: float = 80.0,
        max_age_seconds: float = 120.0,
    ) -> WeatherDecision:
        observed = _as_utc(observed_utc, name="observed_utc")
        threshold = float(max_humidity_percent)
        age_limit = float(max_age_seconds)
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
            raise ValueError(
                "max_humidity_percent must be finite and between 0 and 100"
            )
        if not math.isfinite(age_limit) or age_limit <= 0.0:
            raise ValueError("max_age_seconds must be positive and finite")

        nearest_by_sensor: dict[str, tuple[float, WeatherSample]] = {}
        for weather_sample in self.samples:
            age = abs((weather_sample.observed_utc - observed).total_seconds())
            previous = nearest_by_sensor.get(weather_sample.sensor)
            if previous is None or age < previous[0]:
                nearest_by_sensor[weather_sample.sensor] = (age, weather_sample)

        fresh = [
            (age, weather_sample)
            for age, weather_sample in nearest_by_sensor.values()
            if age <= age_limit
        ]
        if not fresh:
            return WeatherDecision(
                status="unknown",
                humidity_percent=None,
                sample_utc=None,
                age_seconds=None,
                sensor=None,
                reason="no_fresh_sample",
            )

        age, selected = max(
            fresh,
            key=lambda item: (item[1].humidity_percent, item[1].sensor),
        )
        status: Literal["accept", "skip"] = (
            "skip" if selected.humidity_percent >= threshold else "accept"
        )
        return WeatherDecision(
            status=status,
            humidity_percent=selected.humidity_percent,
            sample_utc=selected.observed_utc,
            age_seconds=age,
            sensor=selected.sensor,
            reason=(
                "humidity_at_or_above_limit"
                if status == "skip"
                else "humidity_below_limit"
            ),
        )
