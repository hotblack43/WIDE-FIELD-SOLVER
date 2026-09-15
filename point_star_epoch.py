"""Catalogue space motion and conditional epoch fitting for point-source images.

ICRS axes remain fixed. Linear tangential space motion is normalised to a unit
vector; parallax and radial/perspective motion are not modelled by this CSV.
"""
from dataclasses import dataclass

import numpy as np

MAS_TO_RAD = np.deg2rad(1. / 3_600_000.)


@dataclass
class Catalogue:
    rows: list
    base: np.ndarray
    reference: np.ndarray
    velocity: np.ndarray
    has_motion: np.ndarray

    @classmethod
    def from_rows(cls, rows):
        rows = list(rows)
        if not rows:
            raise ValueError('Empty catalogue')
        def required(key):
            values = np.array([float(row[key]) for row in rows])
            if not np.all(np.isfinite(values)):
                raise ValueError(f'Non-finite catalogue {key}')
            return values
        ra, dec = required('ra_deg'), required('dec_deg')
        if np.any(np.abs(dec) > 90):
            raise ValueError('Catalogue declination outside [-90, 90]')
        reference = required('reference_epoch_jyear')
        ra, dec = np.deg2rad(ra), np.deg2rad(dec)
        base = np.c_[np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)]
        east = np.c_[-np.sin(ra), np.cos(ra), np.zeros(len(ra))]
        north = np.c_[-np.cos(ra)*np.sin(dec), -np.sin(ra)*np.sin(dec), np.cos(dec)]
        motion = np.zeros((len(rows), 2))
        valid = np.ones(len(rows), dtype=bool)
        for i, row in enumerate(rows):
            for j, key in enumerate(('pm_ra_cosdec_mas_per_year', 'pm_dec_mas_per_year')):
                value = str(row.get(key, '')).strip()
                if value == '':
                    valid[i] = False
                else:
                    motion[i, j] = float(value)
                    if not np.isfinite(motion[i, j]):
                        raise ValueError(f'Non-finite catalogue {key}')
        motion[~valid] = 0.
        velocity = MAS_TO_RAD*(motion[:, 0, None]*east + motion[:, 1, None]*north)
        return cls(rows, base, reference, velocity, valid)

    def at_year(self, year):
        if not np.isfinite(year):
            raise ValueError('Epoch must be finite')
        moved = self.base + (year-self.reference)[:, None]*self.velocity
        return moved/np.linalg.norm(moved, axis=1)[:, None]

    def subset(self, indices):
        indices = np.asarray(indices)
        return Catalogue([self.rows[i] for i in indices], self.base[indices],
                         self.reference[indices], self.velocity[indices], self.has_motion[indices])


def fit_epoch(camera, xy, catalogue, year_limits=(1850., 2150.), *, fixed_year=None):
    """Refit all fixed associations at trial epochs and return the adopted camera.

    The interval is an approximate profile-likelihood interval conditional on
    catalogue motions, associations and the lens model. It excludes catalogue
    uncertainty, refraction/model systematics and any independent date evidence.
    """
    from scipy.optimize import brentq, minimize_scalar
    from point_star_barghini import fit_camera, stats

    xy = np.asarray(xy, dtype=float)
    low, high = map(float, year_limits)
    if not np.isfinite([low, high]).all() or low >= high:
        raise ValueError('Epoch limits must be finite and increasing')
    if len(xy) != len(catalogue.rows) or len(xy) < 12 or not np.isfinite(xy).all():
        raise ValueError('Epoch fit needs at least 12 finite, paired stellar positions')
    if fixed_year is not None and not np.isfinite(fixed_year):
        raise ValueError('Supplied epoch must be finite')
    cache = {}

    def evaluate(year):
        year = float(year)
        if year not in cache:
            sky = catalogue.at_year(year)
            fitted, info = fit_camera(camera, xy, sky, max_nfev=2000)
            if not info['success'] or not fitted.is_monotonic():
                raise RuntimeError(f'Barghini fit failed at trial epoch {year:g}')
            residual = (fitted.to_sky(xy)-sky)*fitted.scale
            square = residual**2
            # Stable equivalent of scipy's soft_l1 cost at f_scale=1.
            penalty = (np.maximum(1e-6-fitted.radial_slopes(), 0)*fitted.scale*1e4)**2
            cost = float(np.sum(square/(np.sqrt(1+square)+1)) +
                         np.sum(penalty/(np.sqrt(1+penalty)+1)))
            cache[year] = (fitted, info, cost, residual)
        return cache[year]

    record = dict(mode='fixed' if fixed_year is not None else 'fit',
                  status='supplied_epoch' if fixed_year is not None else 'not_identifiable',
                  epoch_jyear=None, best_epoch_jyear=None, applied_epoch_jyear=2000.,
                  search_limits_jyear=[low, high], fitted_count=len(xy), withheld_count=0,
                  proper_motion_count=int(catalogue.has_motion.sum()),
                  missing_motion_count=int((~catalogue.has_motion).sum()),
                  boundary_limited=False, provisional=False, conditional_interval_95_jyear=[None, None],
                  method='all-star Barghini soft_l1 profile on fixed associations',
                  uncertainty_method='approximate delta-cost interval scaled by fitted residual variance',
                  limitation='Conditional on catalogue motions, associations and lens model; '
                    'does not include catalogue errors or atmospheric/lens systematics. '
                    'An unresolved epoch is provisional, not a measured date; only a numerically '
                    'flat or zero-motion profile adopts J2000.0.',
                  profile=[])
    if fixed_year is not None:
        adopted = float(fixed_year)
        record.update(epoch_jyear=adopted, applied_epoch_jyear=adopted,
                      reason='Epoch supplied explicitly; not inferred from stars')
    elif not np.any(catalogue.velocity):
        adopted = 2000.
        record.update(reason='No nonzero proper motions; epoch cannot be measured',
                      provisional=True, numerically_flat=True)
    else:
        grid = np.linspace(low, high, 21)
        costs = np.array([evaluate(year)[2] for year in grid])
        candidates = [(float(grid[0]), float(costs[0])), (float(grid[-1]), float(costs[-1]))]
        for i in range(len(grid)):
            if (i == 0 or costs[i] <= costs[i-1]) and (i == len(grid)-1 or costs[i] <= costs[i+1]):
                answer = minimize_scalar(lambda year: evaluate(year)[2],
                    bounds=(grid[max(0, i-1)], grid[min(len(grid)-1, i+1)]), method='bounded',
                    options={'xatol': .01})
                if not answer.success:
                    raise RuntimeError('Stellar epoch minimisation failed')
                candidates.append((float(answer.x), float(answer.fun)))
        best, minimum = min(candidates, key=lambda pair: pair[1])
        fitted, _, _, residual = evaluate(best)
        # Two independent sky coordinates per star, eight camera terms and epoch.
        variance = float(np.sum(residual**2/np.sqrt(1+residual**2))/max(1, 2*len(xy)-9))
        threshold = minimum + 1.920729410347062*max(variance, 1e-14)
        boundary = min(best-low, high-best) < .02
        nodes = sorted(set([*map(float, grid), *[c[0] for c in candidates]]))
        inside = [evaluate(year)[2] <= threshold for year in nodes]
        components = sum(yes and (i == 0 or not inside[i-1]) for i, yes in enumerate(inside))

        def crossing(direction):
            previous = best
            for year in sorted((y for y in nodes if (y-best)*direction > 0), reverse=direction < 0):
                if evaluate(year)[2] > threshold:
                    return float(brentq(lambda y: evaluate(y)[2]-threshold,
                                        min(previous, year), max(previous, year), xtol=.01))
                previous = year
            return None

        interval = [crossing(-1), crossing(1)]
        identifiable = not boundary and all(value is not None for value in interval) and components == 1
        flat = float(np.ptp(costs)) <= 1e-9*max(1., abs(minimum))
        identifiable = identifiable and not flat
        adopted = 2000. if flat else best
        record.update(status='conditional_epoch' if identifiable else 'not_identifiable',
                      epoch_jyear=best if identifiable else None, best_epoch_jyear=best,
                      applied_epoch_jyear=adopted, boundary_limited=boundary,
                      provisional=not identifiable, numerically_flat=flat,
                      conditional_interval_95_jyear=interval,
                      profile_variance=variance, confidence_components=components,
                      minimum_cost=minimum, conditional_cost_threshold=threshold,
                      reason=('Bounded conditional profile interval' if identifiable else
                              ('Numerically flat profile; J2000.0 adopted' if flat else
                               'Provisional numerical best fit; epoch not established by this image')))
        record['profile'] = [dict(year=year, cost=evaluate(year)[2],
                                  rms_px=stats(evaluate(year)[0].project(catalogue.at_year(year))-xy)['rms_px'])
                             for year in sorted(set([*map(float, grid), best]))]
    fitted, info, _, _ = evaluate(adopted)
    record['fit'] = stats(fitted.project(catalogue.at_year(adopted))-xy)
    record['applied_epoch_jyear'] = adopted
    return fitted, info, record


def write_epoch_products(output, record):
    """Save the actual solve's profile; never perform another epoch fit here."""
    import json
    from pathlib import Path
    import matplotlib.pyplot as plt
    from point_star_plotting import save_png
    output = Path(output)
    (output/'stellar_epoch.json').write_text(json.dumps(record, indent=2)+'\n')
    fig, ax = plt.subplots(figsize=(7, 4))
    profile = record['profile']
    if profile:
        ax.plot([p['year'] for p in profile], [p['cost']-record['minimum_cost'] for p in profile], 'o-')
        ax.axhline(record['conditional_cost_threshold']-record['minimum_cost'],
                   color='grey', linestyle=':', label='Approximate conditional 95% threshold')
    ax.axvline(record['applied_epoch_jyear'], color='tab:red', linestyle='--', label='Epoch used in saved solution')
    ax.set(xlabel='Trial epoch (Julian year)', ylabel='Increase in all-star robust fit cost',
           title=f"Stellar epoch: {record['status']}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_png(fig, output/'stellar_epoch_profile.png', dpi=160)
    plt.close(fig)
