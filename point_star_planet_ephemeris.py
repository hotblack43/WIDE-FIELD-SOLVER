"""Local, image-independent reference trajectories for blind planetary searches.

Daily samples are a coarse search aid; refine candidate epochs with
``planet_vectors``. Positions are geocentric apparent GCRS, not topocentric or
ICRS catalogue directions. No observing location, UTC date, or network is used.
The supported reference interval is Julian years 1850--2150 TDB. Astropy's
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
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / 'results' / 'ephemeris-cache'
SCHEMA_VERSION = 1
_CHUNK_SIZE = 4096
_LIMITATIONS = [
    'Astropy builtin ERFA ephemerides are approximate, not JPL precision ephemerides.',
    'ERFA Earth epv00 accuracy is characterised over 1900–2100; accuracy degrades '
    'outside this interval, including the 1850–1900 and 2100–2150 search tails.',
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


def load_ephemeris(start_jyear: float = 1850., end_jyear: float = 2150.,
                   cache_dir: Path | str = DEFAULT_CACHE_DIR):
    """Load/build a daily TDB reference grid, including both interval endpoints.

    Ranges outside 1850--2150 are unsupported and rejected. Cache validity
    includes schema, bounds, Astropy/ERFA versions, exact timestamps, unit
    vectors, and SHA256 of every numerical array. Atomic replacement avoids
    exposing partially written tables. No measured images/identities are cached.
    """
    start, end = float(start_jyear), float(end_jyear)
    if not (np.isfinite(start) and np.isfinite(end) and 1850. <= start < end <= 2150.):
        raise ValueError('Reference range must satisfy 1850 <= start_jyear < end_jyear <= 2150')
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
    cache_dir = Path(cache_dir)
    filename = cache_dir / f'planet-reference-{key}.npz'
    cached = _read_cache(filename, jd, provenance)
    if cached is not None:
        return cached
    cache_dir.mkdir(parents=True, exist_ok=True)
    verbose = len(jd) > _CHUNK_SIZE
    if verbose:
        print(f'Building local builtin planet ephemeris: {len(jd):,} dates, '
              f'{start:g}–{end:g} Julian years TDB.', flush=True)
        print('Ephemeris limitation: approximate geocentric directions; accuracy '
              'degrades outside 1900–2100.', flush=True)
    last_progress = time.monotonic()
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
    return jd, vectors, provenance
