from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from .model import Candidate, DateRange, Selection, Site


_DURATION = re.compile(r"^(\d+(?:\.\d+)?)([smh])$")
_SECONDS_PER_UNIT = {"s": Decimal(1), "m": Decimal(60), "h": Decimal(3600)}
UTC = timezone.utc


def parse_duration(text: str) -> timedelta:
    match = _DURATION.fullmatch(text)
    if match is None:
        raise ValueError("duration must be a positive number followed by s, m, or h")
    try:
        seconds = Decimal(match.group(1)) * _SECONDS_PER_UNIT[match.group(2)]
    except InvalidOperation as exc:
        raise ValueError("invalid duration") from exc
    if not seconds.is_finite() or seconds <= 0:
        raise ValueError("duration must be positive and finite")
    try:
        result = timedelta(seconds=float(seconds))
    except OverflowError as exc:
        raise ValueError("duration is too large") from exc
    if result.total_seconds() <= 0 or not math.isfinite(result.total_seconds()):
        raise ValueError("duration is outside the supported range")
    return result


def site_date_range(
    site: Site,
    *,
    date_value: date | None,
    start: date | None,
    end: date | None,
) -> DateRange:
    if date_value is not None:
        if start is not None or end is not None:
            raise ValueError("--date cannot be combined with --start or --end")
        local_start = date_value
        local_end = date_value + timedelta(days=1)
    else:
        if start is None or end is None:
            raise ValueError("provide --date or both --start and --end")
        if end <= start:
            raise ValueError("--end must be after --start")
        local_start, local_end = start, end

    zone = ZoneInfo(site.timezone)
    start_utc = datetime.combine(local_start, time.min, zone).astimezone(UTC)
    end_utc = datetime.combine(local_end, time.min, zone).astimezone(UTC)
    return DateRange(start_utc, end_utc)


def select_candidates(
    candidates: Iterable[Candidate],
    ranges: Mapping[tuple[str, str], DateRange],
    cadence: timedelta,
    max_files: int,
    *,
    newest: bool = False,
) -> Selection:
    cadence_seconds = cadence.total_seconds()
    if cadence_seconds <= 0 or not math.isfinite(cadence_seconds):
        raise ValueError("cadence must be positive and finite")
    if max_files <= 0:
        raise ValueError("max_files must be positive")

    winners: dict[tuple[str, str, int], Candidate] = {}
    for item in candidates:
        key = (item.source_id, item.camera_id)
        requested = ranges.get(key)
        if requested is None:
            continue
        observed = item.observed_at.astimezone(UTC)
        if not requested.start_utc <= observed < requested.end_utc:
            continue
        slot = int((observed - requested.start_utc).total_seconds() // cadence_seconds)
        slot_key = (item.source_id, item.camera_id, slot)
        previous = winners.get(slot_key)
        if previous is None or (observed, item.url) < (
            previous.observed_at.astimezone(UTC),
            previous.url,
        ):
            winners[slot_key] = item

    eligible = sorted(
        winners.values(),
        key=lambda item: (
            item.observed_at.astimezone(UTC),
            item.source_id,
            item.camera_id,
            item.url,
        ),
    )
    selected = tuple(eligible[-max_files:] if newest else eligible[:max_files])
    return Selection(
        candidates=selected,
        eligible_count=len(eligible),
        truncated=len(eligible) > max_files,
        known_bytes=sum(item.size_bytes for item in selected if item.size_bytes is not None),
        unknown_size_count=sum(item.size_bytes is None for item in selected),
    )
