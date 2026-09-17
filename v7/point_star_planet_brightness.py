"""Geocentric visual brightness for conservative bright-planet absence checks.

Polynomial equations: Mallama & Hilton (2018), Astronomy and Computing 25,
10–24, https://doi.org/10.1016/j.ascom.2018.08.002 (arXiv:1808.01973).
Saturn uses the globe-only estimate, omitting ring brightening; Mars omits
rotation/season corrections. These are not calibrated camera-band magnitudes.
"""
from __future__ import annotations
import warnings
import numpy as np
import erfa
from astropy import units as u
from astropy.coordinates import get_body_barycentric
from astropy.time import Time

BRIGHT_PLANETS = ('mercury', 'venus', 'mars', 'jupiter', 'saturn')
SOURCE = 'Mallama & Hilton 2018, equations 2–4, 6, 8, 11; Saturn globe only'


def visual_magnitude(name, r_au, distance_au, phase_deg):
    """Evaluate published geocentric V formulae in their applicable phase range."""
    r, distance, phase = np.broadcast_arrays(np.asarray(r_au, float),
                                            np.asarray(distance_au, float), np.asarray(phase_deg, float))
    coefficients = {
        'mercury': [-.613, .063280, -.0016336, .000033644, -.00000034265, 1.6893e-9, -3.0334e-12],
        'venus': [-4.384, -.001044, .0003687, -.000002814, 8.938e-9],
        'mars': [-1.601, .02267, -.0001302],
        'jupiter': [-9.395, -.00037, .000616],
        'saturn': [-8.95, -.00037, .000616],
    }
    if name not in coefficients:
        return np.full(r.shape, np.nan)
    valid = np.isfinite(r+distance+phase) & (r > 0) & (distance > 0) & (phase >= 0)
    maximum_phase = {'mars':50., 'jupiter':12., 'saturn':6.5}.get(name, 180.)
    valid &= phase <= maximum_phase
    with np.errstate(all='ignore'):
        absolute = np.polynomial.polynomial.polyval(phase, coefficients[name])
        if name == 'venus':
            absolute = np.where(phase > 163.7,
                np.polynomial.polynomial.polyval(phase, [236.05828, -2.81914, .00839034]), absolute)
        magnitude = absolute + 5*np.log10(r*distance)
    return np.where(valid, magnitude, np.nan)


def planet_brightness(name, jd_tdb):
    """Compute a batch of V estimates using only local reference ephemerides.

    Earth is evaluated at reception, planet/Sun at retarded emission times.
    No observer location, image date, network, or fitted stellar epoch is used.
    """
    dates = np.atleast_1d(np.asarray(jd_tdb, dtype=float))
    if dates.ndim != 1 or not np.isfinite(dates).all():
        raise ValueError('Brightness epochs must be finite one-dimensional TDB Julian dates')
    if name not in BRIGHT_PLANETS:
        return np.full(dates.shape, np.nan)
    if not len(dates):
        return dates.copy()
    t = Time(dates, format='jd', scale='tdb')
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message=r'ERFA function "epv00".*', category=erfa.ErfaWarning)
        earth = get_body_barycentric('earth', t, ephemeris='builtin').xyz.to_value(u.au).T
        emission = t
        for _ in range(3):
            planet = get_body_barycentric(name, emission, ephemeris='builtin').xyz.to_value(u.au).T
            emission = t - np.linalg.norm(planet-earth, axis=1)/173.1446326846693*u.day
        planet = get_body_barycentric(name, emission, ephemeris='builtin').xyz.to_value(u.au).T
        sun = get_body_barycentric('sun', emission, ephemeris='builtin').xyz.to_value(u.au).T
    solar, observer = planet-sun, planet-earth
    r, distance = np.linalg.norm(solar,axis=1), np.linalg.norm(observer,axis=1)
    phase = np.rad2deg(np.arccos(np.clip(np.sum(solar*observer,axis=1)/(r*distance),-1,1)))
    return visual_magnitude(name,r,distance,phase)
