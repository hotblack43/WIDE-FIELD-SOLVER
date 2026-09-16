"""Local, image-independent reference trajectories for blind planetary searches.

Daily samples are a coarse search aid; refine candidate epochs with
``planet_vectors``. Positions are geocentric apparent GCRS, not topocentric or
ICRS catalogue directions. No observing location, UTC date, or network is used.
The supported reference interval is Julian years 1850--2036 TDB. Astropy's
builtin ephemeris is approximate, especially outside 1900--2100; it is not a
precision dating standard. See returned provenance for the limitations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import warnings
from zipfile import BadZipFile

import astropy
from astropy.coordinates import get_body
from astropy.time import Time
import erfa
import numpy as np


PLANETS = ('mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune')
ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = ROOT / 'results' / 'ephemeris-cache'
BUNDLED_REFERENCE = ROOT / 'data' / 'planet-reference-1850-2036.npz'
INTERPOLATION_GUARD_ARCSEC = 5.0
SCHEMA_VERSION = 1
_CHUNK_SIZE = 4096
_LIMITATIONS = [
    'Astropy builtin ERFA ephemerides are approximate, not JPL precision ephemerides.',
    'ERFA Earth epv00 accuracy is characterised over 1900–2100; accuracy degrades '
    'outside this interval, including the 1850–1900 historical search tail.',
    'Geocentric apparent GCRS includes light travel time and aberration; mapping '
    'through a catalogue-fitted camera has frame and annual-aberration limitations.',
    'No topocentric parallax or atmospheric refraction correction is applied.',
    'Daily trajectory chords are approximate; refine candidate dates with exact '
    'ephemeris evaluations and retain model uncertainty separately.',
]


def planet_vectors(name: str, jd_tdb) -> np.ndarray:
    """Return finite normalized apparent geocentric directions, always (N, 3).

    Scalar and one-dimensional numerical Julian dates are accepted. TDB dates
    create a new Time without observer metadata. Empty input yields (0, 3).
    Known ERFA warnings for the reference interval's historical/future tails
    are captured here; their accuracy implications are recorded in provenance.
    Other warnings remain visible.
    """
    if name not in PLANETS:
        raise ValueError(f'Unsupported planet: {name!r}')
    return _body_vectors(name, jd_tdb)


def sun_vectors(jd_tdb) -> np.ndarray:
    """Sun in the same local apparent geocentric GCRS convention as planets."""
    return _body_vectors('sun', jd_tdb)


def _body_vectors(name, jd_tdb):
    jd = np.asarray(jd_tdb, dtype=np.float64)
    if jd.ndim > 1 or not np.isfinite(jd).all():
        raise ValueError('jd_tdb must be finite scalar or one-dimensional Julian dates')
    jd = np.atleast_1d(jd)
    if not len(jd):
        return np.empty((0, 3), dtype=np.float64)
    with warnings.catch_warnings():
        # get_body can internally convert TDB to UTC despite its TDB input.
        # These known warnings must not swamp a 300-year coarse search.
        warnings.filterwarnings('ignore', message=r'ERFA function "epv00".*', category=erfa.ErfaWarning)
        warnings.filterwarnings('ignore', message=r'ERFA function "(?:taiutc|utctai)".*dubious year.*', category=erfa.ErfaWarning)
        body = get_body(name, Time(jd, format='jd', scale='tdb'),
                        location=None, ephemeris='builtin')
    xyz = np.asarray(body.cartesian.xyz.value.T, dtype=np.float64)
    norms = np.linalg.norm(xyz, axis=1)
    if xyz.shape != (len(jd), 3) or not np.isfinite(xyz).all() or np.any(norms <= 0):
        raise ValueError('Ephemeris returned invalid direction vectors')
    return xyz / norms[:, None]


def _content_digest(jd: np.ndarray, vectors: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name, values in [('jd_tdb', jd), *[(name, vectors[name]) for name in PLANETS]]:
        digest.update(name.encode('ascii'))
        digest.update(np.asarray(values, dtype='<f8').tobytes(order='C'))
    return digest.hexdigest()


def _validated_dates(name: str, jd_tdb) -> np.ndarray:
    if name not in PLANETS:
        raise ValueError(f'Unsupported planet: {name!r}')
    dates = np.asarray(jd_tdb, dtype=np.float64)
    if dates.ndim > 1 or not np.isfinite(dates).all():
        raise ValueError('jd_tdb must be finite scalar or one-dimensional Julian dates')
    return np.atleast_1d(dates)


class EphemerisProvider:
    """Separate fast daily-table proposals from authoritative exact vectors."""

    def __init__(self, jd, vectors, exact_function=planet_vectors):
        self.jd = np.asarray(jd, dtype=np.float64)
        if (self.jd.ndim != 1 or len(self.jd) < 2 or not np.isfinite(self.jd).all()
                or np.any(np.diff(self.jd) <= 0)):
            raise ValueError('Ephemeris provider needs at least two increasing dates')
        if not vectors or any(name not in PLANETS for name in vectors):
            raise ValueError('Ephemeris provider needs supported planet tracks')
        self.vectors = {name: np.asarray(value, dtype=np.float64)
                        for name, value in vectors.items()}
        if any(value.shape != (len(self.jd), 3) for value in self.vectors.values()):
            raise ValueError('Ephemeris provider track shape differs from date grid')
        self.exact_function = exact_function
        self._counts = dict(interpolated_calls=0, interpolated_dates=0,
                            exact_calls=0, exact_dates=0)

    def interpolated(self, name: str, jd_tdb) -> np.ndarray:
        dates = _validated_dates(name, jd_tdb)
        if name not in self.vectors:
            raise ValueError(f'No reference track for planet: {name!r}')
        if not len(dates):
            return np.empty((0, 3), dtype=np.float64)
        track = self.vectors[name]
        if np.any(dates < self.jd[0]) or np.any(dates > self.jd[-1]):
            raise ValueError('Interpolated date lies outside the reference interval')
        if len(self.jd) < 4:
            raise ValueError('Interpolation requires four reference samples')
        value = np.empty((len(dates), 3), dtype=np.float64)
        insertion = np.searchsorted(self.jd, dates, side='left')
        clipped = np.clip(insertion, 0, len(self.jd)-1)
        exact = self.jd[clipped] == dates
        value[exact] = track[clipped[exact]]
        for row in np.flatnonzero(~exact):
            right = insertion[row]
            left = right-1
            first = min(max(left-1, 0), len(self.jd)-4)
            sample_dates = self.jd[first:first+4]
            sample_vectors = track[first:first+4]
            weights = np.ones(4, dtype=np.float64)
            for i in range(4):
                for j in range(4):
                    if i != j:
                        weights[i] *= ((dates[row]-sample_dates[j]) /
                                       (sample_dates[i]-sample_dates[j]))
            value[row] = weights@sample_vectors
        norms = np.linalg.norm(value, axis=1)
        if not np.isfinite(value).all() or np.any(norms <= 0):
            raise ValueError('Interpolated ephemeris returned invalid vectors')
        value[~exact] /= norms[~exact, None]
        self._counts['interpolated_calls'] += 1
        self._counts['interpolated_dates'] += len(dates)
        return value

    def exact(self, name: str, jd_tdb) -> np.ndarray:
        dates = _validated_dates(name, jd_tdb)
        self._counts['exact_calls'] += 1
        self._counts['exact_dates'] += len(dates)
        return self.exact_function(name, dates)

    def counts(self) -> dict[str, int]:
        return dict(self._counts)


def _read_cache(path: Path, jd: np.ndarray, expected: dict):
    """Invalid/truncated/stale files are reference cache misses, never seeds."""
    try:
        with np.load(path, allow_pickle=False) as data:
            provenance = json.loads(str(data['provenance']))
            if not isinstance(provenance, dict) or any(provenance.get(k) != v for k, v in expected.items()):
                return None
            cached_jd = data['jd_tdb']
            if not np.array_equal(cached_jd, jd):
                return None
            vectors = {name: data[name] for name in PLANETS}
            for values in vectors.values():
                if (values.shape != (len(jd), 3) or not np.isfinite(values).all()
                        or not np.allclose(np.linalg.norm(values, axis=1), 1., rtol=0, atol=1e-12)):
                    return None
            if provenance.get('content_sha256') != _content_digest(cached_jd, vectors):
                return None
            return cached_jd, vectors, provenance
    except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile):
        return None


def _runtime_provenance(provenance, path, source, started, build_seconds=0.):
    result = dict(provenance)
    result.update(cache_source=source, cache_path=str(Path(path).resolve()),
                  cache_bytes=Path(path).stat().st_size,
                  cache_load_seconds=float(time.perf_counter()-started),
                  cache_build_seconds=float(build_seconds))
    return result


def load_ephemeris(start_jyear: float = 1850., end_jyear: float = 2036.,
                   cache_dir: Path | str = DEFAULT_CACHE_DIR,
                   bundled_path: Path | str | None = None, *,
                   prefer_bundled: bool = True):
    """Load/build a daily TDB reference grid, including both interval endpoints.

    Ranges outside 1850--2036 are unsupported and rejected. Cache validity
    includes schema, bounds, Astropy/ERFA versions, exact timestamps, unit
    vectors, and SHA256 of every numerical array. Atomic replacement avoids
    exposing partially written tables. No measured images/identities are cached.
    """
    started = time.perf_counter()
    start, end = float(start_jyear), float(end_jyear)
    if not (np.isfinite(start) and np.isfinite(end) and 1850. <= start < end <= 2036.):
        raise ValueError('Reference range must satisfy 1850 <= start_jyear < end_jyear <= 2036')
    first, last = Time([start, end], format='jyear', scale='tdb').jd
    jd = first + np.arange(int(np.floor(last - first)) + 1, dtype=np.float64)
    if jd[-1] < last:
        jd = np.append(jd, last)
    provenance = {
        'schema_version': SCHEMA_VERSION,
        'astropy_version': astropy.__version__,
        'erfa_version': erfa.__version__,
        'ephemeris': 'builtin',
        'frame': 'geocentric apparent GCRS',
        'time_scale': 'tdb',
        'start_jyear': start,
        'end_jyear': end,
        'step_days': 1.,
        'includes_end': True,
        'planets': list(PLANETS),
        'limitations': list(_LIMITATIONS),
        'suppressed_erfa_warnings': ['epv00 outside 1900–2100', 'taiutc/utctai dubious year'],
        'observer': 'geocenter; no site metadata',
        'reference_only': True,
    }
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode('utf-8')).hexdigest()[:20]
    explicit_bundle = bundled_path is not None
    if bundled_path is None and prefer_bundled and start == 1850. and end == 2036.:
        bundled_path = BUNDLED_REFERENCE
    if bundled_path is not None:
        bundle = Path(bundled_path)
        if bundle.is_file():
            cached = _read_cache(bundle, jd, provenance)
            if cached is None:
                raise ValueError(f'Invalid bundled ephemeris: {bundle}')
            cached_jd, vectors, saved = cached
            return cached_jd, vectors, _runtime_provenance(
                saved, bundle, 'bundled', started)
        if explicit_bundle:
            raise ValueError(f'Bundled ephemeris does not exist: {bundle}')
    cache_dir = Path(cache_dir)
    filename = cache_dir / f'planet-reference-{key}.npz'
    cached = _read_cache(filename, jd, provenance)
    if cached is not None:
        cached_jd, vectors, saved = cached
        return cached_jd, vectors, _runtime_provenance(
            saved, filename, 'writable_cache', started)
    cache_dir.mkdir(parents=True, exist_ok=True)
    verbose = len(jd) > _CHUNK_SIZE
    if verbose:
        print(f'Building local builtin planet ephemeris: {len(jd):,} dates, '
              f'{start:g}–{end:g} Julian years TDB.', flush=True)
        print('Ephemeris limitation: approximate geocentric directions; accuracy '
              'degrades outside 1900–2100.', flush=True)
    last_progress = time.monotonic()
    build_started = time.perf_counter()
    vectors = {}
    for name in PLANETS:
        values = np.empty((len(jd), 3), dtype=np.float64)
        for begin in range(0, len(jd), _CHUNK_SIZE):
            finish = min(begin + _CHUNK_SIZE, len(jd))
            values[begin:finish] = planet_vectors(name, jd[begin:finish])
            now = time.monotonic()
            if verbose and now - last_progress >= 20:
                print(f'Planet ephemeris: {name}, {finish:,}/{len(jd):,} dates.', flush=True)
                last_progress = now
        vectors[name] = values
    provenance['content_sha256'] = _content_digest(jd, vectors)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache_dir, prefix='.ephemeris-', suffix='.npz', delete=False) as stream:
            temporary = Path(stream.name)
            np.savez(stream, jd_tdb=jd, provenance=np.asarray(json.dumps(provenance)), **vectors)
        temporary.replace(filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if verbose:
        print(f'Planet reference ephemeris cached at {filename}', flush=True)
    build_seconds = time.perf_counter()-build_started
    return jd, vectors, _runtime_provenance(
        provenance, filename, 'generated', started, build_seconds)
