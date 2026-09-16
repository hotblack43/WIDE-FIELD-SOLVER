"""Blind positional planet/date candidates, independent of observation metadata."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linear_sum_assignment, minimize_scalar, brentq
from scipy.spatial import cKDTree


def _load_sky_footprint(solution):
    """Load an optional detection-domain mask; legacy analyses have none."""
    path = Path(solution)/'dots/sky_footprint.npz'
    if not path.is_file():
        return None
    with np.load(path) as saved:
        if 'valid_mask' not in saved:
            raise ValueError('Saved sky-footprint file has no valid_mask')
        mask = np.asarray(saved['valid_mask'], dtype=bool)
    if mask.ndim != 2:
        raise ValueError('Saved sky-footprint mask is not two-dimensional')
    return mask


def _date_text(jd):
    from astropy.time import Time
    return Time(jd, format='jd', scale='tdb').isot + ' TDB'


def _project(camera, vectors):
    """Keep a ray outside the model's inverse domain from aborting other rays."""
    vectors = np.asarray(vectors, dtype=float)
    if vectors.ndim != 2 or vectors.shape[1] != 3:
        raise ValueError('Projection requires an array of three-dimensional rays')
    with np.errstate(all='ignore'):
        try:
            return camera.project(vectors)
        except ValueError:
            points = np.full((len(vectors), 2), np.nan)
            for i, vector in enumerate(vectors):
                try:
                    points[i] = camera.project(vector[None, :])[0]
                except ValueError:
                    pass  # This ray has no valid projection in this camera.
            return points


def _altitudes(vectors, zenith):
    vectors = np.asarray(vectors, dtype=float)
    return np.rad2deg(np.arcsin(np.clip(vectors @ zenith, -1., 1.)))


def _visible_projection(camera, vectors, zenith):
    """Reject below-horizon, off-detector and non-invertible projections."""
    vectors = np.asarray(vectors, dtype=float)
    points = _project(camera, vectors)
    height, width = camera.shape
    valid = (np.isfinite(points).all(axis=1) & (_altitudes(vectors, zenith) >= -1e-7)
             & (points[:, 0] >= 0) & (points[:, 0] <= width-1)
             & (points[:, 1] >= 0) & (points[:, 1] <= height-1))
    if np.any(valid):
        indices = np.flatnonzero(valid)
        inverse = camera.to_sky(points[valid])
        valid[indices] &= np.linalg.norm(inverse-vectors[valid], axis=1) < 1e-6
    points[~valid] = np.nan
    return points


def _record_empty_performance(output, search_started, requested_workers):
    from point_star_planet_performance import PlanetSearchPerformance
    performance = PlanetSearchPerformance(requested_workers=int(requested_workers))
    performance.seconds.update(
        coarse_scan=0., interpolated_refinement=0., exact_refinement=0.,
        individual_refinement=0., joint_assignment=0., negative_evidence=0.,
        cache_load=0.)
    output['planet_search_performance'] = performance.serialise(
        total_planet_stage=time.perf_counter()-search_started)


def search_planet_epochs(camera, detections, jd_grid, sky_grid, vector_function, *,
                         gate_px=3., positional_sigma_px=.5, zenith_unit_vector=None,
                         zenith_status='conditional_zenith', latest_jd_tdb=None,
                         planet_workers=1):
    """Search trajectory segments, refine dates and retain competing assignments.

    Inputs are measured detections, a fitted camera and reference ephemerides only.
    A single planet never establishes a unique epoch. Multi-planet candidates also
    remain conditional: ranking is positional and not a false-alarm probability.
    """
    search_started = time.perf_counter()
    jd = np.asarray(jd_grid, dtype=float)
    if len(jd) < 2 or not np.isfinite(jd).all() or np.any(np.diff(jd) <= 0):
        raise ValueError('Planet search needs increasing finite reference dates')
    if gate_px <= 0 or positional_sigma_px <= 0:
        raise ValueError('Planet gate and positional uncertainty must be positive')
    from point_star_time_bounds import capture_time_ceiling
    if latest_jd_tdb is None:
        latest_jd_tdb = capture_time_ceiling()['jd_tdb']
    if not np.isfinite(latest_jd_tdb):
        raise ValueError('The causal time ceiling must be finite')
    last_date = min(float(jd[-1]), float(latest_jd_tdb))
    names = list(sky_grid)
    output = dict(status='no_planet_match', matches=[], candidates=[], match_count=0,
                  metadata_used=False, stellar_epoch_used_as_date_prior=False, derived_epoch_utc=None, source_candidates=[],
                  search_start_tdb=_date_text(jd[0]), search_end_tdb=_date_text(last_date), search_end_jd_tdb=last_date,
                  causal_latest_jd_tdb=float(latest_jd_tdb),
                  search_step_days=float(np.max(np.diff(jd))), searched_planets=names,
                  tested_sources=len(detections), gate_px=gate_px,
                  star_competition_delta_chi2=9.,
                  positional_sigma_px=positional_sigma_px,
                  method='blind trajectory-segment search, cubic proposals and batched exact positional time refinement',
                  limitation='Conditional on the saved camera and geocentric apparent ephemerides. '
                    'No site, image date or stellar epoch seeds this search. Topocentric parallax, '
                    'aberration/frame differences, refraction and ephemeris error are not fitted. '
                    'Local time uncertainty excludes global aliases and model systematics. '
                    'Ranking is not a calibrated false-alarm probability.')
    if last_date <= jd[0]:
        output['reason'] = 'Reference interval lies entirely beyond the causal time ceiling'
        _record_empty_performance(output, search_started, planet_workers)
        return output
    if jd[-1] > last_date:
        before = jd < last_date
        sky_grid = {name: np.vstack([np.asarray(values)[before], vector_function(name, [last_date])])
                    for name, values in sky_grid.items()}
        jd = np.r_[jd[before], last_date]
    if zenith_unit_vector is None:
        output.update(status='visibility_unresolved', reason='No image-derived photometric zenith; planet visibility cannot be checked')
        _record_empty_performance(output, search_started, planet_workers)
        return output
    zenith = np.asarray(zenith_unit_vector, dtype=float)
    if zenith.shape != (3,) or not np.isfinite(zenith).all() or np.linalg.norm(zenith) < 1e-12:
        raise ValueError('Planet visibility needs a finite nonzero zenith vector')
    zenith = zenith/np.linalg.norm(zenith)
    output['visibility'] = dict(source='image-derived photometric zenith', zenith_status=zenith_status,
                                zenith_unit_vector=zenith.tolist(), minimum_altitude_deg=0.,
                                horizon_roundoff_tolerance_deg=1e-7)
    if not detections or not names:
        output['reason'] = 'No measured sources or reference planets'
        _record_empty_performance(output, search_started, planet_workers)
        return output
    xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in detections])
    if not np.isfinite(xy).all():
        raise ValueError('Planet sources need finite measured detector positions')
    star_residual = np.array([float(row.get('catalogue_residual_px', np.inf)) for row in detections])
    # A catalogue match is an alternative explanation, not an irreversible veto.
    # Associated sources need a >=9 improvement in positional chi-square before
    # they can count toward a planet hypothesis; all flags remain in the exports.
    source_gate2 = np.minimum(gate_px**2, star_residual**2-9*positional_sigma_px**2)
    eligible = source_gate2 > 0
    output['unassociated_sources'] = int(np.isinf(star_residual).sum())
    output['sources_with_competitive_planet_hypothesis'] = int(eligible.sum())
    measured_rays = camera.to_sky(xy)
    measured_altitudes = _altitudes(measured_rays, zenith)
    height, width = camera.shape
    in_detector = ((xy[:, 0] >= 0) & (xy[:, 0] <= width-1) &
                   (xy[:, 1] >= 0) & (xy[:, 1] <= height-1))
    above_horizon = measured_altitudes >= -1e-7
    inverse_error = np.linalg.norm(_project(camera, measured_rays)-xy, axis=1)
    invertible = np.isfinite(inverse_error) & (inverse_error < 1e-3)
    visible = in_detector & above_horizon & invertible
    eligible &= visible
    source_gate2[~visible] = -1.
    output['visibility'].update(rejected_below_horizon_count=int((~above_horizon).sum()),
        rejected_outside_detector_count=int((~in_detector).sum()),
        rejected_noninvertible_count=int((~invertible).sum()), visible_detection_count=int(visible.sum()))
    output['visibility_sources'] = [dict(detection_id=int(row['detection_id']),
        x_px=float(xy[i, 0]), y_px=float(xy[i, 1]), altitude_deg=float(measured_altitudes[i]),
        visible=bool(visible[i]), rejection_reason='; '.join(reason for rejected, reason in
            [(not in_detector[i], 'outside_detector'), (not above_horizon[i], 'below_horizon'),
             (not invertible[i], 'noninvertible_projection')] if rejected))
        for i, row in enumerate(detections)]
    coarse_started = time.perf_counter()
    tree = cKDTree(measured_rays)
    # Convert the detector gate conservatively to angular distance using local
    # camera derivatives. Search on the sphere, avoiding off-detector projection
    # folds. A 0.1-degree daily curvature guard exceeds measured Mercury curvature
    # in the reference ephemeris tests; exact ephemerides set the final pixel gate.
    scales = [np.linalg.norm(camera.to_sky(xy+offset)-measured_rays, axis=1)
              for offset in ([1., 0.], [0., 1.])]
    angular_gate = 2*gate_px*float(np.max(scales)) + np.deg2rad(.1)
    tracks = {name: np.asarray(values) for name, values in sky_grid.items()}
    output['coarse_curvature_guard_deg'] = .1
    windows = []
    for name, track in tracks.items():
        if track.shape != (len(jd), 3):
            raise ValueError('Reference track shape differs from date grid')
        middle = (track[:-1]+track[1:])/2
        delta = track[1:]-track[:-1]
        length = np.linalg.norm(delta, axis=1)
        valid = np.isfinite(middle).all(axis=1) & np.isfinite(length)
        per_source = {}
        indices = np.flatnonzero(valid)
        neighbours = tree.query_ball_point(middle[valid], angular_gate+length[valid]/2+length[valid]**2/8)
        for index, nearby in zip(indices, neighbours):
            for source in nearby:
                if not eligible[source]:
                    continue
                fraction = np.clip(np.dot(measured_rays[source]-track[index], delta[index]) /
                                   max(length[index]**2, 1e-30), 0, 1)
                distance = np.linalg.norm(track[index]+fraction*delta[index]-measured_rays[source])
                if distance <= angular_gate+length[index]**2/8:
                    per_source.setdefault(source, []).append(int(index))
        for source, indices in per_source.items():
            # Split visits across epochs; retain each sampled local minimum in
            # a connected visit (including a stationary/retrograde double pass).
            for visit in np.split(indices, np.flatnonzero(np.diff(indices) > 1)+1):
                sample = np.arange(visit[0], visit[-1]+2)
                distances = np.linalg.norm(track[sample]-measured_rays[source], axis=1)
                minima = [k for k in range(len(sample)) if
                          (k == 0 or distances[k] <= distances[k-1]) and
                          (k == len(sample)-1 or distances[k] <= distances[k+1])]
                for k in minima:
                    lo, hi = max(0, sample[k]-1), min(len(jd)-1, sample[k]+1)
                    windows.append((name, source, jd[lo], jd[hi], jd[visit[0]], jd[visit[-1]+1]))
    coarse_seconds = time.perf_counter()-coarse_started
    print(f'Blind planets: refining {len(windows)} positional visits across the full date interval', flush=True)

    from point_star_planet_ephemeris import EphemerisProvider
    from point_star_planet_refinement import (
        RefinementContext, Visit, refine_all_planets)
    authoritative_function = vector_function
    provider = EphemerisProvider(jd, tracks, exact_function=authoritative_function)
    vector_function = provider.exact

    worker_counters = dict(interpolated_calls=0, interpolated_dates=0,
                           exact_calls=0, exact_dates=0)
    worker_timings = []
    workers_used = 1

    def record_performance(joint_seconds=0.):
        from point_star_planet_performance import PlanetSearchPerformance
        counts = provider.counts()
        counts = {key: int(value+worker_counters.get(key, 0))
                  for key, value in counts.items()}
        performance = PlanetSearchPerformance(requested_workers=int(planet_workers))
        performance.used_workers = int(workers_used)
        performance.providers.update(counts)
        proposal_seconds = (max((row['proposal_seconds'] for row in worker_timings), default=0.)
                            if workers_used > 1 else
                            sum(row['proposal_seconds'] for row in worker_timings))
        performance.seconds.update(
            coarse_scan=float(coarse_seconds),
            interpolated_refinement=float(proposal_seconds),
            exact_refinement=float(max(0., individual_seconds-proposal_seconds)),
            individual_refinement=float(individual_seconds),
            joint_assignment=float(joint_seconds),
            negative_evidence=0., cache_load=0.)
        performance.counts.update(
            refined_visits=len(windows),
            joint_trials=int(output.get('joint_trial_count', 0)),
            source_candidates=len(output.get('source_candidates', [])),
            retained_candidates=len(output.get('candidates', [])))
        output['planet_search_performance'] = performance.serialise(
            total_planet_stage=time.perf_counter()-search_started)

    def prediction(name, date):
        return _visible_projection(camera, vector_function(name, np.atleast_1d(date)), zenith)[0]

    def refine(assignments, start, stop, *, all_options=False):
        def objective(offset):
            total = 0.
            for name, source in assignments:
                # A flat invalid-visibility penalty can hide a brief visible
                # passage. Minimise the actual positional residual first.
                predicted = _project(camera, vector_function(name, [start+offset]))[0]
                if not np.isfinite(predicted).all():
                    return 1e100
                total += float(np.sum((predicted-xy[source])**2))
            return total
        optimum = minimize_scalar(objective, bounds=(0., stop-start), method='bounded',
                                  options={'xatol': 1e-7})
        offsets = [0., float(optimum.x), stop-start]
        # If the unconstrained minimum is below the horizon, the constrained
        # minimum may be at a rise/set crossing. Retain these boundaries too.
        for name, _ in assignments:
            def altitude(offset):
                return float(_altitudes(vector_function(name, [start+offset]), zenith)[0])
            for left, right in zip(offsets[:2], offsets[1:3]):
                if altitude(left)*altitude(right) < 0:
                    crossing = brentq(altitude, left, right, xtol=1e-9)
                    offsets.extend([max(0., crossing-1e-7), crossing,
                                    min(stop-start, crossing+1e-7)])
        options = [(offset, objective(offset)) for offset in offsets
                   if all(np.isfinite(prediction(name, start+offset)).all()
                          for name, _ in assignments)]
        if all_options:
            return [(start+offset, cost) for offset, cost in options]
        if not options:
            return start+float(optimum.x), float('inf')
        offset, cost = min(options, key=lambda item: item[1])
        return start+offset, cost

    # Refine individual passages without choosing a planet identity or date.
    def gate_interval(name, source, date, first, last):
        def excess(t):
            value = float(np.sum((prediction(name, t)-xy[source])**2)-source_gate2[source])
            return value if np.isfinite(value) else 1e100
        bounds = []
        for end in (first, last):
            # Find the first gate crossing on either side, preserving separate
            # visits even when a loop's two minima share one coarse window.
            sample = np.r_[date, np.linspace(date, end, max(2, int(abs(end-date)/.5)+2))[1:]]
            residuals = np.sum((_visible_projection(camera, vector_function(name, sample), zenith)-xy[source])**2, axis=1)-source_gate2[source]
            residuals[~np.isfinite(residuals)] = 1e100
            outside = np.flatnonzero(residuals > 0)
            if len(outside):
                k = outside[0]
                if k == 0:
                    bounds.append(date)
                else:
                    bounds.append(float(brentq(excess, min(sample[k-1], sample[k]), max(sample[k-1], sample[k]), xtol=1e-8)))
            else:
                bounds.append(float(end))
        return bounds

    individual_started = time.perf_counter()
    grouped = {name: [] for name in names}
    for name, source, start, stop, visit_start, visit_stop in windows:
        grouped[name].append(Visit(name, source, start, stop, visit_start, visit_stop))
    groups = sum(bool(value) for value in grouped.values())
    workers_used = min(int(planet_workers), groups) if groups else 1
    if workers_used <= 0:
        raise ValueError('Planet worker count must be a positive integer')
    results = refine_all_planets(
        grouped, RefinementContext(camera=camera, xy=xy, zenith=zenith),
        (jd, tracks, authoritative_function), workers=workers_used)
    for result in results:
        for key, value in result.counters.items():
            worker_counters[key] += value
        worker_timings.append({'planet': result.name, **result.timings})

    passages = []
    visit_index = 0
    for result in results:
        for visit, minimum in zip(grouped[result.name], result.passages):
            name, source = visit.name, visit.source
            start, stop = visit.start, visit.stop
            visit_start, visit_stop = visit.visit_start, visit.visit_stop
            local = []
            by_date = {option[0]: option for option in minimum.options}
            options = [by_date[date] for date in sorted(by_date)]
            # Preserve exact rise/set boundary options around an invisible minimum.
            def altitude(date):
                return float(_altitudes(vector_function(name, [date]), zenith)[0])
            for left_option, right_option in zip(options[:-1], options[1:]):
                left, right = left_option[0], right_option[0]
                left_altitude, right_altitude = left_option[2], right_option[2]
                if left_altitude*right_altitude < 0:
                    crossing = brentq(altitude, left, right, xtol=1e-9)
                    for date in (max(start, crossing-1e-7), crossing,
                                 min(stop, crossing+1e-7)):
                        predicted = prediction(name, date)
                        cost = float(np.sum((predicted-xy[source])**2))
                        options.append((date, cost, altitude(date),
                                        bool(np.isfinite(predicted).all())))
            for date, cost, _, is_visible in options:
                if not is_visible:
                    continue
                if cost > source_gate2[source]:
                    continue
                interval = gate_interval(name, source, date, visit_start, visit_stop)
                passage = (date, name, source, cost, interval)
                # Keep one optimum per connected visible acceptance interval. Two
                # rise/set sides separated by an invisible gap remain alternatives.
                connected = [i for i, old in enumerate(local)
                             if min(interval[1], old[4][1]) >= max(interval[0], old[4][0])]
                if connected:
                    passage = min([passage]+[local[i] for i in connected], key=lambda p: p[3])
                    local = [old for i, old in enumerate(local) if i not in connected]
                local.append(passage)
            passages.extend(local)
            visit_index += 1
            if visit_index % 100 == 0:
                print(f'Blind planets: {visit_index}/{len(windows)} visits refined', flush=True)
    output['refined_visit_count'] = len(windows)
    individual_seconds = time.perf_counter()-individual_started
    output['source_candidates'] = [dict(planet=name.title(), detection_id=int(detections[source]['detection_id']),
        jd_tdb=float(date), epoch_tdb=_date_text(date), separation_px=float(np.sqrt(cost)))
        for date, name, source, cost, interval in passages]
    if not passages:
        output['reason'] = 'No competitive positional planet match survived the source and catalogue checks'
        record_performance()
        return output

    def assign(date, forced=()):
        predictions = np.array([prediction(name, date) for name in names])
        distance2 = np.sum((predictions[:, None, :]-xy[None, :, :])**2, axis=2)
        distance2[~np.isfinite(distance2)] = 1e100
        # Dummy columns allow unmatched planets; cardinality dominates residual.
        costs = np.full((len(names), len(xy)+len(names)), 1.)
        costs[:, :len(xy)] = np.where(distance2 <= source_gate2[None, :],
                                      distance2/((len(names)+1)*gate_px**2), 1e6)
        for name, source in forced:
            row = names.index(name)
            if distance2[row, source] > source_gate2[source]*(1+1e-8):
                return []
            costs[row, :] = 1e6
            costs[:, source] = 1e6
            costs[row, source] = -1.
        planets, sources = linear_sum_assignment(costs)
        return [(names[p], int(s)) for p, s in zip(planets, sources)
                if s < len(xy) and distance2[p, s] <= source_gate2[s]*(1+1e-8)]

    joint_started = time.perf_counter()
    candidates = []
    brightness_order = sorted(range(len(detections)), key=lambda i: float(detections[i].get('flux_above_background', 0)), reverse=True)
    rank = {source: i+1 for i, source in enumerate(brightness_order)}
    seeds = [(date, ((name, source),), interval) for date, name, source, _, interval in passages]
    # Every intersection of acceptance windows is sampled, even when no single
    # planet's closest approach lies in that intersection. Force each participating
    # planet/source pair in turn so competing source identities remain available.
    events = sorted({t for _, _, _, _, interval in passages for t in interval})
    for left, right in zip(events[:-1], events[1:]):
        date = (left+right)/2
        active = [(name, source) for _, name, source, _, interval in passages
                  if interval[0] < date < interval[1]]
        if len({name for name, _ in active}) > 1 and len({source for _, source in active}) > 1:
            for pair in set(active):
                seeds.append((date, (pair,), (left, right)))
    output['joint_trial_count'] = len(seeds)
    for trial_index, (date, forced, interval) in enumerate(seeds):
        assignments = assign(date, forced)
        if not assignments:
            continue
        if len(assignments) > 1:
            # Keep the returned date optimal for the actual returned membership.
            # Reassociate only between refits; never swap membership after the
            # final fit. If it does not stabilise, keep the fitted assignment.
            def common_interval(membership, trial_date):
                spans = []
                for name, source in membership:
                    connected = [span for _, n, i, _, span in passages
                                 if n == name and i == source and span[0]-1e-7 <= trial_date <= span[1]+1e-7]
                    spans.append((min(x[0] for x in connected), max(x[1] for x in connected))
                                 if connected else tuple(interval))
                return max(jd[0], max(x[0] for x in spans)), min(jd[-1], min(x[1] for x in spans))
            start, stop = common_interval(assignments, date)
            for _ in range(6):
                refined_date, _ = refine(assignments, start, stop)
                if all(np.sum((prediction(n, refined_date)-xy[i])**2) <= source_gate2[i]*(1+1e-8)
                       for n, i in assignments):
                    date = refined_date
                else:
                    break
                updated = assign(date, forced)
                if set(updated) == set(assignments) or len(updated) < len(assignments):
                    break
                assignments = updated
                start, stop = common_interval(assignments, date)
            else:
                date, _ = refine(assignments, start, stop)
        if (trial_index+1) % 100 == 0:
            print(f'Blind planets: {trial_index+1}/{len(seeds)} joint date trials', flush=True)
        if any(not np.isfinite(prediction(n, date)).all() or np.sum((prediction(n, date)-xy[i])**2) > source_gate2[i]*(1+1e-8) for n, i in assignments):
            continue
        matches, speed_squared = [], 0.
        for name, source in assignments:
            predicted = prediction(name, date)
            # The local derivative is geometric, even at a visibility boundary.
            nearby = _project(camera, vector_function(name, [date-.001, date+.001]))
            speed = (nearby[1]-nearby[0])/.002
            speed_squared += float(speed@speed)
            row = detections[source]
            matches.append(dict(planet=name.title(), detection_id=int(row['detection_id']),
                measured_x_px=float(xy[source, 0]), measured_y_px=float(xy[source, 1]),
                predicted_x_px=float(predicted[0]), predicted_y_px=float(predicted[1]),
                separation_px=float(np.linalg.norm(predicted-xy[source])),
                saturated=str(row.get('saturated', False)).lower() == 'true',
                source_class=row.get('source_class', 'unknown'),
                measured_altitude_deg=float(max(0., measured_altitudes[source])),
                predicted_altitude_deg=float(max(0., _altitudes(vector_function(name, [date]), zenith)[0])),
                catalogue_star_id=row.get('catalogue_star_id'),
                catalogue_residual_px=(float(star_residual[source]) if np.isfinite(star_residual[source]) else None),
                improvement_over_star_chi2=(float((star_residual[source]**2-np.sum((predicted-xy[source])**2))/positional_sigma_px**2)
                                            if np.isfinite(star_residual[source]) else None),
                unused_brightness_rank=rank[source],
                flux_above_background=float(row.get('flux_above_background', 0))))
        if not matches:
            continue
        cost = sum(m['separation_px']**2 for m in matches)
        candidate = dict(jd_tdb=float(date), epoch_tdb=_date_text(date), matches=matches,
                         match_count=len(matches), cost_px2=cost,
                         rms_px=float(np.sqrt(cost/len(matches))),
                         conditional_time_sigma_minutes=(float(1440*positional_sigma_px/np.sqrt(speed_squared))
                                                         if speed_squared > 1e-16 else None),
                         boundary_limited=bool(date-jd[0] < 1e-5 or jd[-1]-date < 1e-5))
        identity = {(m['planet'], m['detection_id']) for m in matches}
        duplicate = next((c for c in candidates if abs(c['jd_tdb']-date) < 1e-4 and
                          {(m['planet'], m['detection_id']) for m in c['matches']} == identity), None)
        if duplicate is None:
            candidates.append(candidate)
        elif cost < duplicate['cost_px2']:
            duplicate.update(candidate)
    candidates.sort(key=lambda c: (-c['match_count'], c['cost_px2'], c['jd_tdb']))
    if not candidates:
        record_performance(time.perf_counter()-joint_started)
        return output
    best = candidates[0]
    peers = [c for c in candidates if c['match_count'] == best['match_count'] and
             c['cost_px2'] <= best['cost_px2']+9*positional_sigma_px**2]
    ambiguous = (best['match_count'] < 2 or len(peers) > 1 or best['boundary_limited']
                 or zenith_status != 'conditional_zenith'
                 or min(m['predicted_altitude_deg'] for m in best['matches']) < .01)
    output.update(status='planet_epoch_ambiguous' if ambiguous else 'conditional_planet_epoch',
                  confidence='ambiguous_positional_candidates' if ambiguous else 'conditional_multiple_planets',
                  candidates=candidates, matches=best['matches'], match_count=best['match_count'],
                  candidate_count=len(candidates), competing_candidates=len(peers)-1,
                  best_candidate_jd_tdb=best['jd_tdb'], best_candidate_epoch_tdb=best['epoch_tdb'],
                  rms_px=best['rms_px'], conditional_time_sigma_minutes=best['conditional_time_sigma_minutes'],
                  reason='Competing dates/identities remain; no unique planetary epoch' if ambiguous else
                         'Multiple measured sources give a conditional positional epoch; false-alarm probability uncalibrated')
    record_performance(time.perf_counter()-joint_started)
    return output


def predict_other_planets(camera, answer, vector_function):
    """Project unmatched planets at the fixed best candidate epoch, for display only."""
    if answer.get('status') == 'planet_epoch_not_identifiable':
        return []
    date = answer.get('best_candidate_jd_tdb')
    zenith = (answer.get('visibility') or {}).get('zenith_unit_vector')
    if not answer.get('matches') or date is None or zenith is None:
        return []
    zenith = np.asarray(zenith, dtype=float)
    zenith = zenith / np.linalg.norm(zenith)
    matched = {row['planet'].lower() for row in answer['matches']}
    rows = []
    for name in answer.get('searched_planets', []):
        if name.lower() in matched:
            continue
        vectors = vector_function(name.lower(), [date])
        point = _visible_projection(camera, vectors, zenith)[0]
        if np.isfinite(point).all():
            rows.append(dict(planet=name.title(), predicted_x_px=float(point[0]),
                             predicted_y_px=float(point[1]),
                             predicted_altitude_deg=float(_altitudes(vectors, zenith)[0]),
                             jd_tdb=float(date), epoch_tdb=_date_text(date)))
    return rows


def fit_blind_planet_epoch(image_path, solution, result, *, epoch_limits=(1850., 2036.), gate_px=3.):
    """Search positions, check local bright-planet absences, then select and plot."""
    from point_star_planet_ephemeris import load_ephemeris, planet_vectors
    from point_star_planet_refinement import planet_worker_count
    from point_star_report import _camera_from_result
    planet_stage_started = time.perf_counter()
    output = Path(solution)
    with (output/'dots/star_candidates.csv').open() as handle:
        detections = list(csv.DictReader(handle))
    with (output/'star_coordinates.csv').open() as handle:
        used = {row['detection_id']: row for row in csv.DictReader(handle)}
    for row in detections:
        if row['detection_id'] in used:
            star = used[row['detection_id']]
            row.update(catalogue_star_id=star['star_id'], catalogue_residual_px=float(star['residual_px']))
    from point_star_time_bounds import capture_time_ceiling
    ceiling = result.get('causal_epoch_ceiling') or capture_time_ceiling()
    zenith_path = output/'photometric_zenith.json'
    photometric_zenith = json.loads(zenith_path.read_text()) if zenith_path.is_file() else {}
    jd, grid, provenance = load_ephemeris(*epoch_limits)
    # Patched/local callables used by tests and embedders stay on the serial
    # reference path; the shipped module function is safe for process workers.
    parallel_safe = getattr(planet_vectors, '__module__', '') == 'point_star_planet_ephemeris'
    workers = planet_worker_count(nonempty_groups=len(grid)) if parallel_safe else 1
    answer = search_planet_epochs(_camera_from_result(result), detections, jd, grid, planet_vectors,
                                 gate_px=gate_px, positional_sigma_px=max(float(result['fit']['rms_px']), .5),
                                 zenith_unit_vector=photometric_zenith.get('zenith_unit_vector'),
                                 zenith_status=photometric_zenith.get('status', 'unresolved'),
                                 latest_jd_tdb=ceiling['jd_tdb'], planet_workers=workers)
    answer['causal_epoch_ceiling'] = ceiling
    answer['ephemeris'] = provenance
    from point_star_planet_nondetections import check_candidate_absences, write_evidence
    evidence_started = time.perf_counter()
    post_search_counts = {'exact_calls': 0, 'exact_dates': 0}
    def counted_planet_vectors(name, dates):
        values = np.atleast_1d(dates)
        post_search_counts['exact_calls'] += 1
        post_search_counts['exact_dates'] += len(values)
        return planet_vectors(name, values)
    answer = check_candidate_absences(image_path, answer, _camera_from_result(result),
                                     detections, list(used.values()), counted_planet_vectors,
                                     valid_mask=_load_sky_footprint(output))
    evidence_seconds = time.perf_counter()-evidence_started
    write_evidence(output, answer)
    answer['predicted_planets'] = predict_other_planets(
        _camera_from_result(result), answer, counted_planet_vectors)
    identities = {}
    for candidate in answer['source_candidates']:
        identities.setdefault(candidate['detection_id'], set()).add(candidate['planet'])
    answer['source_identity_alternatives'] = {str(key): sorted(value) for key, value in identities.items()}
    answer['candidate_selection'] = 'nonnegative measured/predicted altitude relative to photometric zenith and valid detector projection; all measured detections considered; a matched star may be challenged only with positional delta chi-square >=9; saturated/broad sources retained'
    performance = answer.get('planet_search_performance')
    if performance is not None:
        for key, value in post_search_counts.items():
            performance['providers'][key] += value
        performance['cache'] = {
            'source': provenance.get('cache_source'),
            'path': provenance.get('cache_path'),
            'bytes': provenance.get('cache_bytes'),
            'digest': provenance.get('content_sha256'),
            'build_seconds': float(provenance.get('cache_build_seconds', 0.)),
        }
        performance['seconds']['cache_load'] = float(provenance.get('cache_load_seconds', 0.))
        performance['seconds']['negative_evidence'] = float(evidence_seconds)
        performance['seconds']['total_planet_stage'] = float(time.perf_counter()-planet_stage_started)
        provider_counts = performance['providers']
        seconds = performance['seconds']
        print('Planet performance: '
              f"total {seconds['total_planet_stage']:.2f} s; "
              f"cache {seconds['cache_load']:.2f} s ({performance['cache']['source']}); "
              f"coarse {seconds['coarse_scan']:.2f} s; "
              f"refine {seconds['individual_refinement']:.2f} s; "
              f"exact {provider_counts['exact_calls']} calls/{provider_counts['exact_dates']} dates; "
              f"workers {performance['workers']['used']}.", flush=True)
    (output/'planet_epoch.json').write_text(json.dumps(answer, indent=2, allow_nan=False)+'\n')
    if performance is not None:
        (output/'planet_search_performance.json').write_text(
            json.dumps(performance, indent=2, allow_nan=False)+'\n')
    fields = ['candidate_rank', 'positional_rank', 'missing_bright_planets', 'epoch_tdb', 'match_count', 'rms_px', 'planet', 'detection_id',
              'measured_x_px', 'measured_y_px', 'predicted_x_px', 'predicted_y_px', 'separation_px',
              'saturated', 'source_class', 'unused_brightness_rank', 'flux_above_background',
              'catalogue_star_id', 'catalogue_residual_px', 'improvement_over_star_chi2',
              'measured_altitude_deg', 'predicted_altitude_deg']
    with (output/'planet_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for rank, candidate in enumerate(answer['candidates'], 1):
            for match in candidate['matches']:
                writer.writerow(dict(candidate_rank=rank, positional_rank=candidate['positional_rank'],
                                     missing_bright_planets=';'.join(candidate['missing_bright_planets']),
                                     epoch_tdb=candidate['epoch_tdb'],
                                     match_count=candidate['match_count'], rms_px=candidate['rms_px'], **match))
    with (output/'planet_source_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=['planet', 'detection_id', 'jd_tdb', 'epoch_tdb', 'separation_px'])
        writer.writeheader(); writer.writerows(answer['source_candidates'])
    with (output/'planet_visibility.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=['detection_id', 'x_px', 'y_px', 'altitude_deg', 'visible', 'rejection_reason'])
        writer.writeheader(); writer.writerows(answer.get('visibility_sources', []))
    write_epoch_diagnostics(output, answer)
    _plot_candidates(image_path, output, answer)
    return answer


def _plot_candidates(image_path, output, answer):
    from PIL import Image
    import matplotlib.pyplot as plt
    from point_star_plotting import save_png
    fig, ax = plt.subplots(figsize=(10, 9))
    ax.imshow(Image.open(image_path))
    for row in answer['matches']:
        x, y = row['measured_x_px'], row['measured_y_px']
        ax.plot(x, y, '*', mfc='none', mec='magenta', mew=1.4, ms=12)
        ax.annotate(row['planet'], (x, y), xytext=(7, 7), textcoords='offset points', color='white',
                    bbox=dict(fc='black', alpha=.7))
    from point_star_report import _draw_predicted_planets
    prediction_handle = _draw_predicted_planets(ax, answer.get('predicted_planets', []))
    if prediction_handle is not None:
        ax.legend(handles=[prediction_handle], loc='lower left', fontsize=8)
    ax.set_title('Blind planet candidates: '+answer['status'].replace('_', ' ')+'\n'+
                 (answer.get('best_candidate_epoch_tdb') or 'No supported candidate')+'; alternatives in planet_candidates.csv')
    ax.axis('off'); fig.tight_layout()
    save_png(fig, output/'planet_candidates.png', dpi=180); plt.close(fig)


def write_epoch_diagnostics(output, answer):
    """Print every retained epoch and plot its identity/residual/local precision."""
    from astropy.time import Time
    import matplotlib.pyplot as plt
    from point_star_plotting import save_png
    output = Path(output)
    candidates = answer.get('candidates', [])
    lines = [f"Blind planetary epoch candidates: {len(candidates)} ({answer['status']})",
             'Fit rank | Candidate epoch (TDB)       | Planet/source                   | RMS px | local sigma (h) | Missing bright planets']
    if answer.get('visibility'):
        visible = answer['visibility']
        lines.insert(1, f"Visibility: altitude >=0 degrees using {visible['source']} ({visible['zenith_status']}); {visible.get('rejected_below_horizon_count', 0)} below-horizon detections rejected.")
    if answer.get('causal_epoch_ceiling'):
        lines.insert(1, f"Causal latest epoch: {answer['causal_epoch_ceiling'].get('utc', answer['causal_epoch_ceiling']['jd_tdb'])} (run clock, not image metadata).")
    ranked = sorted(enumerate(candidates, 1), key=lambda item: item[1]['jd_tdb'])
    for rank, candidate in ranked:
        bodies = ', '.join(f"{m['planet']} #{m['detection_id']}" for m in candidate['matches'])
        sigma = candidate.get('conditional_time_sigma_minutes')
        sigma_text = f'{sigma/60:.2f}' if sigma is not None else 'unresolved'
        lines.append(f"{rank:8d} | {candidate['epoch_tdb']:27s} | {bodies:31s} | {candidate['rms_px']:6.3f} | {sigma_text} | {', '.join(candidate.get('missing_bright_planets', [])) or '--'}")
    if answer.get('negative_evidence'):
        lines.append('Candidates with missing bright planets rank below uncontradicted trials; unknown detectability is neutral. See planet_non_detections.json.')
    lines.append('Local sigma excludes alternative dates and model systematics; smallest residual is not an identification.')
    text = '\n'.join(lines)+'\n'
    (output/'planet_epoch_candidates.txt').write_text(text)
    print(text, flush=True)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    labels = sorted({' / '.join(m['planet'] for m in c['matches']) for c in candidates})
    for label in labels:
        group = [c for c in candidates if ' / '.join(m['planet'] for m in c['matches']) == label]
        years = Time([c['jd_tdb'] for c in group], format='jd', scale='tdb').jyear
        uncertainty = np.array([(c.get('conditional_time_sigma_minutes') or 0.)/(1440*365.25) for c in group])
        ax.errorbar(years, [c['rms_px'] for c in group], xerr=uncertainty,
                    fmt='o', ms=4, capsize=2, alpha=.8, label=label)
    if candidates:
        ax.legend(fontsize=8)
    else:
        ax.text(.5, .5, 'No competitive planet/date candidate', ha='center', transform=ax.transAxes)
    ax.set(xlabel='Candidate epoch (Julian year, TDB)', ylabel='Positional RMS (pixels)',
           title=f"Blind planetary dates: {len(candidates)} retained candidates\n{answer['status'].replace('_', ' ')}")
    ax.grid(alpha=.25)
    fig.text(.5, .01, 'Horizontal bars: conditional local 1-sigma only; global date/identity ambiguities remain.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .035, 1, 1))
    save_png(fig, output/'planet_epoch_candidates.png', dpi=190)
    plt.close(fig)
