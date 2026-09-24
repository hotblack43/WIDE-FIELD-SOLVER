"""Planet/date candidates for blind or explicitly metadata-conditioned searches."""
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


def _angular_separation_matrix_arcmin(first, second):
    """Pairwise great-circle separations between unit-vector rows."""
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    dots = np.clip(first @ second.T, -1., 1.)
    return np.rad2deg(np.arccos(dots))*60.


def _paired_angular_separations_arcmin(first, second):
    """Great-circle separations between corresponding unit-vector rows."""
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    dots = np.clip(np.sum(first*second, axis=-1), -1., 1.)
    return np.rad2deg(np.arccos(dots))*60.


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
                         gate_arcmin=30., positional_sigma_arcmin=3., zenith_unit_vector=None,
                         zenith_status='conditional_zenith', zenith_source='photometric_extinction',
                         latest_jd_tdb=None,
                         planet_workers=1, solar_constraint=None,
                         search_label='Blind planets'):
    """Search trajectory segments, refine dates and retain competing assignments.

    Inputs are measured detections, a fitted camera and reference ephemerides only.
    A single planet never establishes a unique epoch. Multi-planet candidates also
    remain conditional: ranking is positional and not a false-alarm probability.
    """
    search_started = time.perf_counter()
    jd = np.asarray(jd_grid, dtype=float)
    if len(jd) < 2 or not np.isfinite(jd).all() or np.any(np.diff(jd) <= 0):
        raise ValueError('Planet search needs increasing finite reference dates')
    if gate_arcmin <= 0 or positional_sigma_arcmin <= 0:
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
                  tested_sources=len(detections), gate_arcmin=gate_arcmin,
                  star_competition_delta_chi2=9.,
                  positional_sigma_arcmin=positional_sigma_arcmin,
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
        output.update(status='visibility_unresolved',
                      reason='No image-derived zenith; planet visibility cannot be checked')
        _record_empty_performance(output, search_started, planet_workers)
        return output
    zenith = np.asarray(zenith_unit_vector, dtype=float)
    if zenith.shape != (3,) or not np.isfinite(zenith).all() or np.linalg.norm(zenith) < 1e-12:
        raise ValueError('Planet visibility needs a finite nonzero zenith vector')
    zenith = zenith/np.linalg.norm(zenith)
    visibility_source = ('investigator-assumed image-centre zenith'
                         if zenith_source == 'image_centre_assumption' else
                         'image-derived centred full-horizon geometry'
                         if zenith_source == 'centred_full_horizon_geometry'
                         else 'image-derived photometric extinction zenith')
    output['visibility'] = dict(source=visibility_source, zenith_source=zenith_source,
                                zenith_status=zenith_status,
                                zenith_unit_vector=zenith.tolist(), minimum_altitude_deg=0.,
                                horizon_roundoff_tolerance_deg=1e-7)
    if not detections or not names:
        output['reason'] = 'No measured sources or reference planets'
        _record_empty_performance(output, search_started, planet_workers)
        return output
    xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in detections])
    if not np.isfinite(xy).all():
        raise ValueError('Planet sources need finite measured detector positions')
    star_residual = np.array([
        float(row.get('catalogue_residual_arcmin', np.inf)) for row in detections])
    star_residual_px = np.array([
        float(row.get('catalogue_residual_px', np.inf)) for row in detections])
    # A catalogue match is an alternative explanation, not an irreversible veto.
    # Associated sources need a >=9 improvement in positional chi-square before
    # they can count toward a planet hypothesis; all flags remain in the exports.
    source_gate2 = np.minimum(
        gate_arcmin**2, star_residual**2-9*positional_sigma_arcmin**2)
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
    # Search on the sphere, avoiding off-detector projection folds. A 0.1-degree
    # daily curvature guard exceeds measured Mercury curvature in the reference
    # ephemeris tests; exact ephemerides set the final great-circle gate.
    gate_chord = 2*np.sin(np.deg2rad(gate_arcmin/60.)/2.)
    angular_gate = gate_chord + np.deg2rad(.1)
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
    print(f'{search_label}: refining {len(windows)} positional visits across the date interval', flush=True)

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

    def angular_residual_arcmin(name, date, source):
        ray = np.asarray(vector_function(name, [date]), dtype=float)
        return float(_paired_angular_separations_arcmin(
            ray, measured_rays[source:source+1])[0])

    def refine(assignments, start, stop, *, all_options=False):
        def objective(offset):
            total = 0.
            for name, source in assignments:
                # A flat invalid-visibility penalty can hide a brief visible
                # passage. Minimise the actual positional residual first.
                predicted = _project(camera, vector_function(name, [start+offset]))[0]
                if not np.isfinite(predicted).all():
                    return 1e100
                total += angular_residual_arcmin(name, start+offset, source)**2
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
            if not np.isfinite(prediction(name, t)).all():
                return 1e100
            value = angular_residual_arcmin(name, t, source)**2-source_gate2[source]
            return value if np.isfinite(value) else 1e100
        bounds = []
        for end in (first, last):
            # Find the first gate crossing on either side, preserving separate
            # visits even when a loop's two minima share one coarse window.
            sample = np.r_[date, np.linspace(date, end, max(2, int(abs(end-date)/.5)+2))[1:]]
            vectors = vector_function(name, sample)
            points = _visible_projection(camera, vectors, zenith)
            residuals = (_paired_angular_separations_arcmin(
                vectors, np.repeat(measured_rays[source][None, :], len(sample), axis=0))**2
                - source_gate2[source])
            residuals[~np.isfinite(points).all(axis=1)] = 1e100
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
                        cost = angular_residual_arcmin(name, date, source)**2
                        options.append((date, cost, altitude(date),
                                        bool(np.isfinite(predicted).all())))
            for date, cost, _, is_visible in options:
                if not is_visible:
                    continue
                cost = angular_residual_arcmin(name, date, source)**2
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
                print(f'{search_label}: {visit_index}/{len(windows)} visits refined', flush=True)
    output['refined_visit_count'] = len(windows)
    individual_seconds = time.perf_counter()-individual_started
    output['source_candidates'] = [dict(
        planet=name.title(), detection_id=int(detections[source]['detection_id']),
        jd_tdb=float(date), epoch_tdb=_date_text(date),
        separation_px=float(np.linalg.norm(prediction(name, date)-xy[source])),
        separation_arcmin=float(np.sqrt(cost)))
        for date, name, source, cost, interval in passages]
    if not passages:
        output['reason'] = 'No competitive positional planet match survived the source and catalogue checks'
        record_performance()
        return output

    def assign(date, forced=()):
        predictions = np.array([prediction(name, date) for name in names])
        planet_rays = np.array([vector_function(name, [date])[0] for name in names])
        distance2 = _angular_separation_matrix_arcmin(planet_rays, measured_rays)**2
        distance2[~np.isfinite(predictions).all(axis=1), :] = 1e100
        distance2[~np.isfinite(distance2)] = 1e100
        # Dummy columns allow unmatched planets; cardinality dominates residual.
        costs = np.full((len(names), len(xy)+len(names)), 1.)
        costs[:, :len(xy)] = np.where(distance2 <= source_gate2[None, :],
                                      distance2/((len(names)+1)*gate_arcmin**2), 1e6)
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

    def recruit_constellation(date, anchors):
        """Enumerate compatible Gaia overrides behind a two-planet date anchor."""
        if len(anchors) < 2:
            return []
        anchored_planets = {name for name, _ in anchors}
        anchored_sources = {source for _, source in anchors}
        remaining_planets = [name for name in names if name not in anchored_planets]
        override_sources = [source for source in range(len(xy))
                            if source not in anchored_sources and visible[source]
                            and not eligible[source] and np.isfinite(star_residual[source])]
        if not remaining_planets or not override_sources:
            return []
        predictions = np.array([prediction(name, date) for name in remaining_planets])
        planet_rays = np.array([
            vector_function(name, [date])[0] for name in remaining_planets])
        distance2 = _angular_separation_matrix_arcmin(
            planet_rays, measured_rays[override_sources])**2
        distance2[~np.isfinite(predictions).all(axis=1), :] = 1e100
        # The anchor-only date can place a faster third planet farther from its
        # source than the Gaia alternative. Admit ordinary-gate proposals here;
        # assignment_is_valid applies the Gaia comparison after the common epoch
        # has been refitted with the complete constellation.
        valid = distance2 <= gate_arcmin**2
        choices = [[override_sources[column] for column in np.flatnonzero(valid[row])]
                   for row in range(len(remaining_planets))]
        memberships = []

        def enumerate_compatible(row, additions, used_sources):
            if row == len(remaining_planets):
                if additions:
                    memberships.append(list(anchors)+list(additions))
                return
            # A planet may remain unmatched. Exhaustive alternatives matter:
            # the closest source at the anchor-only date need not beat Gaia
            # after the common epoch is refitted.
            enumerate_compatible(row+1, additions, used_sources)
            name = remaining_planets[row]
            for source in choices[row]:
                if source not in used_sources:
                    enumerate_compatible(
                        row+1, additions+[(name, source)], used_sources | {source})

        enumerate_compatible(0, [], set(anchored_sources))
        return memberships

    def assignment_is_valid(name, source, date):
        predicted = prediction(name, date)
        if not np.isfinite(predicted).all():
            return False
        distance2 = angular_residual_arcmin(name, date, source)**2
        if eligible[source]:
            return distance2 <= source_gate2[source]*(1+1e-8)
        return (visible[source] and np.isfinite(star_residual[source]) and
                distance2 <= gate_arcmin**2*(1+1e-8) and
                distance2 < star_residual[source]**2)

    joint_started = time.perf_counter()
    candidates = []
    brightness_order = sorted(range(len(detections)), key=lambda i: float(detections[i].get('flux_above_background', 0)), reverse=True)
    rank = {source: i+1 for i, source in enumerate(brightness_order)}

    def retain_candidate(assignments, date, *, solar_boundary_refinement=False):
        if any(not assignment_is_valid(name, source, date)
               for name, source in assignments):
            return
        matches, speed_squared = [], 0.
        for name, source in assignments:
            predicted = prediction(name, date)
            # The local derivative is geometric, even at a visibility boundary.
            nearby_rays = vector_function(name, [date-.001, date+.001])
            speed = float(_paired_angular_separations_arcmin(
                nearby_rays[:1], nearby_rays[1:])[0]/.002)
            speed_squared += speed**2
            row = detections[source]
            separation_arcmin = angular_residual_arcmin(name, date, source)
            separation_px = float(np.linalg.norm(predicted-xy[source]))
            matches.append(dict(planet=name.title(), detection_id=int(row['detection_id']),
                measured_x_px=float(xy[source, 0]), measured_y_px=float(xy[source, 1]),
                predicted_x_px=float(predicted[0]), predicted_y_px=float(predicted[1]),
                separation_px=separation_px, separation_arcmin=separation_arcmin,
                saturated=str(row.get('saturated', False)).lower() == 'true',
                source_class=row.get('source_class', 'unknown'),
                measured_altitude_deg=float(max(0., measured_altitudes[source])),
                predicted_altitude_deg=float(max(0., _altitudes(vector_function(name, [date]), zenith)[0])),
                catalogue_star_id=row.get('catalogue_star_id'),
                catalogue_residual_px=(float(star_residual_px[source])
                                       if np.isfinite(star_residual_px[source]) else None),
                catalogue_residual_arcmin=(float(star_residual[source])
                                           if np.isfinite(star_residual[source]) else None),
                improvement_over_star_chi2=(float(
                    (star_residual[source]**2-separation_arcmin**2)/
                    positional_sigma_arcmin**2)
                                            if np.isfinite(star_residual[source]) else None),
                constellation_override=bool(not eligible[source]),
                unused_brightness_rank=rank[source],
                flux_above_background=float(row.get('flux_above_background', 0))))
        if not matches:
            return
        cost = sum(match['separation_arcmin']**2 for match in matches)
        cost_px = sum(match['separation_px']**2 for match in matches)
        # An enclosing interval for this connected positional hypothesis. Every
        # independently eligible anchor must remain inside its acceptance span;
        # recruited overrides can only shrink this interval, never enlarge it.
        spans = []
        for name, source in assignments:
            connected = [span for _, n, i, _, span in passages
                         if n == name and i == source and span[0]-1e-7 <= date <= span[1]+1e-7]
            if connected:
                spans.append((min(s[0] for s in connected), max(s[1] for s in connected)))
        interval = [min(date, max(s[0] for s in spans)), max(date, min(s[1] for s in spans))] if spans else [float(jd[0]), float(jd[-1])]
        candidate = dict(jd_tdb=float(date), epoch_tdb=_date_text(date), matches=matches,
                         positional_interval_jd_tdb=list(map(float, interval)),
                         solar_boundary_refinement=solar_boundary_refinement,
                         match_count=len(matches), cost_arcmin2=cost, cost_px2=cost_px,
                         constellation_override_count=sum(match['constellation_override'] for match in matches),
                         rms_px=float(np.sqrt(cost_px/len(matches))),
                         rms_arcmin=float(np.sqrt(cost/len(matches))),
                         conditional_time_sigma_minutes=(float(
                             1440*positional_sigma_arcmin/np.sqrt(speed_squared))
                                                         if speed_squared > 1e-16 else None),
                         boundary_limited=bool(date-jd[0] < 1e-5 or jd[-1]-date < 1e-5))
        identity = {(match['planet'], match['detection_id']) for match in matches}
        duplicate = next((existing for existing in candidates
                          if abs(existing['jd_tdb']-date) < 1e-4 and
                          {(match['planet'], match['detection_id'])
                           for match in existing['matches']} == identity), None)
        if duplicate is None:
            candidates.append(candidate)
        elif cost < duplicate['cost_arcmin2']:
            duplicate.update(candidate)

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
        expansions = []
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
                if all(angular_residual_arcmin(n, refined_date, i)**2 <=
                       source_gate2[i]*(1+1e-8)
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
            for expanded in recruit_constellation(date, assignments):
                expanded_date, _ = refine(expanded, start, stop)
                if any(not assignment_is_valid(n, i, expanded_date) for n, i in expanded):
                    continue
                expansions.append((expanded, expanded_date))
        if (trial_index+1) % 100 == 0:
            print(f'{search_label}: {trial_index+1}/{len(seeds)} joint date trials', flush=True)
        retain_candidate(assignments, date)
        for expanded, expanded_date in expansions:
            retain_candidate(expanded, expanded_date)
    if solar_constraint is not None and solar_constraint.active:
        source_indices = {int(row['detection_id']): i for i, row in enumerate(detections)}
        for candidate in list(candidates):
            evidence = solar_constraint.assess(candidate['jd_tdb'], candidate['positional_interval_jd_tdb'])
            if not evidence['requires_date_refinement']:
                continue
            assignments = [(m['planet'].lower(), source_indices[m['detection_id']]) for m in candidate['matches']]
            for first, last in solar_constraint.possible_intervals(candidate['positional_interval_jd_tdb']):
                for date, _ in refine(assignments, first, last, all_options=True):
                    exact = solar_constraint.assess(date)
                    if exact['status'] != 'solar_inconsistent':
                        retain_candidate(assignments, date, solar_boundary_refinement=True)
    candidates.sort(key=lambda c: (-c['match_count'], c['cost_arcmin2'], c['jd_tdb']))
    if not candidates:
        record_performance(time.perf_counter()-joint_started)
        return output
    best = candidates[0]
    peers = [c for c in candidates if c['match_count'] == best['match_count'] and
             c['cost_arcmin2'] <= best['cost_arcmin2']+9*positional_sigma_arcmin**2]
    from point_star_zenith import zenith_supports_visibility
    ambiguous = (best['match_count'] < 2 or len(peers) > 1 or best['boundary_limited']
                 or not zenith_supports_visibility(zenith_status, zenith_source)
                 or min(m['predicted_altitude_deg'] for m in best['matches']) < .01)
    output.update(status='planet_epoch_ambiguous' if ambiguous else 'conditional_planet_epoch',
                  confidence='ambiguous_positional_candidates' if ambiguous else 'conditional_multiple_planets',
                  candidates=candidates, matches=best['matches'], match_count=best['match_count'],
                  candidate_count=len(candidates), competing_candidates=len(peers)-1,
                  best_candidate_jd_tdb=best['jd_tdb'], best_candidate_epoch_tdb=best['epoch_tdb'],
                  rms_px=best['rms_px'], rms_arcmin=best['rms_arcmin'],
                  conditional_time_sigma_minutes=best['conditional_time_sigma_minutes'],
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


def associate_planets_at_metadata_time(camera, detections, planet_names,
                                       vector_function, metadata, *, gate_arcmin=30.,
                                       positional_sigma_arcmin=3.,
                                       zenith_unit_vector=None):
    """Associate measured sources at the supplied time without inferring an epoch."""
    empty = dict(status='metadata_time_unavailable', matches=[],
                 predicted_without_source=[])
    if metadata.get('status') != 'selected' or metadata.get('jd_tdb') is None:
        return empty
    if zenith_unit_vector is None:
        return dict(status='metadata_time_visibility_unresolved', matches=[],
                    predicted_without_source=[])
    zenith = np.asarray(zenith_unit_vector, dtype=float)
    if zenith.shape != (3,) or not np.isfinite(zenith).all() or np.linalg.norm(zenith) < 1e-12:
        raise ValueError('Metadata-time planet association needs a finite nonzero zenith vector')
    zenith /= np.linalg.norm(zenith)
    jd_tdb = float(metadata['jd_tdb'])
    height, width = camera.shape
    projected = []
    for name in planet_names:
        vectors = np.asarray(vector_function(name, [jd_tdb]), dtype=float)
        point = _visible_projection(camera, vectors, zenith)[0]
        altitude = float(_altitudes(vectors, zenith)[0])
        if (np.isfinite(point).all() and altitude >= -1e-7
                and 0 <= point[0] <= width-1 and 0 <= point[1] <= height-1):
            projected.append(dict(planet=str(name).title(), _name=str(name),
                                  _ray=vectors[0],
                                  predicted_x_px=float(point[0]),
                                  predicted_y_px=float(point[1]),
                                  predicted_altitude_deg=max(0., altitude),
                                  jd_tdb=jd_tdb, epoch_tdb=_date_text(jd_tdb)))
    if not projected:
        return dict(status='metadata_time_no_visible_planets', matches=[],
                    predicted_without_source=[], epoch_tdb=_date_text(jd_tdb),
                    epoch_source=metadata.get('source'), time_utc=metadata.get('time_utc'))
    xy = np.array([[float(row['x_px']), float(row['y_px'])]
                   for row in detections], dtype=float).reshape((-1, 2))
    star_residual = np.array([
        float(row.get('catalogue_residual_arcmin', np.inf)) for row in detections], dtype=float)
    source_gate2 = np.minimum(gate_arcmin**2,
                              star_residual**2-9*positional_sigma_arcmin**2)
    source_gate2[source_gate2 <= 0] = -1.
    planet_xy = np.array([[row['predicted_x_px'], row['predicted_y_px']]
                          for row in projected])
    if len(detections):
        measured_rays = camera.to_sky(xy)
        measured_altitudes = _altitudes(measured_rays, zenith)
        measured_visible = measured_altitudes >= -1e-7
        planet_rays = np.asarray([row['_ray'] for row in projected])
        distance_arcmin = _angular_separation_matrix_arcmin(planet_rays, measured_rays)
        distance2 = distance_arcmin**2
        distance2[:, ~measured_visible] = np.inf
        costs = np.full((len(projected), len(detections)+len(projected)), 1.)
        costs[:, :len(detections)] = np.where(
            distance2 <= source_gate2[None, :],
            distance2/((len(projected)+1)*gate_arcmin**2), 1e6)
        planet_indices, source_indices = linear_sum_assignment(costs)
        assignments = [(int(p), int(s)) for p, s in zip(planet_indices, source_indices)
                       if s < len(detections)
                       and distance2[p, s] <= source_gate2[s]*(1+1e-8)]
    else:
        distance2 = np.empty((len(projected), 0))
        assignments = []
    brightness = sorted(range(len(detections)),
                        key=lambda i: float(detections[i].get('flux_above_background', 0)),
                        reverse=True)
    rank = {source: index+1 for index, source in enumerate(brightness)}
    matches = []
    for planet_index, source_index in assignments:
        prediction = projected[planet_index]
        source = detections[source_index]
        residual = star_residual[source_index]
        matches.append(dict(
            planet=prediction['planet'], detection_id=int(source['detection_id']),
            measured_x_px=float(xy[source_index, 0]),
            measured_y_px=float(xy[source_index, 1]),
            predicted_x_px=prediction['predicted_x_px'],
            predicted_y_px=prediction['predicted_y_px'],
            separation_px=float(np.linalg.norm(
                planet_xy[planet_index]-xy[source_index])),
            separation_arcmin=float(np.sqrt(distance2[planet_index, source_index])),
            saturated=str(source.get('saturated', False)).lower() == 'true',
            source_class=source.get('source_class', 'unknown'),
            predicted_altitude_deg=prediction['predicted_altitude_deg'],
            measured_altitude_deg=float(measured_altitudes[source_index]),
            catalogue_star_id=source.get('catalogue_star_id'),
            catalogue_residual_px=(float(source['catalogue_residual_px'])
                                   if source.get('catalogue_residual_px') not in (None, '')
                                   else None),
            catalogue_residual_arcmin=(float(residual) if np.isfinite(residual) else None),
            unused_brightness_rank=rank[source_index],
            flux_above_background=float(source.get('flux_above_background', 0)),
            source_origin=source.get('source_origin', 'general_detection'),
            morphology_rejection_reason=source.get('morphology_rejection_reason'),
            association_status='metadata_time_match', jd_tdb=jd_tdb,
            epoch_tdb=prediction['epoch_tdb'], epoch_source=metadata.get('source')))
    matched_planets = {planet_index for planet_index, _ in assignments}
    predictions = [dict((key, value) for key, value in row.items() if not key.startswith('_'))
                   | {'association_status': 'predicted_no_detected_source',
                      'epoch_source': metadata.get('source')}
                   for index, row in enumerate(projected) if index not in matched_planets]
    return dict(status=('metadata_time_associated' if matches
                        else 'metadata_time_no_source_match'),
                matches=matches, predicted_without_source=predictions,
                epoch_tdb=_date_text(jd_tdb), epoch_source=metadata.get('source'),
                time_utc=metadata.get('time_utc'), gate_arcmin=float(gate_arcmin),
                positional_sigma_arcmin=float(positional_sigma_arcmin),
                method='exact ephemeris positions at supplied observation metadata time',
                limitation='Source identities are conditioned on supplied metadata; the image did not infer this epoch.')


def _targeted_peak_measurement(scientific, x, y):
    """Measure a detector-rejected peak without making it a stellar detection."""
    from scipy.ndimage import label
    x, y = int(round(float(x))), int(round(float(y)))
    half = 4
    if min(x, y, scientific.shape[1]-1-x, scientific.shape[0]-1-y) < half+1:
        return None
    gy, gx = np.mgrid[-half:half+1, -half:half+1]
    annulus = np.maximum(abs(gx), abs(gy)) == half
    cut = np.asarray(scientific.luminance[y-half:y+half+1, x-half:x+half+1], float)
    signal = cut-np.median(cut[annulus])
    peak = float(signal[half, half])
    component, _ = label(signal > max(0., .15*peak))
    centre = component[half, half]
    mask = component == centre if centre else np.zeros(signal.shape, bool)
    if mask.sum() < 1:
        return None
    weights = np.where(mask, np.maximum(signal, 0.), 0.)
    flux = float(weights.sum())
    if not np.isfinite(flux) or flux <= 0:
        return None
    cx = float((weights*gx).sum()/flux)
    cy = float((weights*gy).sum()/flux)
    dx, dy = gx-cx, gy-cy
    covariance = np.array([
        [(weights*dx*dx).sum(), (weights*dx*dy).sum()],
        [(weights*dx*dy).sum(), (weights*dy*dy).sum()],
    ])/flux
    _, major2 = np.linalg.eigvalsh(covariance)
    significant = 0
    for plane in scientific.planes.values():
        values = np.asarray(plane[y-half:y+half+1, x-half:x+half+1], float)
        border = values[annulus]
        noise = max(1.4826*float(np.median(abs(border-np.median(border)))), 1e-6)
        significant += values[half, half]-np.median(border) > 3*noise
    required = 1 if len(scientific.planes) == 1 else 2
    if significant < required:
        return None
    px, py = float(x+cx), float(y+cy)
    saturated_channels = [
        name for name, saturated in scientific.plane_saturated_masks.items()
        if np.any(saturated[y-half:y+half+1, x-half:x+half+1][mask])]
    return dict(
        x_px=px, y_px=py, flux_above_background=flux,
        peak_above_background=peak, area_px=int(mask.sum()),
        major_sigma_px=float(np.sqrt(max(major2, 0.))),
        saturated=bool(saturated_channels),
        saturation_known=bool(scientific.provenance()['saturation_known']),
        saturated_channels=','.join(saturated_channels),
        source_class='targeted_planet_recovery',
        measurement_half_window_px=half,
        significant_channels=int(significant),
        source_origin='metadata_predicted_recovery')


def recover_predicted_planet_sources(
        scientific, camera, predictions, detections, rejected_candidates,
        valid_mask, *, gate_arcmin=30.):
    """Recover strong multichannel peaks rejected only by stellar morphology."""
    if not predictions or not rejected_candidates:
        return []
    valid_mask = np.asarray(valid_mask, dtype=bool)
    if valid_mask.shape != scientific.luminance.shape:
        raise ValueError('Targeted recovery validity mask differs from image')
    rejected = []
    for row in rejected_candidates:
        if row.get('reason') not in ('too_sharp', 'too_small'):
            continue
        x, y = int(round(float(row['x_px']))), int(round(float(row['y_px'])))
        if (0 <= y < valid_mask.shape[0] and 0 <= x < valid_mask.shape[1]
                and valid_mask[y, x]):
            rejected.append(row)
    measured = []
    for row in rejected:
        source = _targeted_peak_measurement(scientific, row['x_px'], row['y_px'])
        if source is not None:
            source['morphology_rejection_reason'] = row['reason']
            duplicate = any(
                np.hypot(source['x_px']-float(accepted['x_px']),
                         source['y_px']-float(accepted['y_px'])) <
                max(1., float(source.get('major_sigma_px', .5))+
                    float(accepted.get('major_sigma_px', .5)))
                for accepted in detections)
            if not duplicate:
                measured.append(source)
    if not predictions or not measured:
        return []
    predicted_xy = np.array([[row['predicted_x_px'], row['predicted_y_px']]
                             for row in predictions], dtype=float)
    measured_xy = np.array([[row['x_px'], row['y_px']] for row in measured], dtype=float)
    distance = _angular_separation_matrix_arcmin(
        camera.to_sky(predicted_xy), camera.to_sky(measured_xy))
    costs = np.where(distance <= gate_arcmin, distance, 1e6)
    planet_indices, source_indices = linear_sum_assignment(costs)
    next_id = max([int(row['detection_id']) for row in detections] or [0])+1
    recovered = []
    for planet_index, source_index in zip(planet_indices, source_indices):
        if distance[planet_index, source_index] > gate_arcmin:
            continue
        source = measured[source_index]
        source.update(
            detection_id=str(next_id),
            recovery_planet=predictions[planet_index]['planet'],
            recovery_separation_arcmin=float(distance[planet_index, source_index]))
        recovered.append(source)
        next_id += 1
    return recovered


def associate_metadata_planets_with_recovery(
        scientific, camera, detections, rejected_candidates, valid_mask,
        planet_names, vector_function, metadata, *,
        gate_arcmin=30., positional_sigma_arcmin=3., zenith_unit_vector=None):
    """Associate ordinary detections, then reconsider only predicted rejected peaks."""
    association = associate_planets_at_metadata_time(
        camera, detections, planet_names, vector_function, metadata,
        gate_arcmin=gate_arcmin, positional_sigma_arcmin=positional_sigma_arcmin,
        zenith_unit_vector=zenith_unit_vector)
    recovered = recover_predicted_planet_sources(
        scientific, camera, association.get('predicted_without_source', []), detections,
        rejected_candidates, valid_mask,
        gate_arcmin=gate_arcmin)
    if recovered:
        association = associate_planets_at_metadata_time(
            camera, [*detections, *recovered], planet_names, vector_function, metadata,
            gate_arcmin=gate_arcmin, positional_sigma_arcmin=positional_sigma_arcmin,
            zenith_unit_vector=zenith_unit_vector)
    association['targeted_recovered_sources'] = len(recovered)
    return association, recovered


def append_recovered_source_photometry(output, scientific, recovered):
    """Append aperture/count-rate records for metadata-targeted recovered sources."""
    output = Path(output)
    path = output/'source_photometry.csv'
    if not recovered or not path.is_file():
        return []
    with path.open(newline='') as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        existing = list(reader)
    existing_ids = {str(row.get('detection_id')) for row in existing}
    if scientific.rgb is None:
        channel_data = {name: scientific.luminance for name in 'RGB'}
    else:
        channel_data = {name: scientific.rgb[..., index]
                        for index, name in enumerate('RGB')}
    for name in ('G1', 'G2'):
        if name in scientific.planes:
            channel_data[name] = scientific.planes[name].astype(float)
    if set(scientific.planes) == {'R', 'G1', 'G2', 'B'}:
        channel_masks = {
            'R': scientific.plane_saturated_masks['R'],
            'G': (scientific.plane_saturated_masks['G1'] |
                  scientific.plane_saturated_masks['G2']),
            'B': scientific.plane_saturated_masks['B'],
            'G1': scientific.plane_saturated_masks['G1'],
            'G2': scientific.plane_saturated_masks['G2'],
        }
    elif scientific.rgb is None:
        channel_masks = {name: scientific.plane_saturated_masks['L'] for name in 'RGB'}
    else:
        channel_masks = {name: scientific.plane_saturated_masks[name] for name in 'RGB'}
    exposure = scientific.provenance().get('exposure') or {}
    exposure_seconds = exposure.get('seconds') if exposure.get('status') == 'available' else None
    from point_star_photometry import measure_channel
    added = []
    for source in recovered:
        if str(source['detection_id']) in existing_ids:
            continue
        row = {field: '' for field in fields}
        row.update({
            'detection_id': str(source['detection_id']),
            'x_px': source['x_px'], 'y_px': source['y_px'],
            'star_id': '', 'identified_as_star': False,
            'source_class': source['source_class'],
            'saturated': source.get('saturated', False),
            'saturation_known': source.get(
                'saturation_known', scientific.provenance()['saturation_known']),
            'saturated_channels': source.get('saturated_channels', ''),
            'exposure_seconds': exposure_seconds if exposure_seconds is not None else '',
            'exposure_status': exposure.get('status', 'unavailable'),
            'exposure_source': exposure.get('source') or '',
        })
        aperture_radius = min(9., max(3., 2.5*float(source.get('major_sigma_px', 1.5))))
        for channel, pixels in channel_data.items():
            if f'{channel}_flux' not in fields:
                continue
            measured = measure_channel(
                pixels, scientific.valid_mask, channel_masks[channel],
                x=float(source['x_px']), y=float(source['y_px']),
                aperture_radius=aperture_radius, exposure_seconds=exposure_seconds)
            row[f'{channel}_flux'] = measured['aperture_counts_adu']
            prefix = f'{channel}_'
            for field in fields:
                if field.startswith(prefix) and field != f'{channel}_flux':
                    key = field[len(prefix):]
                    if key in measured:
                        row[field] = measured[key]
        existing.append(row)
        added.append(row)
        existing_ids.add(str(source['detection_id']))
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing)
    return added


def annotate_metadata_accuracy(answer):
    """Compare locally fitted planetary dates with the metadata reference time."""
    if not answer.get('metadata_used'):
        return answer
    metadata = answer.get('observation_time_metadata') or {}
    reference = metadata.get('jd_tdb')
    if reference is None:
        return answer
    reference = float(reference)
    for candidate in answer.get('candidates', []):
        candidate['metadata_offset_seconds'] = float(np.round(
            (float(candidate['jd_tdb'])-reference)*86400., 6))
    best = answer.get('best_candidate_jd_tdb')
    offset = (float(np.round((float(best)-reference)*86400., 6))
              if best is not None else None)
    answer['metadata_accuracy'] = dict(
        status=('local_planet_epoch_compared' if best is not None
                else 'no_supported_planet_epoch'),
        reference_time_utc=metadata.get('time_utc'),
        reference_source=metadata.get('source'),
        reference_jd_tdb=reference,
        fitted_planet_jd_tdb=(float(best) if best is not None else None),
        planet_minus_metadata_seconds=offset,
        absolute_timing_error_seconds=(abs(offset) if offset is not None else None),
        candidate_offsets_seconds=[candidate['metadata_offset_seconds']
                                   for candidate in answer.get('candidates', [])],
        limitation=('Timing accuracy is conditional on the metadata-supplied local interval; '
                    'it does not measure global blind date identifiability or ephemeris systematics.'))
    return answer


def _attach_identified_photometry(output, answer):
    """Join immutable detection measurements to star and planet identities."""
    output = Path(output)
    source_path = output/'source_photometry.csv'
    if not source_path.is_file():
        return []
    with source_path.open(newline='') as handle:
        reader = csv.DictReader(handle)
        source_fields = list(reader.fieldnames or [])
        source_rows = {row['detection_id']: row for row in reader}
    general = {'detection_id', 'x_px', 'y_px', 'star_id', 'identified_as_star',
               'source_class', 'saturated', 'saturation_known', 'saturated_channels'}
    measurement_fields = [name for name in source_fields if name not in general]
    for candidate in answer.get('candidates', []):
        for match in candidate.get('matches', []):
            measurement = source_rows.get(str(match['detection_id']))
            if measurement:
                for name in measurement_fields:
                    match[name] = measurement.get(name, '')
    # The selected matches normally alias a candidate's match dictionaries, but
    # update independently so that custom/test callers retain the same contract.
    for match in answer.get('matches', []):
        measurement = source_rows.get(str(match['detection_id']))
        if measurement:
            for name in measurement_fields:
                match[name] = measurement.get(name, '')
    for match in answer.get('metadata_matches', []):
        measurement = source_rows.get(str(match['detection_id']))
        if measurement:
            for name in measurement_fields:
                match[name] = measurement.get(name, '')
    selected = {(str(row['detection_id']), row['planet'])
                for row in answer.get('matches', [])}
    metadata_selected = {(str(row['detection_id']), row['planet'])
                         for row in answer.get('metadata_matches', [])}
    metadata_by_identity = {
        (str(row['detection_id']), row['planet']): row
        for row in answer.get('metadata_matches', [])}
    fields = ['identity_type', 'identity_name', 'identity_status',
              'candidate_rank', 'epoch_tdb', 'detection_id', 'x_px', 'y_px',
              'source_class', 'saturated', 'saturation_known',
              'saturated_channels', *measurement_fields]
    rows = []
    stars_path = output/'stellar_photometry.csv'
    if stars_path.is_file():
        with stars_path.open(newline='') as handle:
            for star in csv.DictReader(handle):
                source = source_rows.get(star['detection_id'], {})
                rows.append(dict(
                    identity_type='catalogue_star', identity_name=star.get('star_id', ''),
                    identity_status='catalogue_association', candidate_rank='', epoch_tdb='',
                    detection_id=star['detection_id'], x_px=source.get('x_px', ''),
                    y_px=source.get('y_px', ''), source_class=source.get('source_class', ''),
                    saturated=source.get('saturated', ''),
                    saturation_known=source.get('saturation_known', ''),
                    saturated_channels=source.get('saturated_channels', ''),
                    **{name: source.get(name, '') for name in measurement_fields}))
    written_planets = set()
    for rank, candidate in enumerate(answer.get('candidates', []), 1):
        for match in candidate.get('matches', []):
            identity = (str(match['detection_id']), match['planet'])
            source = source_rows.get(identity[0], {})
            written_planets.add(identity)
            rows.append(dict(
                identity_type=('minor_planet' if match['planet'].lower() in ('ceres', 'vesta')
                               else 'major_planet'),
                identity_name=match['planet'],
                identity_status=('metadata_time_match' if identity in metadata_selected
                                 else ('selected_planet_match' if identity in selected
                                       else 'planet_candidate')),
                candidate_rank=rank,
                epoch_tdb=(metadata_by_identity[identity].get('epoch_tdb', '')
                           if identity in metadata_by_identity
                           else candidate.get('epoch_tdb', '')),
                detection_id=identity[0], x_px=source.get('x_px', ''),
                y_px=source.get('y_px', ''), source_class=source.get('source_class', ''),
                saturated=source.get('saturated', ''),
                saturation_known=source.get('saturation_known', ''),
                saturated_channels=source.get('saturated_channels', ''),
                **{name: source.get(name, '') for name in measurement_fields}))
    for identity, match in metadata_by_identity.items():
        if identity in written_planets:
            continue
        source = source_rows.get(identity[0], {})
        rows.append(dict(
            identity_type=('minor_planet' if match['planet'].lower() in ('ceres', 'vesta')
                           else 'major_planet'),
            identity_name=match['planet'], identity_status='metadata_time_match',
            candidate_rank='', epoch_tdb=match.get('epoch_tdb', ''),
            detection_id=identity[0], x_px=source.get('x_px', ''),
            y_px=source.get('y_px', ''), source_class=source.get('source_class', ''),
            saturated=source.get('saturated', ''),
            saturation_known=source.get('saturation_known', ''),
            saturated_channels=source.get('saturated_channels', ''),
            **{name: source.get(name, '') for name in measurement_fields}))
    with (output/'identified_source_photometry.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    answer['identified_source_photometry'] = dict(
        path='identified_source_photometry.csv', rows=len(rows),
        catalogue_star_rows=sum(row['identity_type'] == 'catalogue_star' for row in rows),
        planet_candidate_rows=sum(row['identity_type'] != 'catalogue_star' for row in rows),
        count_rate_unit='ADU/s', calibrated_physical_flux=False)
    return measurement_fields


def fit_blind_planet_epoch(image_path, solution, result, *, epoch_limits=(1850., 2036.),
                           gate_arcmin=30., search_context=None):
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
            row.update(catalogue_star_id=star['star_id'],
                       catalogue_residual_px=float(star['residual_px']),
                       catalogue_residual_arcmin=float(
                           star.get('residual_arcmin', np.inf)))
    from point_star_time_bounds import capture_time_ceiling
    ceiling = result.get('causal_epoch_ceiling') or capture_time_ceiling()
    zenith_path = output/'photometric_zenith.json'
    photometric_zenith = json.loads(zenith_path.read_text()) if zenith_path.is_file() else {}
    jd, grid, provenance = load_ephemeris(*epoch_limits)
    from point_star_planet_solar import (
        classify_night, SolarConstraint, annotate_candidates, write_solar_evidence)
    fixed_ids = {str(identity) for identity in photometric_zenith.get('fitted_detection_ids', [])}
    fixed_rows = [row for identity, row in used.items() if str(identity) in fixed_ids]
    camera = _camera_from_result(result)
    if fixed_rows and len(fixed_rows) == len(fixed_ids):
        fixed_rays = camera.to_sky([[float(row['x_px']), float(row['y_px'])] for row in fixed_rows])
    else:
        fixed_rays = np.empty((0, 3))
    from point_star_zenith import zenith_constraints
    zenith, envelope, _ = zenith_constraints(camera, photometric_zenith, fixed_rays)
    solar = SolarConstraint(classify_night(result, len(used)), envelope, zenith_unit_vector=zenith)
    # Patched/local callables used by tests and embedders stay on the serial
    # reference path; the shipped module function is safe for process workers.
    parallel_safe = getattr(planet_vectors, '__module__', '') == 'point_star_planet_ephemeris'
    workers = planet_worker_count(nonempty_groups=len(grid)) if parallel_safe else 1
    metadata_conditioned = bool(search_context and search_context.get('metadata_used'))
    answer = search_planet_epochs(_camera_from_result(result), detections, jd, grid, planet_vectors,
                                 gate_arcmin=gate_arcmin,
                                 positional_sigma_arcmin=max(
                                     float(result['fit'].get('rms_arcmin', 3.)), 3.),
                                 zenith_unit_vector=zenith,
                                 zenith_status=photometric_zenith.get('status', 'unresolved'),
                                 zenith_source=photometric_zenith.get('zenith_source'),
                                 latest_jd_tdb=ceiling['jd_tdb'], planet_workers=workers,
                                 solar_constraint=solar,
                                 search_label=('Metadata planets' if metadata_conditioned
                                               else 'Blind planets'))
    if search_context is None:
        search_context = dict(planet_search_mode='blind', metadata_used=False,
                              epoch_limits=tuple(epoch_limits))
    answer.update({key: value for key, value in search_context.items()
                   if key != 'epoch_limits'})
    if answer['metadata_used']:
        answer['method'] = answer['method'].replace(
            'blind trajectory-segment search',
            'metadata-conditioned trajectory-segment search')
        answer['limitation'] = answer['limitation'].replace(
            'No site, image date or stellar epoch seeds this search.',
            'The selected observation time bounds this local search; '
            'no site or stellar epoch seeds it.')
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
    solar_started = time.perf_counter()
    answer = annotate_candidates(answer, solar, camera, counted_planet_vectors)
    solar_seconds = time.perf_counter()-solar_started
    answer = check_candidate_absences(image_path, answer, _camera_from_result(result),
                                     detections, list(used.values()), counted_planet_vectors,
                                     valid_mask=_load_sky_footprint(output), solution=output)
    answer = annotate_metadata_accuracy(answer)
    evidence_seconds = time.perf_counter()-evidence_started-solar_seconds
    write_evidence(output, answer)
    write_solar_evidence(output, answer)
    from point_star_science import load_recorded_image
    scientific = load_recorded_image(image_path, output)
    rejection_path = output/'dots/rejected_candidates.csv'
    if rejection_path.is_file():
        with rejection_path.open() as handle:
            rejected_candidates = list(csv.DictReader(handle))
    else:
        rejected_candidates = []
    recovery_valid_mask = _load_sky_footprint(output)
    metadata_association, recovered = associate_metadata_planets_with_recovery(
        scientific, _camera_from_result(result), detections,
        rejected_candidates, recovery_valid_mask,
        answer.get('searched_planets', []), counted_planet_vectors,
        answer.get('observation_time_metadata') or {},
        gate_arcmin=gate_arcmin,
        positional_sigma_arcmin=max(float(result['fit'].get('rms_arcmin', 3.)), 3.),
        zenith_unit_vector=(answer.get('visibility') or {}).get('zenith_unit_vector'))
    if recovered:
        append_recovered_source_photometry(output, scientific, recovered)
        detections.extend(recovered)
    answer['metadata_planet_association'] = metadata_association
    answer['metadata_recovered_sources'] = recovered
    answer['metadata_matches'] = metadata_association['matches']
    answer['predicted_planets'] = (
        metadata_association['predicted_without_source']
        if metadata_association['status'] in
        ('metadata_time_associated', 'metadata_time_no_source_match')
        else predict_other_planets(_camera_from_result(result), answer,
                                   counted_planet_vectors))
    identities = {}
    for candidate in answer['source_candidates']:
        identities.setdefault(candidate['detection_id'], set()).add(candidate['planet'])
    for candidate in answer['candidates']:
        for match in candidate['matches']:
            identities.setdefault(match['detection_id'], set()).add(match['planet'])
    answer['source_identity_alternatives'] = {str(key): sorted(value) for key, value in identities.items()}
    surviving, rejected = {}, {}
    for candidate in answer['candidates']:
        target = surviving if candidate['solar_evidence']['selection_eligible'] else rejected
        for match in candidate['matches']:
            target.setdefault(str(match['detection_id']), set()).add(match['planet'])
    answer['surviving_source_identity_alternatives'] = {key: sorted(value) for key, value in surviving.items()}
    answer['solar_rejected_source_identity_alternatives'] = {key: sorted(value) for key, value in rejected.items()}
    photometry_fields = _attach_identified_photometry(output, answer)
    answer['candidate_selection'] = ('nonnegative measured/predicted altitude relative to the recorded adopted zenith and valid detector projection; '
        'all measured detections considered; an isolated matched star may be challenged only with positional delta chi-square >=9; '
        'a coherent three-or-more-planet constellation anchored by two independently eligible planets may recruit a matched star '
        'inside the ordinary planet gate only when the planet residual is smaller than the catalogue residual; saturated/broad sources retained; '
        'accepted stellar field implies nighttime; candidates requiring daylight throughout their positional interval '
        'for all zeniths in the recorded solar envelope (an assumed point for the centre default) are excluded from selection')
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
        performance['seconds']['solar_evidence'] = float(solar_seconds)
        performance['providers']['solar_exact_dates'] = len(solar._cache)
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
    fields = ['candidate_rank', 'positional_rank', 'missing_bright_planets', 'solar_status', 'solar_reason',
              'solar_selection_eligible', 'solar_boundary_refinement',
              'sun_altitude_deg', 'sun_minimum_altitude_deg', 'sun_maximum_altitude_deg',
              'epoch_tdb', 'metadata_offset_seconds', 'match_count', 'rms_arcmin', 'rms_px',
              'planet', 'detection_id', 'measured_x_px', 'measured_y_px',
              'predicted_x_px', 'predicted_y_px', 'separation_arcmin', 'separation_px',
              'saturated', 'source_class', 'unused_brightness_rank', 'flux_above_background',
              'catalogue_star_id', 'catalogue_residual_arcmin', 'catalogue_residual_px',
              'improvement_over_star_chi2',
              'constellation_override', 'measured_altitude_deg', 'predicted_altitude_deg',
              *photometry_fields]
    with (output/'planet_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for rank, candidate in enumerate(answer['candidates'], 1):
            for match in candidate['matches']:
                solar_row = candidate['solar_evidence']
                writer.writerow(dict(candidate_rank=rank, positional_rank=candidate['positional_rank'],
                                     missing_bright_planets=';'.join(candidate['missing_bright_planets']),
                                     solar_status=solar_row['status'], solar_reason=solar_row['reason'],
                                     solar_selection_eligible=solar_row['selection_eligible'],
                                     solar_boundary_refinement=candidate['solar_boundary_refinement'],
                                     sun_altitude_deg=solar_row.get('adopted_zenith_solar_altitude_deg'),
                                     sun_minimum_altitude_deg=solar_row.get('minimum_solar_altitude_deg'),
                                     sun_maximum_altitude_deg=solar_row.get('maximum_solar_altitude_deg'),
                                     epoch_tdb=candidate['epoch_tdb'],
                                     metadata_offset_seconds=candidate.get('metadata_offset_seconds'),
                                     match_count=candidate['match_count'],
                                     rms_arcmin=candidate['rms_arcmin'],
                                     rms_px=candidate['rms_px'], **match))
    with (output/'planet_source_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            'planet', 'detection_id', 'jd_tdb', 'epoch_tdb',
            'separation_arcmin', 'separation_px'])
        writer.writeheader(); writer.writerows(answer['source_candidates'])
    with (output/'planet_visibility.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=['detection_id', 'x_px', 'y_px', 'altitude_deg', 'visible', 'rejection_reason'])
        writer.writeheader(); writer.writerows(answer.get('visibility_sources', []))
    write_epoch_diagnostics(output, answer)
    _plot_candidates(image_path, output, answer)
    return answer


def _plot_candidates(image_path, output, answer):
    import matplotlib.pyplot as plt
    from point_star_image import load_recorded_image
    from point_star_plotting import save_png
    fig, ax = plt.subplots(figsize=(10, 9))
    ax.imshow(load_recorded_image(image_path, output).display_rgb)
    metadata_matches = answer.get('metadata_matches') or []
    selected = answer.get('matches') or []
    metadata_only = bool(metadata_matches)
    candidate_only = not metadata_only and not selected
    displayed = metadata_matches or selected or answer.get('candidate_matches') or []
    for row in displayed:
        x, y = row['measured_x_px'], row['measured_y_px']
        ax.plot(x, y, '*', mfc='none', mec='magenta', mew=1.4, ms=12)
        label = (row['planet'] + ' — metadata-time match' if metadata_only else
                 row['planet'] + (' candidate' if candidate_only else ''))
        ax.annotate(label, (x, y), xytext=(7, 7), textcoords='offset points', color='white',
                    bbox=dict(fc='black', alpha=.7))
    from point_star_report import _draw_predicted_planets
    from matplotlib.lines import Line2D
    handles = []
    if displayed:
        handles.append(Line2D([], [], marker='*', linestyle='none', markersize=11,
                              markerfacecolor='none', markeredgecolor='magenta',
                              markeredgewidth=1.4,
                              label=('metadata-time planet match' if metadata_only else
                                     'planet candidate' if candidate_only else 'matched planet')))
    prediction_handle = _draw_predicted_planets(ax, answer.get('predicted_planets', []))
    if prediction_handle is not None:
        handles.append(prediction_handle)
    if handles:
        ax.legend(handles=handles, loc='lower left', fontsize=8)
    heading = ('Metadata-conditioned planet candidates'
               if answer.get('metadata_used') else 'Blind planet candidates')
    ax.set_title(heading+': '+answer['status'].replace('_', ' ')+'\n'+
                 (answer.get('best_candidate_epoch_tdb') or
                  ('Metadata-time source match shown; epoch not inferred' if metadata_only else
                   'Candidate identity shown; no identifiable epoch' if displayed else
                   'No supported candidate'))+'; alternatives in planet_candidates.csv')
    ax.axis('off'); fig.tight_layout()
    save_png(fig, output/'planet_candidates.png', dpi=180); plt.close(fig)


def write_epoch_diagnostics(output, answer):
    """Print every retained epoch and plot its identity/residual/local precision."""
    from astropy.time import Time
    import matplotlib.pyplot as plt
    from point_star_plotting import save_png
    output = Path(output)
    candidates = answer.get('candidates', [])
    conditioned = bool(answer.get('metadata_used'))
    heading = ('Metadata-conditioned planetary candidates'
               if conditioned else 'Blind planetary epoch candidates')
    lines = [f"{heading}: {len(candidates)} ({answer['status']})",
             'Fit rank | Candidate epoch (TDB)       | Planet/source                   | RMS arcmin | local sigma (h) | Missing bright planets | Solar status']
    metadata = answer.get('observation_time_metadata') or {}
    if conditioned:
        lines.insert(1, f"Metadata time: {metadata.get('time_utc', '--')} from {metadata.get('source', '--')}; local search only, not blind epoch inference.")
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
        solar_status = candidate.get('solar_evidence', {}).get('status', 'not_checked')
        if candidate.get('solar_evidence', {}).get('requires_date_refinement'):
            solar_status += ' (epoch needs refit)'
        lines.append(f"{rank:8d} | {candidate['epoch_tdb']:27s} | {bodies:31s} | {candidate['rms_arcmin']:10.3f} | {sigma_text} | {', '.join(candidate.get('missing_bright_planets', [])) or '--'} | {solar_status}")
    if answer.get('negative_evidence'):
        lines.append('Candidates with missing bright planets rank below uncontradicted trials; unknown detectability is neutral. See planet_non_detections.json.')
    if answer.get('solar_evidence'):
        solar = answer['solar_evidence']
        lines.append(f"Solar consistency: {solar['rejected_candidates']} rejected, {solar['unresolved_candidates']} unresolved, "
                     f"{solar['consistent_candidates']} consistent. Night classification: {answer['night_classification']['status']}. "
                     'Rejected epochs remain in the audit; see planet_solar_evidence.json.')
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
        ax.errorbar(years, [c['rms_arcmin'] for c in group], xerr=uncertainty,
                    fmt='o', ms=4, capsize=2, alpha=.8, label=label)
    if candidates:
        ax.legend(fontsize=8)
    else:
        ax.text(.5, .5, 'No competitive planet/date candidate', ha='center', transform=ax.transAxes)
    plot_heading = ('Metadata-conditioned planetary dates'
                    if conditioned else 'Blind planetary dates')
    ax.set(xlabel='Candidate epoch (Julian year, TDB)', ylabel='Positional RMS (arcmin)',
           title=f"{plot_heading}: {len(candidates)} retained candidates\n{answer['status'].replace('_', ' ')}")
    ax.grid(alpha=.25)
    fig.text(.5, .01, 'Horizontal bars: conditional local 1-sigma only; global date/identity ambiguities remain.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .035, 1, 1))
    save_png(fig, output/'planet_epoch_candidates.png', dpi=190)
    plt.close(fig)
