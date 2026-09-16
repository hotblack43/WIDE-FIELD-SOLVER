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
from PIL import Image
from scipy.optimize import minimize_scalar
from scipy.spatial import cKDTree

from point_star_barghini import vectors
from point_star_plotting import save_png
from point_star_refraction import fit_atmospheric_refraction
from point_star_report import _camera_from_result, observation_metadata

PLANETS = ('mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune')


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




def classify_image_colour(image_path):
    """Classify independent RGB information separately from the file's stored mode."""
    with Image.open(image_path) as image:
        stored_mode = image.mode
        rgb = np.asarray(image.convert('RGB'), dtype=float)
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
    independent = (stored_mode not in {'1', 'L', 'I', 'F'}
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

def measure_photometry(image_path, solution, result, refraction):
    """Measure RGB aperture fluxes and fit catalogue-relative extinction."""
    solution = Path(solution)
    colour = classify_image_colour(image_path)
    rgb = np.asarray(Image.open(image_path).convert('RGB'), dtype=float)
    coordinates = {row['detection_id']: row for row in _read(solution/'star_coordinates.csv')}
    detections = {row['detection_id']: row for row in _read(solution/'dots/star_candidates.csv')}
    fields = ['detection_id', 'star_id', 'catalogue_magnitude', 'saturated',
              'source_class', 'R_flux', 'G_flux', 'B_flux', 'R_mag', 'G_mag', 'B_mag',
              'altitude_deg', 'airmass',
              'R_minus_catalogue_mag', 'G_minus_catalogue_mag', 'B_minus_catalogue_mag',
              'R_used_for_extinction', 'G_used_for_extinction', 'B_used_for_extinction']
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
        aperture = radius <= aperture_radius
        annulus = (radius >= inner) & (radius <= outer)
        fluxes = cut[aperture].sum(axis=0)-np.median(cut[annulus], axis=0)*aperture.sum()
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
                      altitude_deg=altitude, airmass=airmass)
        for channel, flux, magnitude in zip('RGB', fluxes, mags):
            record[f'{channel}_flux'] = float(flux)
            record[f'{channel}_mag'] = float(magnitude)
            record[f'{channel}_minus_catalogue_mag'] = float(magnitude-catalogue_magnitude)
            record[f'{channel}_used_for_extinction'] = False
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
    if usable:
        pixels = np.array([[_float(coordinates[r['detection_id']], 'x_px'),
                            _float(coordinates[r['detection_id']], 'y_px')] for r in usable])
        rays = camera.to_sky(pixels)
        radial = np.sum((pixels-np.array([camera.physical.x_o, camera.physical.y_o]))**2, axis=1)/camera.scale**2
        zenith = fit_photometric_zenith(rays,
                    [r['G_minus_catalogue_mag'] for r in usable], radial)
    else:
        zenith = fit_photometric_zenith(np.empty((0, 3)), np.array([]), np.array([]))
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
        if channel == 'G':
            # Show the nuisance regression that actually selected the zenith.
            fitted = dict(intercept_mag=zenith['intercept_mag'],
                          coefficient_mag_per_airmass=zenith['extinction_mag_per_airmass'],
                          coefficient_sigma_mag_per_airmass=zenith['extinction_sigma'],
                          rms_mag=zenith['rms_mag'], fitted_count=len(fit_rows), rejected_count=0,
                          fit_role='zenith_objective')
            keep = np.ones(len(fit_rows), dtype=bool)
        else:
            fitted, keep = _robust_line(x, y)
            if fitted is not None:
                fitted['fit_role'] = 'post_fit_channel_diagnostic'
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
            role = 'zenith objective' if channel == 'G' else 'post-fit diagnostic'
            ax.set_title(f"{channel}: k={fitted['coefficient_mag_per_airmass']:.3f}{uncertainty}\n{role}",
                         fontsize=9, color=colours[channel])
            ax.set_xlabel('Airmass', fontsize=8)
            ax.set_ylabel(r'$m_{machine}-m_{catalogue}$ [mag]', fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=.2)
        fig.suptitle(f"Blind photometric zenith: {zenith['status']} — regression by channel", fontsize=10)
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
                   calibrated=False,
                   image_colour=colour, channels_fitted=channels,
                   extinction=representative,
                   extinction_by_channel=extinction_by_channel,
                   extinction_status=(representative['status']
                                      if representative else 'not_fitted'),
                   epoch_and_site_source=None, metadata_used=False,
                   airmass_source='blind_photometric_zenith', photometric_zenith=zenith,
                   limitation=('Each channel is compared with the same catalogue magnitude. '
                     'Passband mismatch, JPEG response, colour terms and vignetting add scatter.'))
    (solution/'photometry_summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def _planet_vectors(times, name, location):
    from astropy.coordinates import get_body
    body = get_body(name, times, location)
    ra, dec = body.ra.radian, body.dec.radian
    return np.c_[np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)], body


def planet_confidence(match_count, random_expectation, bright_single=True):
    if match_count >= 3 and random_expectation < .05:
        return 'strong'
    if match_count >= 2 and random_expectation < .2:
        return 'supported'
    if match_count == 1:
        return 'single_planet_candidate' if bright_single else 'weak_single_planet_candidate'
    return 'none'


def fit_planet_epoch(image_path, solution, result, stellar_epoch, search_days=366, gate_px=3., *, allow_metadata=False):
    """Blind planetary search by default; legacy control requires explicit opt-in."""
    if not allow_metadata:
        from point_star_planets import fit_blind_planet_epoch
        return fit_blind_planet_epoch(image_path, solution, result)
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation
    from astropy.time import Time
    solution = Path(solution)
    detections = _read(solution/'dots/star_candidates.csv')
    used = {row['detection_id'] for row in _read(solution/'star_coordinates.csv')}
    unused = [row for row in detections if row['detection_id'] not in used]
    unused_xy = np.array([[_float(row, 'x_px'), _float(row, 'y_px')] for row in unused])
    metadata = observation_metadata(result)
    if not len(unused) or not metadata.get('observation_time'):
        output = dict(status='not_run', matches=[], reason='No unused sources or epoch search centre')
        (solution/'planet_epoch.json').write_text(json.dumps(output, indent=2)+'\n')
        return output
    centre = Time(metadata['observation_time'], scale='utc')
    times = centre + np.arange(-search_days, search_days+1)*u.day
    location = None
    if metadata.get('latitude') is not None:
        location = EarthLocation.from_geodetic(metadata['longitude']*u.deg,
            metadata['latitude']*u.deg, metadata['elevation_m']*u.m)
    camera = _camera_from_result(result); tree = cKDTree(unused_xy)
    predicted = {}; altitude = {}
    for name in PLANETS:
        sky, body = _planet_vectors(times, name, location)
        predicted[name] = camera.project(sky)
        if location is not None:
            altitude[name] = body.transform_to(AltAz(obstime=times, location=location,
                                                     pressure=0*u.hPa)).alt.deg
    trials = []
    for index in range(len(times)):
        candidates = []
        for name in PLANETS:
            xy = predicted[name][index]
            if not (0 <= xy[0] < camera.shape[1] and 0 <= xy[1] < camera.shape[0]):
                continue
            if name in altitude and altitude[name][index] <= 0:
                continue
            distance, nearest = tree.query(xy)
            if distance <= gate_px:
                candidates.append((float(distance), name, int(nearest)))
        candidates.sort()
        unique = []; claimed = set()
        for candidate in candidates:
            if candidate[2] not in claimed:
                unique.append(candidate); claimed.add(candidate[2])
        trials.append(unique)
    best_index = min(range(len(trials)), key=lambda i: (-len(trials[i]),
                     sum(item[0]**2 for item in trials[i])))
    coarse = trials[best_index]
    if not coarse:
        output = dict(status='no_planet_match', matches=[], unused_sources=len(unused),
                      search_centre_utc=centre.isot, search_half_width_days=search_days)
        (solution/'planet_epoch.json').write_text(json.dumps(output, indent=2)+'\n')
        return output
    assignments = [(name, nearest) for _, name, nearest in coarse]

    def objective(jd):
        epoch = Time(jd, format='jd', scale='utc'); total = 0.
        for name, nearest in assignments:
            sky, _ = _planet_vectors(epoch, name, location)
            total += float(np.sum((camera.project(sky)[0]-unused_xy[nearest])**2))
        return total
    optimum = minimize_scalar(objective, bounds=(times[best_index].jd-2,
                              times[best_index].jd+2), method='bounded',
                              options={'xatol': 1e-7})
    epoch = Time(optimum.x, format='jd', scale='utc')
    matches = []
    for name, nearest in assignments:
        sky, _ = _planet_vectors(epoch, name, location); predicted_xy = camera.project(sky)[0]
        row = unused[nearest]
        matches.append(dict(planet=name.title(), detection_id=int(row['detection_id']),
            measured_x_px=_float(row, 'x_px'), measured_y_px=_float(row, 'y_px'),
            predicted_x_px=float(predicted_xy[0]), predicted_y_px=float(predicted_xy[1]),
            separation_px=float(np.linalg.norm(predicted_xy-unused_xy[nearest])),
            flux_above_background=_float(row, 'flux_above_background'),
            saturated=row['saturated']=='True', source_class=row['source_class']))
    area = camera.shape[0]*camera.shape[1]
    random_expectation = len(PLANETS)*len(unused)*math.pi*gate_px**2/area
    ranked = sorted(range(len(unused)),
                    key=lambda i: _float(unused[i], 'flux_above_background'),
                    reverse=True)
    rank_by_index = {index: rank+1 for rank, index in enumerate(ranked)}
    for match, (_, nearest) in zip(matches, assignments):
        match['unused_brightness_rank'] = rank_by_index[nearest]
        match['unused_brightness_percentile'] = float(
            100.*(len(unused)-rank_by_index[nearest]+1)/len(unused))
    bright_single = bool(matches and
        (matches[0]['unused_brightness_percentile'] >= 75. or matches[0]['saturated']))
    confidence = planet_confidence(len(matches), random_expectation, bright_single)
    competing = sum(len(trial) >= len(matches) for trial in trials)-1
    speeds = []
    step_days = 1./1440.
    for name, nearest in assignments:
        before, _ = _planet_vectors(Time(epoch.jd-step_days, format='jd'), name, location)
        after, _ = _planet_vectors(Time(epoch.jd+step_days, format='jd'), name, location)
        speeds.append(np.linalg.norm(camera.project(after)[0]-
                                     camera.project(before)[0])/(2.*step_days))
    positional_sigma = max(float(result['fit']['rms_px']), .25)
    time_sigma_days = positional_sigma/math.sqrt(sum(speed**2 for speed in speeds))
    output = dict(status='planet_epoch_fitted', confidence=confidence,
        derived_epoch_utc=epoch.utc.isot+' UTC', derived_jd_utc=float(epoch.utc.jd),
        matches=matches, match_count=len(matches), unused_sources=len(unused),
        rms_px=float(math.sqrt(optimum.fun/len(matches))), gate_px=gate_px,
        random_match_expectation=float(random_expectation),
        conditional_time_sigma_minutes=float(time_sigma_days*1440.),
        competing_daily_minima=int(max(competing, 0)), search_centre_utc=centre.isot+' UTC',
        search_centre_source=metadata.get('epoch_source'), search_half_width_days=search_days,
        method='apparent GCRS ephemerides matched uniquely to unused measured point sources')
    (solution/'planet_epoch.json').write_text(json.dumps(output, indent=2)+'\n')
    with (solution/'planet_matches.csv').open('w', newline='') as handle:
        writer=csv.DictWriter(handle, fieldnames=list(matches[0])); writer.writeheader(); writer.writerows(matches)
    rgb=np.asarray(Image.open(image_path).convert('RGB')); fig,ax=plt.subplots(figsize=(11,10));ax.imshow(rgb)
    for match in matches:
        ax.plot(match['measured_x_px'],match['measured_y_px'],'o',ms=14,mfc='none',mec='cyan',mew=1.5)
        ax.annotate(f"{match['planet']} #{match['detection_id']}",(match['measured_x_px'],match['measured_y_px']),
                    xytext=(8,8),textcoords='offset points',color='cyan')
    ax.set_title(f"Planet matches: {confidence}; derived epoch {epoch.utc.isot} UTC")
    ax.set_xlim(-.5,rgb.shape[1]-.5);ax.set_ylim(rgb.shape[0]-.5,-.5);fig.tight_layout();save_png(fig, solution/'planet_candidates.png',dpi=160);plt.close(fig)
    return output


def analyse_existing(image_path, solution, result, catalogue_path):
    stellar = fit_stellar_epoch(solution, result, catalogue_path)
    refraction = fit_refraction(solution, result, catalogue_path, stellar)
    photometry = measure_photometry(image_path, solution, result, refraction)
    planets = fit_planet_epoch(image_path, solution, result, stellar)
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
