"""Causal epoch limits from the clock, never from observing metadata."""
import math

from astropy.time import Time


def capture_time_ceiling():
    """Record one instant: an already existing image cannot date after this run."""
    instant = Time.now()
    instant.precision = 9
    return dict(utc=instant.utc.isot, jd_tdb=float(instant.tdb.jd),
                jyear=float(instant.tdb.jyear),
                source='current_system_time_at_run_start')


def limit_epoch_range(limits, ceiling):
    """Intersect a finite, increasing Julian-year range with a causal ceiling."""
    try:
        lower, upper = map(float, limits)
        latest = float(ceiling['jyear'])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError('Epoch limits and causal ceiling must be finite numbers') from exc
    if not all(math.isfinite(value) for value in (lower, upper, latest)) or lower >= upper:
        raise ValueError('Epoch limits must be finite and increasing; ceiling must be finite')
    upper = min(upper, latest)
    if lower >= upper:
        raise ValueError('Epoch range has no interval at or before the causal time ceiling')
    return lower, upper
