"""Native-count aperture photometry with explicit saturated-wing models."""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares


def _rate(value, exposure_seconds):
    if (exposure_seconds is None or not np.isfinite(exposure_seconds)
            or exposure_seconds <= 0 or not np.isfinite(value)):
        return float('nan')
    return float(value/exposure_seconds)


def _moffat_wing_fit(pixels, valid, saturated, x, y, fit_radius, background):
    h, w = pixels.shape
    half = int(np.ceil(fit_radius)) + 1
    ix, iy = int(round(x)), int(round(y))
    x0, x1 = max(0, ix-half), min(w, ix+half+1)
    y0, y1 = max(0, iy-half), min(h, iy+half+1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.hypot(xx-x, yy-y)
    use = valid[y0:y1, x0:x1] & ~saturated[y0:y1, x0:x1] & (rr <= fit_radius)
    values = np.asarray(pixels[y0:y1, x0:x1], float)[use]
    xs, ys = xx[use].astype(float), yy[use].astype(float)
    if len(values) < 20:
        return dict(wing_fit_status='insufficient_unsaturated_wing_pixels',
                    wing_fit_unsaturated_pixels=int(len(values)))
    amplitude = float(np.nanmax(values)-background)
    if not np.isfinite(amplitude) or amplitude <= 0:
        return dict(wing_fit_status='nonpositive_wing_signal',
                    wing_fit_unsaturated_pixels=int(len(values)))
    alpha0 = max(.8, min(4., fit_radius/3.))
    initial = np.array([background, amplitude, x, y, alpha0, 2.5], float)
    bound_radius = max(2., fit_radius/2.)
    lower = [-np.inf, 0., x-bound_radius, y-bound_radius, .35, 1.05]
    upper = [np.inf, np.inf, x+bound_radius, y+bound_radius, fit_radius, 10.]
    noise = 1.4826*np.median(np.abs(values-np.median(values)))
    scale = max(1., float(noise))

    def residual(parameters):
        bg, peak, cx, cy, alpha, beta = parameters
        model = bg + peak*(1.+((xs-cx)**2+(ys-cy)**2)/alpha**2)**(-beta)
        return (model-values)/scale

    fitted = least_squares(residual, initial, bounds=(lower, upper),
                           loss='soft_l1', f_scale=1., max_nfev=500)
    bg, peak, cx, cy, alpha, beta = fitted.x
    model_residual = residual(fitted.x)*scale
    total = peak*np.pi*alpha**2/(beta-1.)
    acceptable = (fitted.success and np.isfinite(fitted.x).all()
                  and np.isfinite(total) and total > 0 and beta >= 1.2
                  and abs(cx-x) <= bound_radius and abs(cy-y) <= bound_radius
                  and alpha > .36 and alpha < .98*fit_radius)
    status = ('modelled_from_unsaturated_wings' if acceptable
              else 'wing_fit_quality_rejected')
    answer = dict(
        wing_fit_status=status,
        wing_fit_unsaturated_pixels=int(len(values)),
        wing_fit_x_px=float(cx), wing_fit_y_px=float(cy),
        wing_fit_background_adu=float(bg), wing_fit_peak_adu=float(peak),
        wing_fit_alpha_px=float(alpha), wing_fit_beta=float(beta),
        wing_fit_total_counts_adu=(float(total) if acceptable else float('nan')),
        wing_fit_rms_adu=float(np.sqrt(np.mean(model_residual**2))),
        wing_fit_nfev=int(fitted.nfev))
    return answer


def measure_channel(pixels, valid_mask, saturated_mask, *, x, y,
                    aperture_radius, exposure_seconds=None):
    """Measure one channel; saturated fits are separate model estimates."""
    pixels = np.asarray(pixels, float)
    valid = np.asarray(valid_mask, bool) & np.isfinite(pixels)
    saturated_mask = np.asarray(saturated_mask, bool)
    if pixels.ndim != 2 or valid.shape != pixels.shape or saturated_mask.shape != pixels.shape:
        raise ValueError('Channel pixels and masks must be equally shaped 2-D arrays')
    inner, outer = aperture_radius+3., aperture_radius+7.
    h, w = pixels.shape
    half = int(np.ceil(outer)) + 1
    ix, iy = int(round(x)), int(round(y))
    x0, x1 = max(0, ix-half), min(w, ix+half+1)
    y0, y1 = max(0, iy-half), min(h, iy+half+1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    radius = np.hypot(xx-x, yy-y)
    local_valid = valid[y0:y1, x0:x1]
    local_saturated = saturated_mask[y0:y1, x0:x1]
    aperture = radius <= aperture_radius
    annulus = (radius >= inner) & (radius <= outer)
    use_aperture = aperture & local_valid
    use_annulus = annulus & local_valid & ~local_saturated
    saturated_pixels = int(np.sum(aperture & local_saturated))
    if use_aperture.any() and use_annulus.sum() >= 3:
        background = float(np.median(pixels[y0:y1, x0:x1][use_annulus]))
        counts = float(np.sum(pixels[y0:y1, x0:x1][use_aperture])
                       - background*np.sum(use_aperture))
    else:
        background, counts = float('nan'), float('nan')
    saturated = saturated_pixels > 0
    answer = dict(
        aperture_counts_adu=counts,
        count_rate_adu_per_s=_rate(counts, exposure_seconds),
        aperture_background_adu=background,
        aperture_valid_pixels=int(np.sum(use_aperture)),
        saturated=bool(saturated),
        saturated_pixels_in_aperture=saturated_pixels,
        measurement_method=('saturated_aperture_lower_bound' if saturated
                            else ('aperture' if np.isfinite(counts) else 'unavailable')),
        wing_fit_status='not_needed',
        wing_fit_unsaturated_pixels=0,
        wing_fit_total_counts_adu=float('nan'),
        wing_fit_count_rate_adu_per_s=float('nan'),
        wing_fit_x_px=float('nan'), wing_fit_y_px=float('nan'),
        wing_fit_rms_adu=float('nan'))
    if saturated and np.isfinite(background):
        answer.update(_moffat_wing_fit(
            pixels, valid, saturated_mask, x, y, outer, background))
        answer['wing_fit_count_rate_adu_per_s'] = _rate(
            answer.get('wing_fit_total_counts_adu', float('nan')), exposure_seconds)
    return answer
