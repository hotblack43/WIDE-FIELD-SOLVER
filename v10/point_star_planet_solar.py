"""Image-derived nighttime and conservative solar exclusion of planet dates.

The stellar-field => nighttime implication is the investigator's operating
assumption. Zenith bounds enclose *all* directions allowed by the fixed
photometric sample's horizon constraints, including weak extinction solutions.
No observing site, image date, or photometric likelihood cutoff is required.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog, brentq

SUNSET_CENTRE_DEG = -0.8333
ANGULAR_GUARD_DEG = 1.
# Deliberately wider than Earth's ~1 degree/day orbital solar motion. Applies
# to the shipped geocentric Sun provider over its supported 1850--2036 range.
SUN_SPEED_BOUND_DEG_PER_DAY = 2.


def classify_night(result, association_count):
    accepted = (result.get('status') == 'point_star_fit_converged'
                and result.get('fit', {}).get('count', 0) > 0
                and association_count > 0)
    return dict(status='night_supported' if accepted else 'unresolved',
                basis='identified_stellar_field' if accepted else 'no_accepted_stellar_field',
                policy='user_requested_stellar_field_implies_night',
                stellar_solve_status=result.get('status'), association_count=int(association_count),
                metadata_used=False)


def zenith_envelope(rays):
    """Enclose the entire stellar-horizon feasible region in a spherical cap.

    Set g = normalized sum of rays. Any admissible n has g.n > 0 when the
    rays span 3D: all r.n >= 0 and not all can be zero. Thus every admissible
    n is represented by normalize(g + B @ p). Four 2D linear programs bound
    both coordinates of p. The resulting rectangle encloses every solution;
    its four normalized corners generate a cone containing them all. A cap
    of radius <90 degrees containing those corners contains that whole cone.
    Unbounded/infeasible/numerically suspect programs mean unresolved, never
    a proof of solar inconsistency. No plotting-grid or local-covariance cut.
    """
    rays = np.asarray(rays, dtype=float)
    record = dict(status='unresolved', source='fixed_photometric_sample_horizon_constraints',
                  count=len(rays), minimum_stellar_altitude_deg=0.,
                  angular_guard_deg=ANGULAR_GUARD_DEG,
                  method='global gnomonic half-plane bounds; enclosing spherical cap')
    if (rays.ndim != 2 or rays.shape[1:] != (3,) or len(rays) < 3
            or not np.isfinite(rays).all()):
        return dict(record, reason='Insufficient finite stellar rays')
    norms = np.linalg.norm(rays, axis=1)
    if np.any(norms < 1e-12):
        return dict(record, reason='Invalid stellar rays')
    rays = rays / norms[:, None]
    if np.linalg.matrix_rank(rays, tol=1e-8) < 3:
        return dict(record, reason='Stellar rays do not span three dimensions')
    centre = rays.sum(axis=0)
    if np.linalg.norm(centre) < 1e-8:
        return dict(record, reason='No supported hemisphere chart')
    centre /= np.linalg.norm(centre)
    east = np.cross(np.eye(3)[np.argmin(abs(centre))], centre)
    east /= np.linalg.norm(east)
    basis = np.column_stack([east, np.cross(centre, east)])
    matrix, rhs = -rays@basis, rays@centre
    bounds = []
    try:
        for direction in ([1., 0.], [-1., 0.], [0., 1.], [0., -1.]):
            objective = np.asarray(direction)
            fit = linprog(objective, A_ub=matrix, b_ub=rhs,
                          bounds=[(None, None)]*2, method='highs')
            if not fit.success or not np.isfinite(fit.fun):
                return dict(record, reason='Horizon region unbounded or unresolved')
            dual = np.asarray(fit.ineqlin.marginals)
            if (np.max(dual) > 1e-8 or np.linalg.norm(matrix.T@dual-objective) > 1e-8
                    or np.max(matrix@fit.x-rhs) > 1e-7):
                return dict(record, reason='Horizon bound numerical check failed')
            # Pad outward, including the primal/dual gap and floating arithmetic.
            padding = max(1e-7, 1e-7*abs(fit.fun), abs(fit.fun-rhs@dual))
            bounds.append(float(min(fit.fun, rhs@dual)-padding))
    except (ValueError, RuntimeError):
        return dict(record, reason='Horizon bound optimization failed')
    xmin, xmax, ymin, ymax = bounds[0], -bounds[1], bounds[2], -bounds[3]
    corners = np.array([centre+basis@[x, y] for x in (xmin, xmax) for y in (ymin, ymax)])
    corners /= np.linalg.norm(corners, axis=1)[:, None]
    cap = corners.sum(axis=0)
    cap /= np.linalg.norm(cap)
    radius = float(np.rad2deg(np.arccos(np.clip(corners@cap, -1., 1.))).max())
    if not np.isfinite(radius) or radius+ANGULAR_GUARD_DEG >= 90.:
        return dict(record, reason='Horizon region too broad for a useful cap')
    return dict(record, status='bounded', centre_unit_vector=cap.tolist(),
                radius_deg=radius+ANGULAR_GUARD_DEG, unpadded_radius_deg=radius,
                gnomonic_bounds=[xmin, xmax, ymin, ymax],
                reason='Cap encloses every zenith keeping the fixed stellar sample above horizon')


class SolarConstraint:
    def __init__(self, night, envelope, *, zenith_unit_vector=None, sun_function=None):
        from point_star_planet_ephemeris import sun_vectors
        self.night = night
        self.envelope = envelope
        self.zenith = None if zenith_unit_vector is None else np.asarray(zenith_unit_vector, float)
        if self.zenith is not None:
            norm = np.linalg.norm(self.zenith)
            self.zenith = self.zenith/norm if np.isfinite(norm) and norm > 0 else None
        self.sun_function = sun_vectors if sun_function is None else sun_function
        self._cache = {}

    @property
    def active(self):
        return self.night['status'] == 'night_supported' and self.envelope['status'] == 'bounded'

    def sun(self, date):
        date = float(date)
        if date not in self._cache:
            value = np.asarray(self.sun_function([date]), dtype=float)
            if value.shape != (1, 3) or not np.isfinite(value).all() or np.linalg.norm(value[0]) < 1e-12:
                raise ValueError('Invalid solar ephemeris')
            self._cache[date] = value[0]/np.linalg.norm(value[0])
        return self._cache[date]

    def assess(self, date, interval=None):
        record = dict(status='solar_unresolved', jd_tdb=float(date),
                      sunset_centre_altitude_deg=SUNSET_CENTRE_DEG,
                      solar_model_guard_deg=ANGULAR_GUARD_DEG,
                      requires_date_refinement=False)
        if self.night['status'] != 'night_supported':
            return dict(record, reason='No accepted stellar-field nighttime classification')
        try:
            sun = self.sun(date)
        except (ValueError, RuntimeError):
            return dict(record, reason='Solar ephemeris unavailable or invalid')
        record['sun_unit_vector'] = sun.tolist()
        if self.zenith is not None:
            record['adopted_zenith_solar_altitude_deg'] = float(np.rad2deg(np.arcsin(np.clip(sun@self.zenith, -1, 1))))
        if self.envelope['status'] != 'bounded':
            return dict(record, reason='No bounded image-derived zenith region')
        altitude = float(np.rad2deg(np.arcsin(np.clip(sun@self.envelope['centre_unit_vector'], -1, 1))))
        radius = self.envelope['radius_deg']
        low, high = max(-90., altitude-radius), min(90., altitude+radius)
        record.update(minimum_solar_altitude_deg=low, maximum_solar_altitude_deg=high)
        span = [float(date), float(date)] if interval is None else list(map(float, interval))
        if (len(span) != 2 or not np.isfinite(span).all() or not span[0] <= date <= span[1]):
            return dict(record, reason='Invalid positional date interval')
        drift = SUN_SPEED_BOUND_DEG_PER_DAY*max(date-span[0], span[1]-date)
        record.update(positional_interval_jd_tdb=span,
                      solar_speed_bound_deg_per_day=SUN_SPEED_BOUND_DEG_PER_DAY,
                      interval_minimum_solar_altitude_deg=max(-90., low-drift))
        if low-drift > SUNSET_CENTRE_DEG+ANGULAR_GUARD_DEG:
            return dict(record, status='solar_inconsistent',
                        reason='Sun above sunset limit for every enclosed zenith and positional date')
        if high < SUNSET_CENTRE_DEG-ANGULAR_GUARD_DEG:
            return dict(record, status='solar_consistent',
                        reason='Sun below sunset limit for every enclosed zenith at candidate date')
        return dict(record, requires_date_refinement=bool(low > SUNSET_CENTRE_DEG+ANGULAR_GUARD_DEG),
                    reason='Solar horizon crossing or zenith uncertainty; no proven contradiction')

    def possible_intervals(self, interval):
        """Propose solar-boundary refits; absence of a proposal is not rejection.

        Hard exclusion uses assess()'s whole-interval speed bound, not sampling.
        A quarter-day mesh brackets solar crossings for additional candidates.
        Very long or unavailable intervals remain unresolved in the audit.
        """
        first, last = interval
        if not self.active or last <= first or last-first > 5000:
            return []
        def excess(date):
            evidence = self.assess(date)
            low = evidence.get('minimum_solar_altitude_deg')
            return np.nan if low is None else low-SUNSET_CENTRE_DEG-ANGULAR_GUARD_DEG
        dates = np.linspace(first, last, max(2, int(np.ceil((last-first)/.25))+1))
        values = np.array([excess(t) for t in dates])
        if not np.isfinite(values).all():
            return []
        boundaries = [first, last]
        for a, b, fa, fb in zip(dates[:-1], dates[1:], values[:-1], values[1:]):
            if fa*fb < 0:
                boundaries.append(float(brentq(excess, a, b, xtol=1e-8)))
            elif fa == 0:
                boundaries.append(float(a))
        boundaries = sorted(set(boundaries))
        intervals = []
        for a, b in zip(boundaries[:-1], boundaries[1:]):
            if excess((a+b)/2) <= 0:
                # Stay on the permissible side despite date/solver roundoff.
                inset = min(1e-6, (b-a)/4)
                intervals.append((a+inset, b-inset))
        return intervals


def annotate_candidates(answer, constraint, camera, vector_function):
    """Add physical evidence without changing positional records or selection."""
    answer['night_classification'] = constraint.night
    for candidate in answer.get('candidates', []):
        date = candidate['jd_tdb']
        interval = candidate.get('positional_interval_jd_tdb')
        # Old saved candidates do not contain their full acceptance intervals.
        # Their exact-date diagnostic must not masquerade as interval rejection.
        evidence = constraint.assess(date, interval)
        if interval is None and evidence['status'] == 'solar_inconsistent':
            evidence.update(status='solar_unresolved', reason='Positional interval unavailable; exact epoch implies daylight')
        evidence['elongations'] = []
        evidence['selection_eligible'] = (evidence['status'] != 'solar_inconsistent'
                                          and not evidence['requires_date_refinement'])
        if 'sun_unit_vector' in evidence:
            sun = np.asarray(evidence['sun_unit_vector'])
            for match in candidate['matches']:
                measured = camera.to_sky([[match['measured_x_px'], match['measured_y_px']]])[0]
                predicted = vector_function(match['planet'].lower(), [date])[0]
                evidence['elongations'].append(dict(
                    planet=match['planet'], detection_id=match['detection_id'],
                    measured_deg=float(np.rad2deg(np.arccos(np.clip(sun@measured, -1, 1)))),
                    predicted_deg=float(np.rad2deg(np.arccos(np.clip(sun@predicted, -1, 1))))))
        candidate['solar_evidence'] = evidence
    records = [c['solar_evidence'] for c in answer.get('candidates', [])]
    answer['solar_evidence'] = dict(
        method='stellar-field nighttime; global stellar-horizon zenith envelope',
        zenith_envelope=constraint.envelope, metadata_used=False,
        rejected_candidates=sum(r['status'] == 'solar_inconsistent' for r in records),
        unresolved_candidates=sum(r['status'] == 'solar_unresolved' for r in records),
        epochs_requiring_refinement=sum(r['requires_date_refinement'] for r in records),
        consistent_candidates=sum(r['status'] == 'solar_consistent' for r in records),
        limitation='Conditional on identified stellar field implying nighttime and fixed stellar horizon constraints. '
                   'One-degree zenith and one-degree solar margins are systematic guards, not confidence intervals. '
                   'Photometric-loss penalties are not applied.')
    return answer


def write_solar_evidence(output, answer):
    output = Path(output)
    (output/'night_classification.json').write_text(json.dumps(answer['night_classification'], indent=2, allow_nan=False)+'\n')
    record = dict(summary=answer['solar_evidence'], candidates=[dict(
        rank=i, epoch_tdb=c['epoch_tdb'], evidence=c['solar_evidence'])
        for i, c in enumerate(answer.get('candidates', []), 1)])
    (output/'planet_solar_evidence.json').write_text(json.dumps(record, indent=2, allow_nan=False)+'\n')
