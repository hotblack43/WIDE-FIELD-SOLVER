"""Scientific products for a completed point-source Barghini solution."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from point_star_barghini import vectors
from point_star_image import load_recorded_image
from point_star_plotting import save_png
from point_star_refraction import fit_atmospheric_refraction
from point_star_report import _camera_from_result, observation_metadata

def _read(path):
    with Path(path).open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def _float(row, key, default=0.):
    value = row.get(key, '').strip()
    return float(value) if value else float(default)


def fit_stellar_epoch(solution, result, catalogue_path, year_limits=(1850., 2036.)):
    """Reuse the epoch that actually produced the saved camera and coordinates."""
    if 'stellar_epoch' in result:
        return result['stellar_epoch']
    return dict(status='not_run', epoch_jyear=None, applied_epoch_jyear=None,
                reason='Catalogue replay has no integrated epoch fit; run the v0.3 solver',
                fitted_count=0, withheld_count=0, profile=[])


def fit_refraction(solution, result, catalogue_path, stellar_epoch):
    solution = Path(solution)
    rows = _read(solution/'star_coordinates.csv')
    xy = np.array([[_float(row, 'x_px'), _float(row, 'y_px')] for row in rows])
    camera = _camera_from_result(result)
    year = stellar_epoch.get('applied_epoch_jyear')
    target = vectors([_float(row, 'propagated_ra_deg', _float(row, 'catalog_ra_deg')) for row in rows],
                     [_float(row, 'propagated_dec_deg', _float(row, 'catalog_dec_deg')) for row in rows])
    apparent_camera = camera.to_sky(xy) @ camera.reference_rotation
    fitted = fit_atmospheric_refraction(apparent_camera, target, camera.reference_rotation)
    output = fitted.as_dict()
    output['catalogue_epoch_jyear_used'] = year
    (solution/'refraction_fit.json').write_text(json.dumps(output, indent=2)+'\n')
    return output




def classify_image_colour(image_path, solution=None):
    """Classify independent RGB information separately from the file's stored mode."""
    image = load_recorded_image(image_path, solution or Path(image_path).parent)
    stored_mode = '/'.join(image.provenance()['plane_names'])
    if image.rgb is None:
        mono = image.luminance
        rgb = np.repeat(mono[..., None], 3, axis=2)
    else:
        rgb = image.rgb
    step = max(1, int(math.sqrt(rgb.shape[0]*rgb.shape[1]/500_000.)))
    sample = rgb[::step, ::step]
    differences = {
        'R-G': float(np.sqrt(np.mean((sample[..., 0]-sample[..., 1])**2))),
        'G-B': float(np.sqrt(np.mean((sample[..., 1]-sample[..., 2])**2))),
        'R-B': float(np.sqrt(np.mean((sample[..., 0]-sample[..., 2])**2))),
    }
    equal_fraction = float(np.mean(
        (sample[..., 0] == sample[..., 1]) & (sample[..., 1] == sample[..., 2])))
    luminance = sample.mean(axis=2)
    chroma_rms = max(differences.values())
    independent = (image.rgb is not None
                   and equal_fraction < .995
                   and chroma_rms >= max(.75, .03*float(np.std(luminance))))
    return dict(stored_mode=stored_mode,
                classification='rgb' if independent else 'effectively_monochrome',
                independent_colour_channels=bool(independent),
                equal_rgb_pixel_fraction=equal_fraction,
                channel_difference_rms_adu=differences)


def _airmass_kasten_young(altitude_deg):
    from point_star_zenith import airmass
    return airmass(altitude_deg)


def _robust_line(x, y):
    """Iteratively clipped ordinary line fit, returning fit diagnostics."""
    keep = np.isfinite(x) & np.isfinite(y)
    for _ in range(5):
        if keep.sum() < 3:
            break
        design = np.c_[np.ones(keep.sum()), x[keep]]
        coefficients = np.linalg.lstsq(design, y[keep], rcond=None)[0]
        residual = y-(coefficients[0]+coefficients[1]*x)
        centre = np.median(residual[keep])
        sigma = 1.4826*np.median(np.abs(residual[keep]-centre))
        if not np.isfinite(sigma) or sigma <= 0:
            break
        updated = keep & (np.abs(residual-centre) <= 3.*sigma)
        if np.array_equal(updated, keep):
            break
        keep = updated
    if keep.sum() < 3:
        return None, keep
    design = np.c_[np.ones(keep.sum()), x[keep]]
    coefficients = np.linalg.lstsq(design, y[keep], rcond=None)[0]
    residual = y[keep]-design@coefficients
    variance = np.sum(residual**2)/max(keep.sum()-2, 1)
    covariance = variance*np.linalg.pinv(design.T@design)
    total = np.sum((y[keep]-np.mean(y[keep]))**2)
    output = dict(intercept_mag=float(coefficients[0]),
                  coefficient_mag_per_airmass=float(coefficients[1]),
                  coefficient_sigma_mag_per_airmass=float(np.sqrt(covariance[1, 1])),
                  rms_mag=float(np.sqrt(np.mean(residual**2))),
                  r_squared=float(1.-np.sum(residual**2)/total) if total > 0 else 0.,
                  fitted_count=int(keep.sum()), rejected_count=int((~keep).sum()))
    return output, keep


def _full_horizon_geometric_zenith(solution, camera):
    from point_star_footprint import centred_full_horizon
    from scipy.ndimage import binary_erosion
    path = Path(solution)/'dots/sky_footprint.npz'
    if not path.is_file():
        return None, dict(status='not_available', reason='No saved sky footprint')
    with np.load(path) as saved:
        if 'valid_mask' not in saved:
            raise ValueError('Saved sky-footprint file has no valid_mask')
        mask = np.asarray(saved['valid_mask'], dtype=bool)
    if mask.shape != tuple(camera.shape):
        raise ValueError('Saved sky-footprint shape does not match the fitted camera')
    evidence = centred_full_horizon(mask)
    if evidence['status'] != 'centred_full_horizon':
        return None, evidence
    vector = camera.to_sky(np.asarray([evidence['centre_px']], dtype=float))[0]
    boundary = mask & ~binary_erosion(mask)
    yy, xx = np.nonzero(boundary)
    boundary_rays = camera.to_sky(np.column_stack([xx, yy]))
    angles = np.rad2deg(np.arccos(np.clip(boundary_rays@vector, -1., 1.)))
    percentiles = np.percentile(angles, [5, 50, 95])
    evidence['camera_boundary_zenith_angle_percentiles_deg'] = percentiles.tolist()
    evidence['camera_horizon_angle_tolerance_deg'] = 10.
    horizon_radius = float(evidence['fitted_circle_radius_px'])
    evidence['footprint_horizon_scale_arcmin_per_px'] = 90.*60./horizon_radius
    evidence['fitted_horizon_scale_arcmin_per_px'] = percentiles[1]*60./horizon_radius
    if not (percentiles[0] >= 80. and percentiles[2] <= 100.
            and abs(percentiles[1]-90.) <= 5.):
        evidence.update(
            status='not_established',
            reason=('Circular footprint boundary rays are not approximately 90 degrees '
                    'from the image-centre ray in the fitted camera'))
        return None, evidence
    evidence['reason'] = ('Closed centred circular footprint and fitted-camera boundary rays '
                          'establish a full horizon around the image-centre zenith')
    return vector, evidence

def measure_photometry(image_path, solution, result, refraction):
    """Measure RGB aperture fluxes and fit catalogue-relative extinction."""
    solution = Path(solution)
    scientific = load_recorded_image(image_path, solution)
    colour = classify_image_colour(image_path, solution)
    if scientific.rgb is None:
        channels_data = {name: scientific.luminance for name in 'RGB'}
    else:
        channels_data = {name: scientific.rgb[..., index]
                         for index, name in enumerate('RGB')}
    for name in ('G1', 'G2'):
        if name in scientific.planes:
            channels_data[name] = scientific.planes[name].astype(float)
    rgb = np.stack([channels_data[name] for name in 'RGB'], axis=-1)
    coordinates = {row['detection_id']: row for row in _read(solution/'star_coordinates.csv')}
    detections = {row['detection_id']: row for row in _read(solution/'dots/star_candidates.csv')}
    fields = ['detection_id', 'star_id', 'catalogue_magnitude', 'saturated',
              'saturation_known', 'saturated_channels',
              'source_class', 'R_flux', 'G_flux', 'B_flux', 'R_mag', 'G_mag', 'B_mag',
              'altitude_deg', 'airmass',
              'R_minus_catalogue_mag', 'G_minus_catalogue_mag', 'B_minus_catalogue_mag',
              'R_used_for_extinction', 'G_used_for_extinction', 'B_used_for_extinction']
    native_extra = [name for name in ('G1', 'G2') if name in channels_data]
    for name in native_extra:
        fields.extend([f'{name}_flux', f'{name}_mag', f'{name}_saturated'])
    records = []
    camera = _camera_from_result(result)
    for identity, coordinate in coordinates.items():
        detection = detections[identity]
        x, y = _float(coordinate, 'x_px'), _float(coordinate, 'y_px')
        sigma = max(1., _float(detection, 'major_sigma_px', 1.5))
        aperture_radius = min(9., max(3., 2.5*sigma))
        inner, outer = aperture_radius+3., aperture_radius+7.
        x0, x1 = max(0, int(x-outer-1)), min(rgb.shape[1], int(x+outer+2))
        y0, y1 = max(0, int(y-outer-1)), min(rgb.shape[0], int(y+outer+2))
        local_y, local_x = np.indices((y1-y0, x1-x0))
        radius = np.hypot(local_x+x0-x, local_y+y0-y)
        cut = rgb[y0:y1, x0:x1]
        valid = scientific.valid_mask[y0:y1, x0:x1]
        aperture = radius <= aperture_radius
        annulus = (radius >= inner) & (radius <= outer)
        use_aperture = aperture & valid
        use_annulus = annulus & valid
        if use_aperture.any() and use_annulus.sum() >= 3:
            fluxes = (cut[use_aperture].sum(axis=0)
                      - np.median(cut[use_annulus], axis=0)*use_aperture.sum())
        else:
            fluxes = np.full(3, np.nan)
        mags = np.full(3, np.nan)
        positive = (fluxes > 0) & np.isfinite(fluxes)
        if str(detection['saturated']).lower() == 'true':
            positive[:] = False  # Raw flux retained for diagnostics, no saturated magnitudes.
        mags[positive] = -2.5*np.log10(fluxes[positive])
        catalogue_magnitude = _float(coordinate, 'magnitude')
        altitude = float('nan')
        airmass = float(_airmass_kasten_young([altitude])[0])
        record = dict(detection_id=identity, star_id=coordinate['star_id'],
                      catalogue_magnitude=catalogue_magnitude,
                      saturated=detection['saturated'], source_class=detection['source_class'],
                      saturation_known=detection.get('saturation_known', True),
                      saturated_channels=detection.get('saturated_channels', ''),
                      altitude_deg=altitude, airmass=airmass)
        for channel, flux, magnitude in zip('RGB', fluxes, mags):
            record[f'{channel}_flux'] = float(flux)
            record[f'{channel}_mag'] = float(magnitude)
            record[f'{channel}_minus_catalogue_mag'] = float(magnitude-catalogue_magnitude)
            record[f'{channel}_used_for_extinction'] = False
        for channel in native_extra:
            native_cut = channels_data[channel][y0:y1, x0:x1]
            if use_aperture.any() and use_annulus.sum() >= 3:
                flux = (native_cut[use_aperture].sum()
                        - np.median(native_cut[use_annulus])*use_aperture.sum())
            else:
                flux = float('nan')
            channel_mask = scientific.plane_saturated_masks[channel][y0:y1, x0:x1]
            saturated = bool(np.any(channel_mask[aperture]))
            magnitude = (-2.5*np.log10(flux)
                         if flux > 0 and np.isfinite(flux)
                         and str(detection['saturated']).lower() != 'true' else float('nan'))
            record[f'{channel}_flux'] = float(flux)
            record[f'{channel}_mag'] = float(magnitude)
            record[f'{channel}_saturated'] = saturated
        records.append(record)

    from point_star_zenith import fit_photometric_zenith, write_zenith_products
    # Membership is fixed before zenith optimisation; all measurement rows survive.
    usable = []
    for r in records:
        if str(r['saturated']).lower() == 'true':
            reason = 'saturated'
        elif not np.isfinite(r['G_mag']):
            reason = 'nonpositive_or_nonfinite_G_flux'
        elif not np.isfinite(r['catalogue_magnitude']):
            reason = 'nonfinite_catalogue_magnitude'
        else:
            reason = ''
        r['photometry_usable'] = not bool(reason)
        r['photometric_zenith_exclusion_reason'] = reason
        r['used_for_photometric_zenith'] = not bool(reason)
        if not reason:
            usable.append(r)
    geometric_zenith, geometric_evidence = _full_horizon_geometric_zenith(solution, camera)
    if usable:
        pixels = np.array([[_float(coordinates[r['detection_id']], 'x_px'),
                            _float(coordinates[r['detection_id']], 'y_px')] for r in usable])
        rays = camera.to_sky(pixels)
        radial = np.sum((pixels-np.array([camera.physical.x_o, camera.physical.y_o]))**2, axis=1)/camera.scale**2
        zenith = fit_photometric_zenith(rays,
                    [r['G_minus_catalogue_mag'] for r in usable], radial,
                    geometric_zenith_unit_vector=geometric_zenith,
                    geometric_evidence=geometric_evidence)
    else:
        zenith = fit_photometric_zenith(
            np.empty((0, 3)), np.array([]), np.array([]),
            geometric_zenith_unit_vector=geometric_zenith,
            geometric_evidence=geometric_evidence)
    zenith.update(coordinate_frame='ICRS', objective_channel='G',
                  excluded_by_fixed_geometric_cap=0,
                  membership='all identified unsaturated positive-flux sources with finite catalogue magnitude; no angular, morphology or residual cut',
                  fitted_detection_ids=[r['detection_id'] for r in usable])
    write_zenith_products(solution, zenith)
    vector = zenith.get('zenith_unit_vector')
    if vector is not None:
        for r in records:
            coordinate = coordinates[r['detection_id']]
            ray = camera.to_sky(np.array([[_float(coordinate, 'x_px'), _float(coordinate, 'y_px')]]))[0]
            r['altitude_deg'] = float(np.rad2deg(np.arcsin(np.clip(ray@vector, -1, 1))))
            r['airmass'] = float(_airmass_kasten_young([r['altitude_deg']])[0])
    fields.extend(['used_for_photometric_zenith', 'photometry_usable',
                   'photometric_zenith_exclusion_reason'])
    base_usable = [r for r in usable if r['used_for_photometric_zenith'] and np.isfinite(r['airmass'])]

    channels = list('RGB') if colour['classification'] == 'rgb' else ['G']
    extinction_by_channel = {}
    plot_data = {}
    for channel in channels:
        fit_rows = [row for row in base_usable if np.isfinite(row[f'{channel}_mag'])]
        if len(fit_rows) < 12:
            continue
        x = np.array([row['airmass'] for row in fit_rows])
        y = np.array([row[f'{channel}_minus_catalogue_mag'] for row in fit_rows])
        if channel == 'G' and all(key in zenith for key in (
                'intercept_mag', 'extinction_mag_per_airmass', 'extinction_sigma', 'rms_mag')):
            # Reuse the regression evaluated at the adopted zenith.
            fitted = dict(intercept_mag=zenith['intercept_mag'],
                          coefficient_mag_per_airmass=zenith['extinction_mag_per_airmass'],
                          coefficient_sigma_mag_per_airmass=zenith['extinction_sigma'],
                          rms_mag=zenith['rms_mag'], fitted_count=len(fit_rows), rejected_count=0,
                          fit_role=('zenith_objective'
                                    if zenith.get('zenith_source') == 'photometric_extinction'
                                    else 'adopted_geometric_zenith_diagnostic'))
            keep = np.ones(len(fit_rows), dtype=bool)
        else:
            fitted, keep = _robust_line(x, y)
            if fitted is not None:
                fitted['fit_role'] = ('adopted_geometric_zenith_diagnostic' if channel == 'G'
                                      else 'post_fit_channel_diagnostic')
        if fitted is None:
            continue
        for row, retained in zip(fit_rows, keep):
            row[f'{channel}_used_for_extinction'] = bool(retained)
        fitted['airmass_range'] = [float(np.min(x[keep])), float(np.max(x[keep]))]
        fitted['airmass_span'] = float(np.ptp(x[keep]))
        fitted['status'] = ('provisional_zenith' if zenith['status'] != 'conditional_zenith' else
                            ('fitted' if fitted['airmass_span'] >= .3 else 'insufficient_airmass_leverage'))
        fitted['relation'] = f'{channel}_machine - catalogue_mag = intercept + k * airmass'
        fitted['catalogue_passband'] = 'local bright-star catalogue magnitude'
        extinction_by_channel[channel] = fitted
        plot_data[channel] = (x, y, keep)

    if plot_data:
        fig, axes = plt.subplots(1, len(plot_data),
                                 figsize=(11.2, 3.0) if len(plot_data) == 3 else (5.5, 3.4),
                                 squeeze=False)
        colours = {'R': '#c53b37', 'G': '#238b45', 'B': '#2878b5'}
        for ax, channel in zip(axes[0], plot_data):
            x, y, keep = plot_data[channel]
            fitted = extinction_by_channel[channel]
            ax.scatter(x[~keep], y[~keep], s=8, facecolors='none',
                       edgecolors='.65', linewidths=.5)
            ax.scatter(x[keep], y[keep], s=8, color=colours[channel], alpha=.55)
            span = np.linspace(np.min(x[keep]), np.max(x[keep]), 100)
            ax.plot(span, fitted['intercept_mag']+
                    fitted['coefficient_mag_per_airmass']*span,
                    color='black', linewidth=1.1)
            sigma = fitted['coefficient_sigma_mag_per_airmass']
            uncertainty = f" ± {sigma:.3f}" if sigma is not None else " (uncertainty unresolved)"
            roles = {
                'zenith_objective': 'zenith objective',
                'adopted_geometric_zenith_diagnostic': 'adopted geometric-zenith diagnostic',
                'post_fit_channel_diagnostic': 'post-fit diagnostic',
            }
            role = roles.get(fitted.get('fit_role'), fitted.get('fit_role', 'diagnostic'))
            ax.set_title(f"{channel}: k={fitted['coefficient_mag_per_airmass']:.3f}{uncertainty}\n{role}",
                         fontsize=9, color=colours[channel])
            ax.set_xlabel('Airmass', fontsize=8)
            ax.set_ylabel(r'$m_{machine}-m_{catalogue}$ [mag]', fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=.2)
        heading = ('Geometric-zenith airmass diagnostic'
                   if zenith.get('zenith_source') == 'centred_full_horizon_geometry'
                   else 'Blind photometric zenith')
        fig.suptitle(f"{heading}: {zenith['status']} — regression by channel", fontsize=10)
        fig.tight_layout()
        save_png(fig, solution/'extinction_fit.png', dpi=180)
        plt.close(fig)

    with (solution/'stellar_photometry.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    representative = extinction_by_channel.get('G') or next(
        iter(extinction_by_channel.values()), None)
    summary = dict(status='instrumental_photometry_measured', measured_stars=len(records),
                   usable_photometric_stars=len(usable),
                   usable_unsaturated_compact_stars=sum(r['source_class'] == 'compact' for r in usable),
                   saturated_stars_excluded=sum(str(r['saturated']).lower() == 'true' for r in records),
                   saturation_known=bool(scientific.provenance()['saturation_known']),
                   saturation_policy=scientific.provenance()['saturation'],
                   calibrated=False,
                   image_colour=colour, channels_fitted=channels,
                   extinction=representative,
                   extinction_by_channel=extinction_by_channel,
                   extinction_status=(representative['status']
                                      if representative else 'not_fitted'),
                   epoch_and_site_source=None, metadata_used=False,
                   airmass_source=('blind_centred_full_horizon_geometry'
                                   if zenith.get('zenith_source') == 'centred_full_horizon_geometry'
                                   else 'blind_photometric_zenith'),
                   photometric_zenith=zenith,
                   limitation=('Each channel is compared with the same catalogue magnitude. '
                     'Passband mismatch, image response, colour terms and vignetting add scatter.'
                     + ('' if scientific.provenance()['saturation_known'] else
                        ' Saturation is unknown for this input, so clipping could not be excluded.')))
    (solution/'photometry_summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def planet_confidence(match_count, random_expectation, bright_single=True):
    if match_count >= 3 and random_expectation < .05:
        return 'strong'
    if match_count >= 2 and random_expectation < .2:
        return 'supported'
    if match_count == 1:
        return 'single_planet_candidate' if bright_single else 'weak_single_planet_candidate'
    return 'none'


def fit_planet_epoch(image_path, solution, result, stellar_epoch, gate_px=3., *,
                     force_blind=False):
    """Use post-fit time metadata by default, with a full blind fallback."""
    from point_star_metadata import planet_search_context
    from point_star_planets import fit_blind_planet_epoch
    explicit = (result.get('observation') or {}).get('time_utc')
    ceiling = (result.get('causal_epoch_ceiling') or {}).get('jd_tdb')
    context = planet_search_context(
        image_path, explicit_time=explicit, force_blind=force_blind,
        latest_jd_tdb=ceiling)
    return fit_blind_planet_epoch(
        image_path, solution, result, epoch_limits=context['epoch_limits'],
        gate_px=gate_px, search_context=context)


def analyse_existing(image_path, solution, result, catalogue_path, *,
                     force_blind_planets=False):
    stellar = fit_stellar_epoch(solution, result, catalogue_path)
    refraction = fit_refraction(solution, result, catalogue_path, stellar)
    photometry = measure_photometry(image_path, solution, result, refraction)
    planets = fit_planet_epoch(image_path, solution, result, stellar,
                               force_blind=force_blind_planets)
    science = dict(stellar_epoch=stellar, refraction=refraction,
                   photometry=photometry, planets=planets)
    (Path(solution)/'science_summary.json').write_text(json.dumps(science, indent=2)+'\n')
    return science


def compare_metadata(result, science):
    """Reveal validation answers after the blind results are fixed; never refit."""
    from astropy import units as u
    from astropy.coordinates import FK5, ICRS, SkyCoord
    from astropy.time import Time
    metadata = observation_metadata(result, reveal=True)
    comparison = dict(used_in_fit=False, metadata=metadata,
                      limitation='Post-fit comparison only. Latitude uses the mean celestial pole at the adopted epoch; '
                                 'uncertainties in stellar epoch and physical zenith limit this estimate.')
    year = result.get('coordinate_epoch_jyear')
    zenith = (science.get('photometry') or {}).get('photometric_zenith') or {}
    if year is not None and zenith.get('zenith_unit_vector') is not None:
        pole = SkyCoord(ra=0*u.deg, dec=90*u.deg,
                        frame=FK5(equinox=Time(year, format='jyear'))).transform_to(ICRS()).cartesian.xyz.value
        latitude = float(np.rad2deg(np.arcsin(np.clip(pole@np.array(zenith['zenith_unit_vector']), -1, 1))))
        comparison.update(derived_latitude_deg=latitude, zenith_status=zenith['status'],
                          stellar_epoch_status=(result.get('stellar_epoch') or {}).get('status'))
        if metadata.get('latitude') is not None:
            comparison['latitude_minus_metadata_deg'] = latitude-metadata['latitude']
    if year is not None and metadata.get('observation_time'):
        raw = metadata['observation_time']
        try:
            observed = Time(raw).jyear
        except (ValueError, TypeError):
            comparison['time_comparison_status'] = 'Metadata time could not be parsed'
        else:
            comparison['stellar_epoch_minus_metadata_years'] = float(year-observed)
    return comparison
