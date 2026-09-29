"""Deterministic batched exact refinement for blind planetary passages."""
from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor
import os
import time
from typing import Callable, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class Visit:
    """One independent trajectory/source bracket found by the coarse search."""

    name: str
    source: int
    start: float
    stop: float
    visit_start: float
    visit_stop: float


@dataclass(frozen=True)
class Passage:
    """An exactly evaluated local positional minimum."""

    date: float
    name: str
    source: int
    cost: float
    interval: tuple[float, float]
    options: tuple[tuple[float, float, float, bool], ...] = ()


@dataclass
class PlanetRefinementResult:
    """Pickle-safe output from one independent planet group."""

    name: str
    passages: list[Passage]
    counters: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RefinementContext:
    """Pickle-safe fixed detector inputs shared by independent planet jobs."""

    camera: object
    xy: np.ndarray
    zenith: np.ndarray | None = None


def planet_worker_count(environ: Mapping[str, str] = os.environ,
                        nonempty_groups: int = 0) -> int:
    """Return a positive, useful process count capped by available planet work."""
    groups = max(0, int(nonempty_groups))
    requested = environ.get('WFS_PLANET_WORKERS')
    if requested is not None:
        try:
            workers = int(requested)
        except (TypeError, ValueError) as exc:
            raise ValueError('WFS_PLANET_WORKERS must be a positive integer') from exc
        if workers <= 0 or str(workers) != str(requested).strip():
            raise ValueError('WFS_PLANET_WORKERS must be a positive integer')
    else:
        workers = min(4, os.cpu_count() or 1)
    return max(1, min(workers, groups or 1))


def _costs(objective: Callable, dates: np.ndarray, vectors: np.ndarray,
           visits: Sequence[Visit]) -> np.ndarray:
    values = np.asarray(objective(dates, vectors, visits), dtype=np.float64)
    if values.shape != (len(dates),):
        raise ValueError('Batched planet objective must return one cost per visit')
    values = values.copy()
    values[~np.isfinite(values)] = np.inf
    return values


def batched_exact_minima(provider, name: str, visits: Sequence[Visit],
                         objective: Callable, xatol: float = 1e-7):
    """Minimize independent bounded objectives with vectorized exact calls.

    ``objective(dates, vectors, active_visits)`` must return one cost for each
    date. The provider is called once per active batch, so Astropy handles many
    independent passages in a vector rather than through scalar Python calls.
    Original endpoints remain candidates, preserving boundary minima.
    """
    visits = tuple(visits)
    if not visits:
        return np.empty(0), np.empty(0)
    if not np.isfinite(xatol) or xatol <= 0:
        raise ValueError('xatol must be positive and finite')
    if any(visit.name != name for visit in visits):
        raise ValueError('Every visit must belong to the refined planet')
    start = np.array([visit.start for visit in visits], dtype=np.float64)
    stop = np.array([visit.stop for visit in visits], dtype=np.float64)
    if (not np.isfinite(start).all() or not np.isfinite(stop).all()
            or np.any(stop <= start)):
        raise ValueError('Visit brackets must be finite and have positive width')

    invphi = (np.sqrt(5.)-1.)/2.
    a, b = start.copy(), stop.copy()
    c = b-invphi*(b-a)
    d = a+invphi*(b-a)
    combined = np.r_[c, d]
    exact = provider.exact(name, combined)
    fc = _costs(objective, c, exact[:len(visits)], visits)
    fd = _costs(objective, d, exact[len(visits):], visits)

    # Daily brackets converge in 36 iterations at 1e-7 day. The generous cap
    # also handles synthetic wider brackets while remaining deterministic.
    for _ in range(256):
        active = np.flatnonzero((b-a) > xatol)
        if not len(active):
            break
        left = active[fc[active] <= fd[active]]
        right = active[fc[active] > fd[active]]
        if len(left):
            b[left], d[left], fd[left] = d[left], c[left], fc[left]
            c[left] = b[left]-invphi*(b[left]-a[left])
        if len(right):
            a[right], c[right], fc[right] = c[right], d[right], fd[right]
            d[right] = a[right]+invphi*(b[right]-a[right])
        new_dates = np.r_[c[left], d[right]]
        new_visits = tuple(visits[i] for i in np.r_[left, right])
        new_vectors = provider.exact(name, new_dates)
        new_costs = _costs(objective, new_dates, new_vectors, new_visits)
        fc[left] = new_costs[:len(left)]
        fd[right] = new_costs[len(left):]
    else:
        raise RuntimeError('Batched planet refinement did not converge')

    middle = (a+b)/2.
    candidates = np.r_[start, middle, stop]
    exact = provider.exact(name, candidates)
    count = len(visits)
    costs = np.column_stack([
        _costs(objective, start, exact[:count], visits),
        _costs(objective, middle, exact[count:2*count], visits),
        _costs(objective, stop, exact[2*count:], visits),
    ])
    choice = np.argmin(costs, axis=1)
    dates = np.column_stack([start, middle, stop])[np.arange(count), choice]
    return dates, costs[np.arange(count), choice]


def batched_interpolated_minima(provider, name: str, visits: Sequence[Visit],
                                objective: Callable, xatol: float = 1e-4):
    """Produce cheap cubic-trajectory proposals without narrowing exact brackets.

    Five positions sample each original bracket in one vector call. A local
    parabolic step around the best sample then proposes a sub-grid date for one
    further interpolated evaluation. The subsequent exact optimizer still sees
    the entire unchanged bracket.
    """
    visits = tuple(visits)
    if not visits:
        return np.empty(0), np.empty(0)
    if not np.isfinite(xatol) or xatol <= 0:
        raise ValueError('xatol must be positive and finite')
    if any(visit.name != name for visit in visits):
        raise ValueError('Every visit must belong to the refined planet')
    a = np.array([visit.start for visit in visits], dtype=np.float64)
    b = np.array([visit.stop for visit in visits], dtype=np.float64)
    if (not np.isfinite(a).all() or not np.isfinite(b).all() or np.any(b <= a)):
        raise ValueError('Visit brackets must be finite and have positive width')
    fractions = np.linspace(0., 1., 5)
    sampled_dates = np.concatenate([a+fraction*(b-a) for fraction in fractions])
    active_visits = visits*len(fractions)
    vectors = provider.interpolated(name, sampled_dates)
    sampled_costs = _costs(objective, sampled_dates, vectors, active_visits)
    sampled_costs = sampled_costs.reshape(len(fractions), len(visits))
    best = np.argmin(sampled_costs, axis=0)
    proposed_fraction = fractions[best]
    interior = np.flatnonzero((best > 0) & (best < len(fractions)-1))
    if len(interior):
        center = best[interior]
        columns = interior
        lower = sampled_costs[center-1, columns]
        middle = sampled_costs[center, columns]
        upper = sampled_costs[center+1, columns]
        denominator = lower-2*middle+upper
        stable = np.abs(denominator) > np.finfo(float).eps*np.maximum(
            1., np.maximum(abs(lower), abs(upper)))
        delta = np.zeros(len(interior))
        delta[stable] = .5*(lower[stable]-upper[stable])/denominator[stable]
        proposed_fraction[interior] = np.clip(
            (center+np.clip(delta, -1., 1.))/4., 0., 1.)
    dates = a+proposed_fraction*(b-a)
    values = provider.interpolated(name, dates)
    return dates, _costs(objective, dates, values, visits)


def _project(camera, vectors):
    vectors = np.asarray(vectors, dtype=np.float64)
    try:
        return camera.project(vectors)
    except ValueError:
        points = np.full((len(vectors), 2), np.nan)
        for index, vector in enumerate(vectors):
            try:
                points[index] = camera.project(vector[None, :])[0]
            except ValueError:
                pass
        return points


def refine_planet_visits(name: str, visits: Sequence[Visit],
                         context: RefinementContext, provider) -> PlanetRefinementResult:
    """Propose cheaply, then refine every passage with exact batched vectors."""
    visits = tuple(visits)
    started = time.perf_counter()
    before = provider.counts()
    proposal_started = time.perf_counter()
    xy = np.asarray(context.xy, dtype=np.float64)

    def objective(dates, vectors, active_visits):
        points = _project(context.camera, vectors)
        measured = xy[[visit.source for visit in active_visits]]
        return np.sum((points-measured)**2, axis=1)

    try:
        proposal_dates, _ = batched_interpolated_minima(
            provider, name, visits, objective)
    except ValueError:
        # Small synthetic providers may not have a cubic stencil. This never
        # narrows the exact bracket or changes its authoritative minimization.
        proposal_dates = np.array([(visit.start+visit.stop)/2. for visit in visits])
    proposal_seconds = time.perf_counter()-proposal_started

    exact_started = time.perf_counter()
    dates, costs = batched_exact_minima(provider, name, visits, objective)
    count = len(visits)
    option_dates = np.r_[
        [visit.start for visit in visits], dates,
        [visit.stop for visit in visits], proposal_dates]
    option_vectors = provider.exact(name, option_dates)
    option_points = _project(context.camera, option_vectors)
    option_sources = np.tile([visit.source for visit in visits], 4)
    option_costs = np.sum((option_points-xy[option_sources])**2, axis=1)
    option_altitudes = np.full(4*count, np.nan)
    option_visible = np.isfinite(option_points).all(axis=1)
    if context.zenith is not None:
        zenith = np.asarray(context.zenith, dtype=np.float64)
        zenith /= np.linalg.norm(zenith)
        option_altitudes = np.rad2deg(np.arcsin(np.clip(option_vectors@zenith, -1., 1.)))
        height, width = context.camera.shape
        option_visible &= ((option_altitudes >= -1e-7)
                           & (option_points[:, 0] >= 0) & (option_points[:, 0] <= width-1)
                           & (option_points[:, 1] >= 0) & (option_points[:, 1] <= height-1))
        indices = np.flatnonzero(option_visible)
        if len(indices):
            inverse = context.camera.to_sky(option_points[indices])
            option_visible[indices] &= (
                np.linalg.norm(inverse-option_vectors[indices], axis=1) < 1e-6)
    exact_seconds = time.perf_counter()-exact_started
    passages = []
    proposal_vectors = option_vectors[3*count:]
    try:
        proposed_approximation = provider.interpolated(name, proposal_dates)
        chord = np.linalg.norm(proposed_approximation-proposal_vectors, axis=1)
        proposal_error_arcsec = (2*np.arcsin(np.clip(chord/2, 0, 1))
                                 * 206264.80624709636)
        from point_star_planet_ephemeris import INTERPOLATION_GUARD_ARCSEC
        safe_proposal = proposal_error_arcsec <= INTERPOLATION_GUARD_ARCSEC
    except ValueError:
        safe_proposal = np.zeros(count, dtype=bool)
    for index, (visit, date, cost) in enumerate(zip(visits, dates, costs)):
        indices = [index, count+index, 2*count+index]
        if safe_proposal[index]:
            indices.append(3*count+index)
        options = tuple((float(option_dates[i]), float(option_costs[i]),
                         float(option_altitudes[i]), bool(option_visible[i]))
                        for i in indices)
        passages.append(Passage(
            float(date), name, visit.source, float(cost),
            (float(visit.visit_start), float(visit.visit_stop)), options))
    after = provider.counts()
    counters = {key: int(after[key]-before.get(key, 0)) for key in after}
    return PlanetRefinementResult(
        name=name, passages=passages, counters=counters,
        timings={'proposal_seconds': proposal_seconds,
                 'exact_refinement_seconds': exact_seconds,
                 'total_seconds': time.perf_counter()-started})


def _refine_worker(payload):
    name, visits, context, jd, track, exact_function = payload
    from point_star_planet_ephemeris import EphemerisProvider
    provider = EphemerisProvider(jd, {name: track}, exact_function=exact_function)
    try:
        return refine_planet_visits(name, visits, context, provider)
    except Exception as exc:
        raise RuntimeError(f'{name} planet refinement failed: {exc}') from exc


def refine_all_planets(grouped_visits, context: RefinementContext, reference,
                       workers: int | None = None) -> list[PlanetRefinementResult]:
    """Refine nonempty planet groups serially or in deterministic processes."""
    jd, vectors, exact_function = reference
    groups = [(name, tuple(grouped_visits[name])) for name in grouped_visits
              if grouped_visits[name]]
    if not groups:
        return []
    if workers is None:
        workers = planet_worker_count(nonempty_groups=len(groups))
    if not isinstance(workers, int) or workers <= 0:
        raise ValueError('Planet worker count must be a positive integer')
    workers = min(workers, len(groups))
    payloads = [(name, visits, context, np.asarray(jd), np.asarray(vectors[name]),
                 exact_function) for name, visits in groups]
    if workers == 1:
        results = [_refine_worker(payload) for payload in payloads]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [(name, executor.submit(_refine_worker, payload))
                       for (name, _), payload in zip(groups, payloads)]
            results = []
            for name, future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    raise RuntimeError(f'{name} planet worker failed: {exc}') from exc
    order = {name: index for index, name in enumerate(vectors)}
    results.sort(key=lambda result: order[result.name])
    return results
