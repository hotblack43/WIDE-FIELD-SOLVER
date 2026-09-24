"""Blind physical-zenith constraint from catalogue-relative stellar photometry.

No site, date, horizon labels or astrometric-refraction zenith enters this fit.
Extinction and zero point are nuisance regression parameters for trial airmasses.
"""
import numpy as np
from scipy.optimize import minimize


def zenith_supports_visibility(status, source):
    return status == 'conditional_zenith' or (status == 'assumed_zenith' and source == 'image_centre_assumption')


def zenith_constraints(camera, record, rays):
    """Visibility authority at this camera, including the explicit centre policy."""
    from point_star_planet_solar import zenith_envelope
    vector = record.get('zenith_unit_vector')
    accepted = zenith_supports_visibility(record.get('status'), record.get('zenith_source'))
    if record.get('zenith_source') == 'image_centre_assumption' and accepted:
        h, w = camera.shape
        vector = camera.to_sky([[(w-1)/2., (h-1)/2.]])[0].tolist()
        envelope = dict(status='bounded', source='image_centre_assumption',
                        centre_unit_vector=vector, radius_deg=0.,
                        reason='Conditional on investigator-requested exact centre zenith, not an extinction confidence region',
                        metadata_used=False)
    else:
        envelope = zenith_envelope(rays)
    return vector, envelope, bool(accepted and vector is not None)


def airmass(altitude_deg):
    altitude = np.asarray(altitude_deg, dtype=float)
    answer = np.full(altitude.shape, np.nan)
    # Allow only sub-microdegree roundoff from the constrained horizon fit.
    valid = (altitude >= -1e-7) & (altitude <= 90.)
    z = 90.-np.maximum(altitude[valid], 0.)
    answer[valid] = 1./(np.cos(np.deg2rad(z))+.50572*(96.07995-z)**-1.6364)
    return answer


def fit_photometric_zenith(rays, dimming, radial_squared, *, loss_scale_mag=.1,
                           geometric_zenith_unit_vector=None, geometric_evidence=None):
    """Profile the extinction regression on a fixed set of usable stellar rays.

    Returns a conditional or explicitly provisional zenith, and a radial-response
    sensitivity fit. The conditional covariance does not include unknown colours,
    clouds, JPEG processing, catalogue errors or general flat-field structure.
    """
    rays, y, radial = (np.asarray(value, dtype=float) for value in (rays, dimming, radial_squared))
    nstars = len(y)
    record = dict(status='not_identifiable', zenith_unit_vector=None,
                  fitted_count=nstars, withheld_count=0, metadata_used=False,
                  method='blind trial zenith; robust magnitude-difference versus airmass regression',
                  loss_scale_mag=loss_scale_mag, minimum_allowed_altitude_deg=0., candidate_profile=[],
                  geometric_horizon=geometric_evidence,
                  limitation='Conditional on a uniform atmosphere and catalogue/image photometry. '
                    'Colours, clouds, JPEG response and lens response may bias the zenith. '
                    'A fitted extinction slope alone does not establish a physical zenith.')
    geometric = None
    assumed_centre = (geometric_evidence or {}).get('status') == 'assumed_image_centre'
    if geometric_zenith_unit_vector is not None:
        geometric = np.asarray(geometric_zenith_unit_vector, dtype=float)
        if (geometric.shape != (3,) or not np.isfinite(geometric).all()
                or np.linalg.norm(geometric) < 1e-12):
            raise ValueError('Geometric zenith must be a finite three-dimensional vector')
        if not assumed_centre and (not geometric_evidence or geometric_evidence.get('status') != 'centred_full_horizon'):
            raise ValueError('Geometric zenith requires an established centred full horizon')
        geometric = geometric/np.linalg.norm(geometric)
    if rays.shape != (nstars, 3) or radial.shape != y.shape or not all(
            np.isfinite(value).all() for value in (rays, y, radial)):
        raise ValueError('Zenith fit needs finite paired unit rays, magnitudes and radii')
    norms = np.linalg.norm(rays, axis=1)
    if np.any(norms < 1e-12) or loss_scale_mag <= 0:
        raise ValueError('Invalid rays or photometric loss scale')
    rays = rays/norms[:, None]
    minimum_sine = 0.  # Include the horizon; never drop low-altitude stars.

    def robust_cost(residual):
        square = (residual/loss_scale_mag)**2
        return float(np.sum(2*loss_scale_mag**2*square/(np.sqrt(1+square)+1)))

    def regression(x, with_radial):
        design = np.column_stack([np.ones(nstars), x] + ([radial] if with_radial else []))
        weights = np.ones(nstars)
        for _ in range(12):
            coefs = np.linalg.lstsq(design*np.sqrt(weights)[:, None], y*np.sqrt(weights), rcond=None)[0]
            if coefs[1] < 0:
                other = [0, 2] if with_radial else [0]
                coefs[:] = 0
                coefs[other] = np.linalg.lstsq(design[:, other]*np.sqrt(weights)[:, None],
                                               y*np.sqrt(weights), rcond=None)[0]
            residual = design@coefs-y
            updated = 1/np.sqrt(1+(residual/loss_scale_mag)**2)
            if np.max(np.abs(updated-weights)) < 1e-7:
                break
            weights = updated
        return coefs, residual

    def fixed_zenith_fit(vector):
        vector = np.asarray(vector, dtype=float)
        if vector.shape != (3,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-12:
            raise ValueError('Geometric zenith must be a finite three-dimensional vector')
        vector = vector/np.linalg.norm(vector)
        sine = rays@vector
        if np.min(sine) < minimum_sine-1e-9:
            return None
        x = airmass(np.rad2deg(np.arcsin(np.clip(sine, minimum_sine, 1))))
        coefs, residual = regression(x, False)
        weights = 1/np.sqrt(1+(residual/loss_scale_mag)**2)
        design = np.column_stack([np.ones(nstars), x])
        weighted = design*np.sqrt(weights)[:, None]
        full_rank = np.linalg.matrix_rank(weighted) == 2
        variance = float(np.sum(weights*residual**2)/max(nstars-2, 1))
        covariance = variance*np.linalg.pinv(weighted.T@weighted)
        return dict(parameters=None, zenith_unit_vector=vector.tolist(),
                    cost=robust_cost(residual), intercept_mag=float(coefs[0]),
                    extinction_mag_per_airmass=float(coefs[1]),
                    extinction_sigma=float(np.sqrt(max(0., covariance[1, 1]))) if full_rank else None,
                    radial_coefficient_mag=0., conditional_sigma_deg=None, full_rank=False,
                    search_boundary_limited=False, rms_mag=float(np.sqrt(np.mean(residual**2))),
                    airmass_range=[float(x.min()), float(x.max())],
                    minimum_altitude_deg=float(np.rad2deg(np.arcsin(np.min(sine)))))

    def adopt_geometry(reason, photometric_trial=None):
        """Apply the same audited geometric fallback to every weak-fit exit."""
        record['reason'] = reason
        if photometric_trial is not None:
            record['photometric_trial'] = photometric_trial
        if geometric is None:
            if photometric_trial is not None:
                record['zenith_source'] = 'unconstrained_photometric_trial'
            return record
        sine = rays@geometric
        if assumed_centre:
            # This is an explicit instrument assumption, not a horizon detection
            # or an extinction recovery. Never move/drop stars to make it true.
            if photometric_trial is not None:
                for key in photometric_trial:
                    if key not in ('status', 'reason'):
                        record.pop(key, None)
            fixed = fixed_zenith_fit(geometric) if nstars >= 3 else None
            if fixed is not None:
                record.update(fixed)
            record.update(status='assumed_zenith', zenith_source='image_centre_assumption',
                zenith_unit_vector=geometric.tolist(), provisional=True,
                conditional_sigma_deg=None,
                below_assumed_horizon_count=int(np.sum(sine < -1e-9)),
                minimum_altitude_deg=float(np.degrees(np.arcsin(np.clip(sine.min(), -1, 1)))) if nstars else None,
                reason=reason + '; adopted investigator-requested image-centre zenith assumption',
                method=record['method'] + '; explicit image-centre default',
                assumption='Physical zenith is the exact detector-centre ray; not measured by extinction. '
                           'No uncertainty in this assumption is included in conditional epoch intervals.')
            return record
        if len(sine) and np.min(sine) < minimum_sine-1e-9:
            if photometric_trial is not None:
                record['zenith_source'] = 'unconstrained_photometric_trial'
            record['geometric_fallback_rejected_reason'] = (
                'One or more fixed photometric-sample rays fall below the geometric horizon')
            return record
        if nstars >= 3:
            record.update(fixed_zenith_fit(geometric))
        else:
            record['zenith_unit_vector'] = geometric.tolist()
        record.update(
            zenith_source='centred_full_horizon_geometry', provisional=True,
            reason=reason + '; adopted image-centre zenith from closed circular horizon',
            method=record['method'] + '; geometric image-centre fallback')
        return record

    if nstars < 20:
        return adopt_geometry('Fewer than 20 usable photometric sources')

    centre = rays.mean(axis=0)
    if np.linalg.norm(centre) < 1e-6:
        return adopt_geometry('Stellar rays do not define a visible hemisphere')
    centre /= np.linalg.norm(centre)
    axis = np.eye(3)[np.argmin(np.abs(centre))]
    east = np.cross(axis, centre); east /= np.linalg.norm(east)
    north = np.cross(centre, east)
    basis = np.column_stack([east, north])

    def zenith(parameters):
        vector = centre + basis@np.asarray(parameters)
        return vector/np.linalg.norm(vector)

    def trial_x(parameters):
        sine = rays@zenith(parameters)
        return airmass(np.rad2deg(np.arcsin(np.clip(sine, minimum_sine, 1))))

    constraints = [{'type': 'ineq', 'fun': lambda p: rays@zenith(p)-minimum_sine}]
    # Geometric seeds only. The mean ray is not assumed to be the physical zenith.
    seeds = [np.zeros(2)] + [np.array([x, y]) for x in (-.4, 0, .4) for y in (-.4, 0, .4) if x or y]

    def optimise(with_radial):
        solutions = []
        objective = lambda p: robust_cost(regression(trial_x(p), with_radial)[1])
        for seed in seeds:
            opt = minimize(objective, seed, method='SLSQP', bounds=[(-2., 2.)]*2,
                           constraints=constraints, options={'maxiter': 200, 'ftol': 1e-10})
            if opt.success and np.min(rays@zenith(opt.x)) >= minimum_sine-1e-9:
                solutions.append(opt)
        if not solutions:
            return None
        opt = min(solutions, key=lambda value: value.fun)
        x = trial_x(opt.x)
        coefs, residual = regression(x, with_radial)
        params = np.r_[opt.x, coefs]

        def predicted(p):
            value = p[2]+p[3]*trial_x(p[:2])
            return value+p[4]*radial if with_radial else value

        step = 1e-5
        jacobian = np.column_stack([(predicted(params+np.eye(len(params))[i]*step)-
                                     predicted(params-np.eye(len(params))[i]*step))/(2*step)
                                    for i in range(len(params))])
        weights = 1/np.sqrt(1+(residual/loss_scale_mag)**2)
        design = jacobian*np.sqrt(weights)[:, None]
        _, singular, vt = np.linalg.svd(design, full_matrices=False)
        threshold = max(1e-7, singular[0]*1e-6)
        valid = singular > threshold
        full_rank = bool(np.all(valid))
        variance = float(np.sum(weights*residual**2)/max(nstars-len(params), 1))
        inverse = np.zeros_like(singular)
        inverse[valid] = 1/singular[valid]**2
        covariance = variance*(vt.T*inverse)@vt
        jn = np.column_stack([(zenith(opt.x+np.eye(2)[i]*step)-zenith(opt.x-np.eye(2)[i]*step))/(2*step)
                              for i in range(2)])
        angular_sigma = np.rad2deg(np.sqrt(max(0., np.linalg.eigvalsh(jn@covariance[:2, :2]@jn.T).max())))
        return dict(parameters=opt.x.tolist(), zenith_unit_vector=zenith(opt.x).tolist(),
                    cost=float(opt.fun), intercept_mag=float(coefs[0]),
                    extinction_mag_per_airmass=float(coefs[1]),
                    extinction_sigma=float(np.sqrt(max(0., covariance[3, 3]))) if full_rank else None,
                    radial_coefficient_mag=float(coefs[2]) if with_radial else 0.,
                    conditional_sigma_deg=float(angular_sigma) if full_rank else None, full_rank=full_rank,
                    search_boundary_limited=bool(np.any(np.abs(opt.x) > 1.999)),
                    rms_mag=float(np.sqrt(np.mean(residual**2))),
                    airmass_range=[float(x.min()), float(x.max())],
                    minimum_altitude_deg=float(np.rad2deg(np.arcsin(np.min(rays@zenith(opt.x))))))

    primary = optimise(False)
    sensitivity = optimise(True)
    if primary is None or sensitivity is None:
        reason = 'No converged zenith keeps the fixed photometric sample at or above the horizon'
        partial_trial = None
        if primary is not None:
            reason = ('Radial-response sensitivity fit did not converge; '
                      'photometric zenith is not identifiable')
            partial_trial = dict(
                primary, status='not_identifiable', reason=reason,
                radial_response_check=None, radial_response_shift_deg=None)
        return adopt_geometry(reason, photometric_trial=partial_trial)
    selected = primary
    angle = float(np.rad2deg(np.arccos(np.clip(np.dot(primary['zenith_unit_vector'], sensitivity['zenith_unit_vector']), -1, 1))))
    reasons = []
    for label, fit in (('primary', primary), ('radial-response sensitivity', sensitivity)):
        if not fit['full_rank'] or fit['conditional_sigma_deg'] > 5.:
            reasons.append(f'{label} zenith has weak angular information')
        if fit['extinction_sigma'] is None or fit['extinction_mag_per_airmass'] <= 3*max(fit['extinction_sigma'], 1e-8):
            reasons.append(f'{label} fit lacks positive extinction evidence')
        if np.ptp(fit['airmass_range']) < .5:
            reasons.append(f'{label} fit has insufficient airmass range')
        if fit['search_boundary_limited']:
            reasons.append(f'{label} minimum is limited by the angular search boundary')
        if fit['minimum_altitude_deg'] < .01:
            reasons.append(f'{label} minimum is limited by the horizon boundary')
    if angle > max(3., 3*np.hypot(primary['conditional_sigma_deg'] or 180., sensitivity['conditional_sigma_deg'] or 180.)):
        reasons.append('Zenith changes under the radial-response sensitivity fit')
    if assumed_centre:
        record['centre_override_policy'] = dict(minimum_stars=50, minimum_extinction_snr=10.,
            maximum_conditional_sigma_deg=1., maximum_radial_response_shift_deg=1.)
        if nstars < 50:
            reasons.append('Centre override requires at least 50 photometric sources')
        for label, fit in (('primary', primary), ('radial-response sensitivity', sensitivity)):
            if (fit['extinction_sigma'] is None or
                    fit['extinction_mag_per_airmass'] < 10*max(fit['extinction_sigma'], 1e-8)):
                reasons.append(f'{label} does not meet 10-sigma centre-override requirement')
            if fit['conditional_sigma_deg'] is None or fit['conditional_sigma_deg'] > 1.:
                reasons.append(f'{label} does not meet 1-degree centre-override precision')
        if angle > 1.:
            reasons.append('Radial-response zenith shift exceeds 1-degree centre-override limit')
    trial_status = 'not_identifiable' if reasons else 'conditional_zenith'
    trial_reason = '; '.join(reasons) if reasons else 'Photometry constrains a conditional zenith'
    record.update(selected, status=trial_status,
                  reason=trial_reason,
                  provisional=bool(reasons), radial_response_check=sensitivity,
                  radial_response_shift_deg=angle,
                  profile_centre_unit_vector=centre.tolist(), profile_basis=basis.tolist())
    if not reasons:
        record['zenith_source'] = 'photometric_extinction'
    else:
        adopt_geometry(trial_reason, photometric_trial=dict(
            selected, status=trial_status, reason=trial_reason,
            radial_response_check=sensitivity, radial_response_shift_deg=angle))
    for x in np.linspace(-.6, .6, 21):
        for ytrial in np.linspace(-.6, .6, 21):
            point = np.array([x, ytrial])
            if np.min(rays@zenith(point)) >= minimum_sine:
                cost = robust_cost(regression(trial_x(point), False)[1])
                record['candidate_profile'].append(dict(x=float(x), y=float(ytrial), cost=cost))
    return record


def write_zenith_products(output, record):
    import json
    from pathlib import Path
    import matplotlib.pyplot as plt
    from point_star_plotting import save_png
    output = Path(output)
    (output/'photometric_zenith.json').write_text(json.dumps(record, indent=2)+'\n')
    fig, ax = plt.subplots(figsize=(6, 5))
    profile = record.get('candidate_profile', [])
    if profile:
        trial = record.get('photometric_trial') or record
        cost = np.array([p['cost'] for p in profile])
        points = ax.scatter([p['x'] for p in profile], [p['y'] for p in profile],
                            c=cost-trial['cost'], cmap='viridis', s=22)
        fig.colorbar(points, ax=ax, label='Increase in robust photometric regression cost')
        label = ('Unconstrained photometric minimum' if record.get('photometric_trial')
                 else 'Numerical best zenith')
        ax.plot(*trial['parameters'], marker='+', color='red', ms=12, label=label)
        ax.legend()
    else:
        ax.text(.5, .5, record['reason'], ha='center', va='center', wrap=True, transform=ax.transAxes)
    ax.set(xlabel='Zenith tangent coordinate 1 (geometric frame)',
           ylabel='Zenith tangent coordinate 2 (geometric frame)',
           title=f"Blind photometric zenith: {record['status']}")
    fig.tight_layout(); save_png(fig, output/'photometric_zenith_profile.png', dpi=160); plt.close(fig)
