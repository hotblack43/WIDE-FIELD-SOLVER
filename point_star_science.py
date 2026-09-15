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

from point_star_barghini import fit_camera, vectors
from point_star_plotting import save_png
from point_star_refraction import fit_atmospheric_refraction
from point_star_report import _camera_from_result, observation_metadata

MAS_TO_RAD = math.radians(1.0 / 3_600_000.0)
PLANETS = ('mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune')


def _read(path):
    with Path(path).open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def _float(row, key, default=0.):
    value = row.get(key, '').strip()
    return float(value) if value else float(default)


def _catalogue_arrays(rows, catalogue_path):
    catalogue = {row['star_id']: row for row in _read(catalogue_path)}
    selected = [catalogue[row['star_id']] for row in rows]
    ra = np.array([_float(row, 'ra_deg') for row in selected])
    dec = np.array([_float(row, 'dec_deg') for row in selected])
    reference = np.array([_float(row, 'reference_epoch_jyear', 2000.) for row in selected])
    pm_ra = np.array([_float(row, 'pm_ra_cosdec_mas_per_year') for row in selected])
    pm_dec = np.array([_float(row, 'pm_dec_mas_per_year') for row in selected])
    base = vectors(ra, dec)
    ra_rad, dec_rad = np.deg2rad(ra), np.deg2rad(dec)
    east = np.c_[-np.sin(ra_rad), np.cos(ra_rad), np.zeros(len(ra))]
    north = np.c_[-np.cos(ra_rad)*np.sin(dec_rad),
                  -np.sin(ra_rad)*np.sin(dec_rad), np.cos(dec_rad)]
    return base, reference, pm_ra, pm_dec, east, north


def propagated_catalogue(arrays, year):
    base, reference, pm_ra, pm_dec, east, north = arrays
    moved = base + (year-reference)[:, None]*MAS_TO_RAD*(
        pm_ra[:, None]*east + pm_dec[:, None]*north)
    return moved/np.linalg.norm(moved, axis=1)[:, None]


def fit_stellar_epoch(solution, result, catalogue_path, year_limits=(1850., 2150.)):
    """Profile a proper-motion epoch while refitting the camera on training stars."""
    solution = Path(solution)
    rows = _read(solution/'star_coordinates.csv')
    xy = np.array([[_float(row, 'x_px'), _float(row, 'y_px')] for row in rows])
    ids = np.array([int(row['detection_id']) for row in rows])
    training = ids % 5 != 0
    test = ~training
    arrays = _catalogue_arrays(rows, catalogue_path)
    base_camera = _camera_from_result(result)

    def evaluate(year):
        sky = propagated_catalogue(arrays, year)
        camera, info = fit_camera(base_camera, xy[training], sky[training], max_nfev=120)
        delta = camera.project(sky[test])-xy[test]
        radius = np.linalg.norm(delta, axis=1)
        return float(np.sqrt(np.mean(radius**2))), float(np.median(radius)), info

    years = np.linspace(year_limits[0], year_limits[1], 31)
    profile = []
    for year in years:
        rms, median, _ = evaluate(float(year))
        profile.append(dict(year=float(year), withheld_rms_px=rms,
                            withheld_median_px=median))
    best_index = int(np.argmin([row['withheld_rms_px'] for row in profile]))
    low = years[max(0, best_index-1)]
    high = years[min(len(years)-1, best_index+1)]
    if low == high:
        best_year = float(years[best_index])
    else:
        optimum = minimize_scalar(lambda year: evaluate(year)[0], bounds=(low, high),
                                  method='bounded', options={'xatol': .01})
        best_year = float(optimum.x)
    rms, median, info = evaluate(best_year)
    boundary = best_index in (0, len(years)-1) or min(
        best_year-year_limits[0], year_limits[1]-best_year) < 1.
    improvement = profile[len(profile)//2]['withheld_rms_px']-rms
    status = 'not_identifiable' if boundary or improvement < .01 else 'conditional_epoch'
    output = dict(status=status, method='catalogue proper motions with camera refitted',
                  epoch_jyear=best_year, search_limits_jyear=list(year_limits),
                  boundary_limited=boundary, withheld_count=int(test.sum()),
                  training_count=int(training.sum()), withheld_rms_px=rms,
                  withheld_median_px=median, rms_improvement_px=float(improvement),
                  profile=profile, limitation=(
                      'Global precession is degenerate with camera orientation in one point image; '
                      'only differential catalogue proper motions constrain this epoch.'))
    (solution/'stellar_epoch.json').write_text(json.dumps(output, indent=2)+'\n')
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(years, [row['withheld_rms_px'] for row in profile], 'o-')
    ax.axvline(best_year, color='tab:red', linestyle='--')
    ax.set(xlabel='Trial epoch (Julian year)', ylabel='Withheld RMS [pixel]',
           title=f'Stellar proper-motion epoch: {status}')
    fig.tight_layout(); save_png(fig, solution/'stellar_epoch_profile.png', dpi=160); plt.close(fig)
    return output


def fit_refraction(solution, result, catalogue_path, stellar_epoch):
    solution = Path(solution)
    rows = _read(solution/'star_coordinates.csv')
    xy = np.array([[_float(row, 'x_px'), _float(row, 'y_px')] for row in rows])
    camera = _camera_from_result(result)
    arrays = _catalogue_arrays(rows, catalogue_path)
    year = stellar_epoch['epoch_jyear'] if stellar_epoch['status'] != 'not_identifiable' else 2000.
    target = propagated_catalogue(arrays, year)
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
    altitude = np.asarray(altitude_deg, dtype=float)
    zenith_distance = 90.-altitude
    answer = np.full(altitude.shape, np.nan)
    valid = altitude > 0.
    z = zenith_distance[valid]
    answer[valid] = 1./(np.cos(np.deg2rad(z))+.50572*(96.07995-z)**-1.6364)
    return answer


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
    metadata = observation_metadata(result)
    altitude_by_id = {}
    if (metadata.get('observation_time') and metadata.get('latitude') is not None
            and metadata.get('longitude') is not None):
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord
        from astropy.time import Time
        location = EarthLocation.from_geodetic(metadata['longitude']*u.deg,
            metadata['latitude']*u.deg, metadata.get('elevation_m', 0.)*u.m)
        ordered = list(coordinates.values())
        sky = SkyCoord([_float(row, 'catalog_ra_deg') for row in ordered]*u.deg,
                       [_float(row, 'catalog_dec_deg') for row in ordered]*u.deg,
                       frame='icrs')
        horizontal = sky.transform_to(AltAz(obstime=Time(metadata['observation_time']),
            location=location, pressure=0*u.hPa))
        altitude_by_id = {row['detection_id']: float(altitude)
                          for row, altitude in zip(ordered, horizontal.alt.deg)}
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
        positive = fluxes > 0
        mags[positive] = -2.5*np.log10(fluxes[positive])
        catalogue_magnitude = _float(coordinate, 'magnitude')
        altitude = altitude_by_id.get(identity, float('nan'))
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

    base_usable = [row for row in records if row['saturated'] == 'False'
                   and row['source_class'] == 'compact'
                   and np.isfinite(row['airmass']) and row['airmass'] <= 4.
                   and _float(coordinates[row['detection_id']], 'residual_px') <= 1.5]
    channels = list('RGB') if colour['classification'] == 'rgb' else ['G']
    extinction_by_channel = {}
    plot_data = {}
    for channel in channels:
        fit_rows = [row for row in base_usable if np.isfinite(row[f'{channel}_mag'])]
        if len(fit_rows) < 12:
            continue
        x = np.array([row['airmass'] for row in fit_rows])
        y = np.array([row[f'{channel}_minus_catalogue_mag'] for row in fit_rows])
        fitted, keep = _robust_line(x, y)
        if fitted is None:
            continue
        for row, retained in zip(fit_rows, keep):
            row[f'{channel}_used_for_extinction'] = bool(retained)
        fitted['airmass_range'] = [float(np.min(x[keep])), float(np.max(x[keep]))]
        fitted['airmass_span'] = float(np.ptp(x[keep]))
        fitted['status'] = ('fitted' if fitted['airmass_span'] >= .3
                            else 'insufficient_airmass_leverage')
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
            ax.set_title(f"{channel}: k={fitted['coefficient_mag_per_airmass']:.3f} ± "
                         f"{fitted['coefficient_sigma_mag_per_airmass']:.3f}",
                         fontsize=9, color=colours[channel])
            ax.set_xlabel('Airmass', fontsize=8)
            ax.set_ylabel(r'$m_{machine}-m_{catalogue}$ [mag]', fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=.2)
        fig.suptitle('Atmospheric-extinction fits by stored image channel', fontsize=10)
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
                   usable_unsaturated_compact_stars=len(base_usable), calibrated=False,
                   image_colour=colour, channels_fitted=channels,
                   extinction=representative,
                   extinction_by_channel=extinction_by_channel,
                   extinction_status=(representative['status']
                                      if representative else 'not_fitted'),
                   epoch_and_site_source=metadata.get('epoch_source'),
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


def fit_planet_epoch(image_path, solution, result, stellar_epoch, search_days=366, gate_px=3.):
    """Fit an epoch by matching ephemeris planets to unused measured sources."""
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
