from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Site:
    source_id: str
    camera_id: str
    name: str
    timezone: str
    latitude_deg: float | None
    longitude_deg: float | None
    elevation_m: float | None


@dataclass(frozen=True, slots=True)
class Candidate:
    source_id: str
    camera_id: str
    observed_at: datetime
    observed_raw: str
    url: str
    filename: str
    size_bytes: int | None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must be nonnegative")


@dataclass(frozen=True, slots=True)
class DateRange:
    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        for name, value in (("start_utc", self.start_utc), ("end_utc", self.end_utc)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")


@dataclass(frozen=True, slots=True)
class Selection:
    candidates: tuple[Candidate, ...]
    eligible_count: int
    truncated: bool
    known_bytes: int
    unknown_size_count: int
