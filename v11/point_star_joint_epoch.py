"""Common Barghini-camera and moving-source epoch profiles for v11.

All astrometric costs are angular, with per-source uncertainty scales. The
profiles are conditional on assignments and an approximate geocentric planet
model. They are not precision UTC measurements or calibrated false-alarm odds.
"""
from copy import deepcopy
import csv
import json
import shutil
from pathlib import Path
import numpy as np
from astropy.time import Time
from scipy.optimize import brentq, least_squares, minimize_scalar

from point_star_barghini import (BarghiniCamera, ARCMIN_PER_RADIAN,
    tangent_residuals_arcmin, radial_soft_l1_residuals)


def qualifies(matches):
    """No duplicate body, duplicate source, or single-body date claim."""
    return (len(matches) >= 2 and
            len({str(m['planet']).lower() for m in matches}) == len(matches) and
            len({str(m['detection_id']) for m in matches}) == len(matches))


def interval_boundary_record(interval, local_limits, global_limits):
    """Separate data-measured crossings from finite physical/search cutoffs."""
    lower, upper = interval
    lower_kind = ('data_threshold' if lower is not None else
                  'supported_ephemeris_start' if abs(local_limits[0]-global_limits[0]) < 1e-7 else 'local_profile_limit')
    upper_kind = ('data_threshold' if upper is not None else
                  'causal_present_time' if abs(local_limits[1]-global_limits[1]) < 1e-7 else 'local_profile_limit')
    return dict(allowed_interval_95_jd_tdb=[local_limits[0] if lower is None else lower,
                                           local_limits[1] if upper is None else upper],
                lower_interval_boundary=lower_kind, upper_interval_boundary=upper_kind,
                data_bounded_both_sides=lower is not None and upper is not None,
                interval_interpretation='Conditional profile set within searched interval; endpoints at search limits '
                                        'are truncation bounds, not measured uncertainty crossings')


def relative_brightness_evidence(matches, photometry, predicted, scatter_mag=1.5):
    """Soft relative brightness after profiling one nuisance zero point.

    Use a single common native channel, never compare unlike channels between
    bodies. Saturated/unknown and missing measurements are neutral. The large
    1.5-mag floor covers passband, colour, extinction and vignetting mismatch;
    it is NOT calibrated photometry. No centroid or astrometric score is edited.
    """
    if not np.isfinite(scatter_mag) or scatter_mag <= 0:
        raise ValueError('Brightness scatter must be positive')
    alternatives = []
    for channel in ('G', 'G1', 'R', 'B', 'G2'):
        rows = []
        for match in matches:
            name = match['planet'].lower()
            measured = photometry.get(str(match['detection_id']), {})
            try:
                rate = float(measured.get(f'{channel}_count_rate_adu_per_s', 'nan'))
                mag = float(predicted.get(name, 'nan'))
            except (ValueError, TypeError):
                continue
            known = str(measured.get('saturation_known', '')).lower() == 'true'
            unsaturated = str(measured.get(f'{channel}_saturated', '')).lower() == 'false'
            if known and unsaturated and rate > 0 and np.isfinite([rate, mag]).all():
                instrumental = -2.5*np.log10(rate)
                rows.append(dict(planet=match['planet'], detection_id=match['detection_id'],
                                 count_rate_adu_per_s=rate, predicted_V_mag=mag,
                                 instrumental_mag=float(instrumental),
                                 offset_mag=float(instrumental-mag)))
        alternatives.append((channel, rows))
    channel, rows = max(alternatives, key=lambda item: len(item[1]))
    answer = dict(status='neutral', cost=0., channel=channel, rows=rows,
                  scatter_floor_mag=float(scatter_mag), zero_point_mag=None,
                  reason='Fewer than two usable same-channel unsaturated measurements',
                  limitation='Soft relative identity evidence only; broad passband/extinction scatter; '
                             'saturated and unknown measurements are neutral, not wing-fit magnitudes.')
    if len(rows) < 2:
        return answer
    offsets = np.array([r['offset_mag'] for r in rows])
    fit = least_squares(lambda z: (offsets-z[0])/scatter_mag,
                        [np.median(offsets)], loss='soft_l1')
    for row in rows:
        row['residual_mag'] = row['offset_mag']-float(fit.x[0])
    answer.update(status='soft_relative_evidence', cost=float(fit.cost),
                  zero_point_mag=float(fit.x[0]), reason='Profiled common native-channel zero point')
    return answer


def select_joint_candidate(candidates, *, failures=0):
    """Separate positional uniqueness from soft brightness ordering."""
    answer = dict(adopted_index=None, best_index=None, competing_indices=[])
    if failures:
        return dict(answer, status='joint_epoch_failed', reason='Incomplete joint profiles; stellar solution retained')
    if not candidates:
        return dict(answer, status='joint_epoch_not_attempted_insufficient_planets',
                    reason='No distinct multi-body hypothesis; stellar solution retained')
    viable = [i for i, c in enumerate(candidates) if c['eligible']]
    if not viable:
        return dict(answer, status='joint_epoch_inconsistent', reason='All joint candidates contradicted')
    # Inherited matched-count hierarchy, not a calibrated global Bayes factor.
    most = max(candidates[i]['planet_count'] for i in viable)
    tier = [i for i in viable if candidates[i]['planet_count'] == most]
    positional = min(tier, key=lambda i: candidates[i]['cost'])
    def membership(c):
        return set(map(tuple, c.get('fitted_pairs', [])))
    peers = [i for i in tier if membership(candidates[i]) != membership(candidates[positional])
             or candidates[i]['cost'] <= candidates[positional]['cost']+4.5]
    ranked = sorted(peers, key=lambda i: candidates[i]['cost']+candidates[i]['brightness']['cost'])
    best = ranked[0]
    chosen = candidates[best]
    answer.update(best_index=best, competing_indices=[i for i in peers if i != best],
                  positional_best_index=positional, brightness_ranked_indices=ranked)
    accepted = (len(peers) == 1 and chosen['bounded'] and chosen['association_converged']
                and chosen['physical_checks_passed'])
    reasons = []
    if len(peers) > 1:
        reasons.append('competing dates/identities (different stellar memberships remain incomparable)')
    if not chosen['bounded']:
        reasons.append('uncertainty truncated by a search boundary')
    if not chosen['association_converged']:
        reasons.append('stellar membership did not converge')
    if not chosen['physical_checks_passed']:
        reasons.append('physical-zenith/visibility checks remain unresolved')
    return dict(answer, adopted_index=best if accepted else None,
        status='joint_epoch_fitted' if accepted else 'joint_epoch_ambiguous',
        reason=('Unique bounded common-camera profile, conditional on model and candidate search'
                if accepted else '; '.join(reasons)+'. Stellar solution retained.'))


def _read_csv(path):
    if not Path(path).is_file():
        return []
    with Path(path).open() as handle:
        return list(csv.DictReader(handle))


def _write_json(path, record):
    Path(path).write_text(json.dumps(record, indent=2, allow_nan=False)+'\n')


def planet_product_view(planets, joint):
    """One identity/date authority for PDF, FITS and photometry exports."""
    if not joint or joint['status'] == 'joint_epoch_not_attempted_control':
        return planets
    index = joint.get('best_index')
    best = joint['candidates'][index] if index is not None else None
    selected = deepcopy(best['matches']) if best else []
    adopted = joint.get('adopted', False)
    out = dict(planets, metadata_matches=[], predicted_planets=[],
               metadata_validation_matches=planets.get('metadata_validation_matches', planets.get('metadata_matches', [])),
               global_proposals_file='global_planet_proposals.json',
               joint_epoch_status=joint['status'],
               matches=selected if adopted else [], candidate_matches=[] if adopted else selected,
               match_count=len(selected) if adopted else 0,
               best_candidate_epoch_tdb=best['epoch_tdb'] if best else None,
               best_candidate_jd_tdb=best['jd_tdb'] if best else None,
               derived_epoch_utc=Time(best['jd_tdb'], format='jd', scale='tdb').utc.isot if adopted else None,
               status='planet_epoch_fitted' if adopted else 'planet_epoch_ambiguous',
               confidence='conditional_joint_epoch' if adopted else 'unconfirmed_joint_candidates')
    if adopted:
        out['candidates'] = [dict(epoch_tdb=best['epoch_tdb'], jd_tdb=best['jd_tdb'], matches=selected)]
    else:
        out['candidates'] = [dict(epoch_tdb=c['epoch_tdb'], jd_tdb=c['jd_tdb'], matches=deepcopy(c['matches']))
                             for c in joint.get('candidates', [])]
        if not out['candidates']:
            out['candidates'] = deepcopy(planets.get('candidates', []))
    return out


def publish_candidate_files(staging, output, *, include_state=False):
    """Recoverably promote this run's staged products, restoring on failure."""
    staging, output = Path(staging), Path(output)
    archive = output/'stellar_only_products'
    archive.mkdir(exist_ok=False)
    files = sorted(p for p in staging.iterdir() if p.is_file()
                   and (include_state or p.name not in ('result.json', 'science_summary.json', 'planet_epoch.json')))
    existed = set()
    for path in files:
        destination = output/path.name
        if destination.is_file():
            shutil.copy2(destination, archive/path.name)
            existed.add(path.name)
    attempted = []
    try:
        for path in files:
            attempted.append(path.name)
            shutil.copy2(path, output/path.name)
    except Exception:
        for name in attempted:
            destination = output/name
            if name in existed:
                # Restoration uses a distinct operation, not the failed copier.
                destination.write_bytes((archive/name).read_bytes())
            elif destination.is_file():
                destination.unlink()
        raise


def write_joint_coordinates(output, result, catalogue, detections, fitted):
    """Save positions from the fitted model, not cosmetic overlay displacements."""
    from point_star_barghini import (astrometric_stats, plate_scale_summary,
        angular_separations_arcmin, resolved_association_gate_arcmin,
        FINAL_ASSOCIATION_PHYSICAL_FLOOR_ARCMIN)
    output = Path(output)
    camera = BarghiniCamera.from_serialised(fitted['camera'])
    year = float(Time(fitted['jd_tdb'], format='jd', scale='tdb').jyear)
    sky = catalogue.at_year(year)
    xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in detections])
    ii, jj = np.array(fitted['fitted_pairs']).T
    predictions = camera.project(sky[jj])
    measured_sky = camera.to_sky(xy[ii])
    residuals = angular_separations_arcmin(measured_sky, sky[jj])
    def ra_dec(v):
        return float(np.rad2deg(np.arctan2(v[1], v[0])) % 360), float(np.rad2deg(np.arctan2(v[2], np.linalg.norm(v[:2]))))
    rows = []
    for i, j, p, ray, residual in zip(ii, jj, predictions, measured_sky, residuals):
        detection, star = detections[i], catalogue.rows[j]
        ra, dec = ra_dec(sky[j])
        mra, mdec = ra_dec(ray)
        rows.append(dict(detection_id=detection['detection_id'], star_id=star['star_id'],
            catalog_ra_deg=star['ra_deg'], catalog_dec_deg=star['dec_deg'], magnitude=star['mag'],
            x_px=float(xy[i, 0]), y_px=float(xy[i, 1]), predicted_x_px=float(p[0]), predicted_y_px=float(p[1]),
            residual_px=float(np.linalg.norm(p-xy[i])), residual_arcmin=float(residual), usage='fitted',
            source_class=detection['source_class'], saturated=detection['saturated'],
            propagated_ra_deg=ra, propagated_dec_deg=dec, coordinate_epoch_jyear=year,
            reference_epoch_jyear=star['reference_epoch_jyear'], proper_motion_available=bool(catalogue.has_motion[j]),
            measured_ra_deg=mra, measured_dec_deg=mdec))
    with (output/'star_coordinates.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    identities = {str(r['detection_id']): r['star_id'] for r in rows}
    blobs = []
    for i, d in enumerate(detections):
        if d['source_class'] == 'broad_blob' or str(d['saturated']).lower() == 'true':
            ra, dec = ra_dec(camera.to_sky(xy[i:i+1])[0])
            blobs.append(dict(d, fitted_ra_deg=ra, fitted_dec_deg=dec,
                              catalogue_star_id=identities.get(str(d['detection_id']), ''), classification='unclassified_object'))
    with (output/'blob_candidates.csv').open('w', newline='') as handle:
        fields = list(detections[0])+['fitted_ra_deg', 'fitted_dec_deg', 'catalogue_star_id', 'classification']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(blobs)
    result.update(camera=camera.serialise(), coordinate_epoch_jyear=year,
        coordinate_epoch_source='joint_stellar_planet_profile',
        fit=astrometric_stats(camera, xy[ii], sky[jj]), plate_scale=plate_scale_summary(camera),
        unmatched_dots=len(detections)-len(rows), broad_or_saturated_objects=len(blobs),
        broad_or_saturated_without_star_match=sum(not b['catalogue_star_id'] for b in blobs),
        final_fit=dict(success=True, cost=fitted['cost'], objective=fitted['objective'],
                       stellar_count=len(rows), planet_count=fitted['planet_count']))
    result.setdefault('association', {})['final_gate_arcmin'] = resolved_association_gate_arcmin(
        camera, FINAL_ASSOCIATION_PHYSICAL_FLOOR_ARCMIN)
    return rows


def _adopt_joint_solution(image_path, output, result, science, cat, detections, fitted, initial):
    """Stage all derived products and recheck physical constraints before adoption."""
    from point_star_science import fit_refraction, measure_photometry
    from point_star_barghini import annotate_stars
    from point_star_diagnostics import write_diagnostics
    from point_star_planets import predict_other_planets, _visible_projection, _attach_identified_photometry
    from point_star_planet_ephemeris import planet_vectors
    from point_star_planet_solar import SolarConstraint, classify_night, zenith_envelope
    staging = output/'joint_candidate_solution'
    staging.mkdir(exist_ok=False)
    # Only this run's own inputs are copied; the original authoritative files
    # remain untouched until regenerated physical checks pass.
    for name in ('dots',):
        shutil.copytree(output/name, staging/name)
    for path in output.iterdir():
        if path.is_file() and path.suffix in ('.json', '.csv', '.npz'):
            shutil.copy2(path, staging/path.name)
    updated = deepcopy(initial)
    rows = write_joint_coordinates(staging, updated, cat, detections, fitted)
    epoch = dict(initial.get('stellar_epoch') or {}, applied_epoch_jyear=updated['coordinate_epoch_jyear'])
    refraction = fit_refraction(staging, updated, None, epoch)
    photometry = measure_photometry(image_path, staging, updated, refraction)
    zenith_info = photometry.get('photometric_zenith') or {}
    zenith = zenith_info.get('zenith_unit_vector')
    if zenith_info.get('status') != 'conditional_zenith' or zenith is None:
        return False, 'Joint-camera photometric zenith is not identifiable; staged products retained separately'
    camera = BarghiniCamera.from_serialised(fitted['camera'])
    measured = camera.to_sky([[m['measured_x_px'], m['measured_y_px']] for m in fitted['matches']])
    directions = np.array([m['predicted_sky_vector'] for m in fitted['matches']])
    if not np.isfinite(_visible_projection(camera, directions, zenith)).all() or np.any(measured@zenith < -1e-9):
        return False, 'Joint-camera photometric zenith invalidates planet visibility'
    by_id = {str(r['detection_id']): r for r in detections}
    fixed = [by_id[str(i)] for i in zenith_info.get('fitted_detection_ids', [])]
    rays = camera.to_sky([[float(r['x_px']), float(r['y_px'])] for r in fixed])
    solar = SolarConstraint(classify_night(updated, len(rows)), zenith_envelope(rays), zenith_unit_vector=zenith)
    if solar.assess(fitted['jd_tdb'])['status'] != 'solar_consistent':
        return False, 'Joint-camera photometric zenith leaves solar consistency unresolved'
    final_planets = planet_product_view(science['planets'], dict(
        status='joint_epoch_fitted', adopted=True, best_index=0, candidates=[fitted]))
    final_planets.update(status='planet_epoch_fitted', matches=fitted['matches'],
        match_count=fitted['planet_count'], best_candidate_jd_tdb=fitted['jd_tdb'],
        best_candidate_epoch_tdb=fitted['epoch_tdb'],
        derived_epoch_utc=Time(fitted['jd_tdb'], format='jd', scale='tdb').utc.isot,
        rms_arcmin=fitted['planet_rms_arcmin'],
        rms_px=float(np.sqrt(np.mean([m['separation_px']**2 for m in fitted['matches']]))),
        confidence='conditional_joint_epoch', candidate_matches=[])
    final_planets['visibility'] = dict(final_planets.get('visibility') or {}, zenith_unit_vector=zenith)
    final_planets['predicted_planets'] = predict_other_planets(camera, final_planets, planet_vectors)
    _attach_identified_photometry(staging, final_planets)
    annotate_stars(image_path, rows, staging, 40, names_cache=output/'display_names.json', offline=True)
    ii, jj = np.array(fitted['fitted_pairs']).T
    xy = np.array([[float(d['x_px']), float(d['y_px'])] for d in detections])
    sky = cat.at_year(updated['coordinate_epoch_jyear'])
    write_diagnostics(image_path, xy[ii], camera.project(sky[jj]), staging,
                      unmatched=xy[np.setdiff1d(np.arange(len(xy)), ii)], camera=camera)
    staged_science = dict(science, refraction=refraction, photometry=photometry, planets=final_planets)
    _write_json(staging/'result.json', updated)
    _write_json(staging/'science_summary.json', staged_science)
    _write_json(staging/'planet_epoch.json', final_planets)
    publish_candidate_files(staging, output, include_state=True)
    result.update(updated)
    science.update(staged_science)
    return True, 'Joint coordinates and regenerated photometry/visibility checks adopted'


def attempt_adoption(image_path, output, result, science, cat, detections, fitted, initial):
    """Convert staged numerical/I/O failures into an explicit stellar fallback."""
    saved_result, saved_science = deepcopy(result), deepcopy(science)
    try:
        accepted, reason = _adopt_joint_solution(image_path, output, result, science,
                                                cat, detections, fitted, initial)
        return accepted, reason, False
    except (ValueError, RuntimeError, KeyError, OSError, FloatingPointError) as exc:
        result.clear(); result.update(saved_result)
        science.clear(); science.update(saved_science)
        return False, f'Joint product regeneration failed; stellar solution retained: {exc}', True


def refine_joint_epoch(image_path, output, result, science, catalogue_path):
    """Profile global hypotheses; preserve the stellar authority on every fallback.

    Never reads the supplied timestamp for selection. Its comparison is written
    only AFTER all profiles and the selection have been fixed.
    """
    from point_star_epoch import Catalogue
    from point_star_barghini import (associate, resolved_association_gate_arcmin,
        FINAL_ASSOCIATION_PHYSICAL_FLOOR_ARCMIN, angular_separations_arcmin)
    from point_star_planet_ephemeris import planet_vectors
    from point_star_planet_brightness import planet_brightness, BRIGHT_PLANETS, SOURCE
    from point_star_planet_solar import SolarConstraint, classify_night, zenith_envelope
    from point_star_planet_nondetections import check_candidate_absences
    from point_star_planets import _visible_projection, _load_sky_footprint
    output = Path(output)
    initial = deepcopy(result)
    _write_json(output/'stellar_only_result.json', initial)
    planets = science['planets']
    _write_json(output/'global_planet_proposals.json', planets)
    if result.get('epoch_mode') in ('fixed', 'catalog'):
        record = dict(status='joint_epoch_not_attempted_control', adopted=False,
                      adopted_index=None, best_index=None, candidates=[], failures=[],
                      reason='Explicit stellar epoch control preserved; no joint epoch adoption attempted',
                      metadata_used_in_fit=result.get('epoch_mode') == 'fixed',
                      search_mode='global_planets_with_control_camera')
        result['joint_epoch'] = science['joint_epoch'] = record
        _write_json(output/'joint_epoch.json', record)
        _write_json(output/'result.json', result)
        _write_json(output/'science_summary.json', science)
        return record
    rows = _read_csv(output/'star_coordinates.csv')
    detections = _read_csv(output/'dots/star_candidates.csv')
    cat = Catalogue.from_rows(_read_csv(catalogue_path))
    cat_indices = {r['star_id']: i for i, r in enumerate(cat.rows)}
    detection_indices = {str(r['detection_id']): i for i, r in enumerate(detections)}
    xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in detections])
    initial_pairs = [(detection_indices[str(r['detection_id'])], cat_indices[r['star_id']]) for r in rows]
    camera = BarghiniCamera.from_serialised(result['camera'])
    sigma = max(3., float(result['fit'].get('rms_arcmin', 3.)))
    low = float(Time(1850., format='jyear', scale='tdb').jd)
    high = min(float(Time(2036., format='jyear', scale='tdb').jd),
               float(result['causal_epoch_ceiling']['jd_tdb']))
    zenith_info = science['photometry'].get('photometric_zenith') or {}
    zenith = zenith_info.get('zenith_unit_vector')
    photo = {str(r['detection_id']): r for r in _read_csv(output/'source_photometry.csv')}
    fixed_ids = {str(i) for i in zenith_info.get('fitted_detection_ids', [])}
    fixed_indices = [detection_indices[i] for i in fixed_ids if i in detection_indices]
    record = dict(status='joint_epoch_pending', adopted=False, candidates=[], failures=[],
        metadata_used_in_fit=False, search_mode='blind_global',
        initial_stellar_epoch=deepcopy(result.get('stellar_epoch')),
        initial_camera=deepcopy(result['camera']), initial_fit=deepcopy(result['fit']),
        supported_search_jd_tdb=[low, high], brightness_model=SOURCE,
        uncertainty_scales_arcmin=dict(stars=sigma, planets=sigma),
        limitations=['Global proposals use the initial stellar camera; not an exhaustive joint camera/date search.',
            'Matched-count hierarchy and positional delta-cost <=4.5 competitor rule are heuristic, not false-alarm odds.',
            'Geocentric apparent planet vectors versus ICRS proper-motion stars retain frame/aberration limitations; '
            '3-arcminute per-source uncertainty floor is conservative, not a correction.',
            'Topocentric parallax and integrated atmospheric refraction remain unmodelled; intervals exclude these systematics.',
            'Image-derived zenith is a fixed conditional visibility constraint; metadata site is not used.'])
    candidates = record['candidates']
    for rank, proposal in enumerate(planets.get('candidates', []), 1):
        matches = proposal['matches']
        if not qualifies(matches):
            continue
        print(f'Joint epoch: global candidate {rank}, {len(matches)} bodies', flush=True)
        try:
            excluded = {str(m['detection_id']) for m in matches}
            pairs = [(i, j) for i, j in initial_pairs if str(detections[i]['detection_id']) not in excluded]
            allowed = np.array([i for i, r in enumerate(detections) if str(r['detection_id']) not in excluded])
            centre = float(proposal['jd_tdb'])
            a, b = proposal.get('positional_interval_jd_tdb', [centre, centre])
            padding = max(1., (b-a)/2, 4*float(proposal.get('conditional_time_sigma_minutes') or 0)/1440.)
            limits = (max(low, a-padding), min(high, b+padding))
            iterations = []
            trial_camera = camera
            for iteration in range(6):
                ii, jj = np.array(pairs).T
                fitted = profile_joint_candidate(trial_camera, xy[ii], cat.subset(jj), matches,
                            planet_vectors, limits, star_sigma_arcmin=sigma, planet_sigma_arcmin=sigma)
                trial_camera = BarghiniCamera.from_serialised(fitted['camera'])
                year = float(Time(fitted['jd_tdb'], format='jd', scale='tdb').jyear)
                sky = cat.at_year(year)
                gate = resolved_association_gate_arcmin(trial_camera, FINAL_ASSOCIATION_PHYSICAL_FLOOR_ARCMIN)
                ai, aj = associate(trial_camera, xy[allowed], sky, gate)
                updated = list(zip(allowed[ai].tolist(), aj.tolist()))
                converged = set(updated) == set(pairs)
                iterations.append(dict(iteration=iteration+1, fitted_pairs=[list(p) for p in pairs],
                    proposed_count=len(updated), converged=converged, jd_tdb=fitted['jd_tdb']))
                if converged or iteration == 5:
                    break
                pairs = updated
            fitted.update(global_candidate_rank=rank, association_iterations=iterations,
                          association_converged=converged, fitted_pairs=[list(p) for p in pairs])
            fitted.update(interval_boundary_record(fitted['interval_95_jd_tdb'],
                                                   fitted['search_limits_jd_tdb'], [low, high]))
            # Distinct initial passages may converge to the same date/assignment.
            identity = sorted((m['planet'].lower(), str(m['detection_id'])) for m in matches)
            duplicate = next((c for c in candidates if c['identity'] == identity
                              and abs(c['jd_tdb']-fitted['jd_tdb']) < 1e-4), None)
            if duplicate is not None:
                duplicate.setdefault('duplicate_global_ranks', []).append(rank)
                continue
            fitted['identity'] = identity
            directions = np.array([m['predicted_sky_vector'] for m in fitted['matches']])
            projected = _visible_projection(trial_camera, directions, zenith)
            measured_xy = np.array([[m['measured_x_px'], m['measured_y_px']] for m in matches])
            measured_rays = trial_camera.to_sky(measured_xy)
            visible = zenith is not None and np.isfinite(projected).all()
            if zenith is not None:
                z = np.array(zenith)/np.linalg.norm(zenith)
                measured_alt = np.rad2deg(np.arcsin(np.clip(measured_rays@z, -1, 1)))
                predicted_alt = np.rad2deg(np.arcsin(np.clip(directions@z, -1, 1)))
                visible = bool(visible and np.all(measured_alt >= -1e-7))
                for m, ma, pa in zip(fitted['matches'], measured_alt, predicted_alt):
                    m.update(measured_altitude_deg=float(ma), predicted_altitude_deg=float(pa))
            geometry = all(m['separation_arcmin'] <= planets.get('gate_arcmin', 30.) for m in fitted['matches'])
            conflicts = []
            for m in fitted['matches']:
                original = next((r for r in rows if str(r['detection_id']) == str(m['detection_id'])), None)
                if original:
                    ray = trial_camera.to_sky([[m['measured_x_px'], m['measured_y_px']]])
                    star_res = float(angular_separations_arcmin(ray, sky[[cat_indices[original['star_id']]]])[0])
                    delta = (star_res**2-m['separation_arcmin']**2)/sigma**2
                    passes = m['separation_arcmin'] < star_res if len(matches) >= 3 else delta >= 9.
                    conflicts.append(dict(detection_id=m['detection_id'], star_id=original['star_id'],
                                          star_residual_arcmin=star_res, delta_chi2=delta, passes=bool(passes)))
            geometry = geometry and all(c['passes'] for c in conflicts)
            fitted['star_identity_checks'] = conflicts
            envelope = zenith_envelope(trial_camera.to_sky(xy[fixed_indices])) if fixed_indices else zenith_envelope([])
            solar = SolarConstraint(classify_night(result, len(pairs)), envelope, zenith_unit_vector=zenith)
            solar_evidence = solar.assess(fitted['jd_tdb'])
            fitted['solar_evidence'] = solar_evidence
            # Re-evaluate the inherited local-depth absence screen at this camera/date.
            absence_candidate = dict(proposal, jd_tdb=fitted['jd_tdb'], epoch_tdb=fitted['epoch_tdb'],
                matches=fitted['matches'], solar_evidence=solar_evidence,
                rms_arcmin=fitted['planet_rms_arcmin'], cost_arcmin2=sum(m['separation_arcmin']**2 for m in fitted['matches']))
            absence_input = dict(planets, candidates=[absence_candidate])
            checked = check_candidate_absences(image_path, absence_input, trial_camera, detections,
                rows, planet_vectors, valid_mask=_load_sky_footprint(output), solution=output)
            absence = checked['candidates'][0]
            fitted.update(non_detection_evidence=absence['non_detection_evidence'],
                          absence_penalty=absence['absence_penalty'])
            predicted = {name: float(planet_brightness(name, [fitted['jd_tdb']])[0])
                         for name in BRIGHT_PLANETS if name in {m['planet'].lower() for m in matches}}
            fitted['brightness'] = relative_brightness_evidence(matches, photo, predicted)
            fitted['eligible'] = bool(geometry and visible and not absence['absence_penalty']
                                      and solar_evidence['status'] != 'solar_inconsistent')
            fitted['physical_checks_passed'] = bool(visible and zenith_info.get('status') == 'conditional_zenith'
                                                    and solar_evidence['status'] == 'solar_consistent')
            candidates.append(fitted)
        except (ValueError, RuntimeError, KeyError, FloatingPointError) as exc:
            record['failures'].append(dict(global_candidate_rank=rank, error=f'{type(exc).__name__}: {exc}'))
        _write_json(output/'joint_epoch.json', record)
    record.update(select_joint_candidate(candidates, failures=len(record['failures'])))
    record['adopted'] = record['adopted_index'] is not None
    best = candidates[record['best_index']] if record['best_index'] is not None else None
    if best:
        record['best_candidate_epoch_tdb'] = best['epoch_tdb']
        record['best_candidate_jd_tdb'] = best['jd_tdb']
    if record['adopted']:
        accepted, reason, failed = attempt_adoption(image_path, output, result, science, cat, detections,
                                                    candidates[record['adopted_index']], initial)
        record['final_product_check'] = reason
        if not accepted:
            record.update(adopted=False, adopted_index=None,
                          status='joint_epoch_failed' if failed else 'joint_epoch_ambiguous', reason=reason)
    # Metadata is now a comparison only, on the final candidate camera.
    if best:
        supplied = planets.get('observation_time_metadata') or {}
        metadata_jd = supplied.get('jd_tdb')
        if metadata_jd is not None:
            fitted_camera = BarghiniCamera.from_serialised(best['camera'])
            comparisons = []
            for m in best['matches']:
                predicted = planet_vectors(m['planet'].lower(), [metadata_jd])
                p = fitted_camera.project(predicted)[0]
                ray = fitted_camera.to_sky([[m['measured_x_px'], m['measured_y_px']]])
                comparisons.append(dict(planet=m['planet'], detection_id=m['detection_id'],
                    metadata_predicted_x_px=float(p[0]), metadata_predicted_y_px=float(p[1]),
                    metadata_residual_arcmin=float(angular_separations_arcmin(ray, predicted)[0]),
                    joint_candidate_residual_arcmin=m['separation_arcmin']))
            record['metadata_comparison'] = dict(used_in_fit=False,
                candidate_minus_metadata_seconds=86400*(best['jd_tdb']-metadata_jd), rows=comparisons)
    from point_star_metadata import fits_clock_audit
    record['fits_clock_audit'] = fits_clock_audit(image_path)
    result['joint_epoch'] = record
    import hashlib
    result.setdefault('code_sha256', {}).update({name: hashlib.sha256(
        (Path(__file__).parent/name).read_bytes()).hexdigest() for name in
        ('point_star_joint_epoch.py', 'point_star_joint_report.py', 'point_star_metadata.py', 'point_star_fits.py')})
    science['joint_epoch'] = record
    science['planets'] = planet_product_view(science['planets'], record)
    from point_star_planets import _attach_identified_photometry
    _attach_identified_photometry(output, science['planets'])
    _write_json(output/'planet_epoch.json', science['planets'])
    _write_json(output/'joint_epoch.json', record)
    _write_json(output/'result.json', result)
    _write_json(output/'science_summary.json', science)
    print(f"Joint epoch: {record['status']}; camera {'adopted' if record['adopted'] else 'unchanged'}", flush=True)
    return record


def _fit_weighted_camera(camera, xy, sky, sigmas):
    scale = camera.scale
    h, w = camera.shape
    lower = [-np.pi, -.5, -.5, -.5, -.5, -2., -.8, .01]
    upper = [np.pi, w/scale+.5, h/scale+.5, w/scale+.5, h/scale+.5, 3., .8, 5.]
    def residual(p):
        model = BarghiniCamera(camera.shape, camera.reference_rotation, p, camera.detector_parity)
        angular = tangent_residuals_arcmin(model.to_sky(xy), sky)/sigmas[:, None]
        robust = radial_soft_l1_residuals(angular, 1.)
        penalty = np.maximum(1e-9-model.radial_slopes()*scale, 0)*ARCMIN_PER_RADIAN*1e6
        return np.r_[robust.ravel(), penalty]
    opt = least_squares(residual, camera.p, bounds=(lower, upper), loss='linear',
                        x_scale='jac', max_nfev=1200, ftol=1e-10, xtol=1e-10, gtol=1e-10)
    fitted = BarghiniCamera(camera.shape, camera.reference_rotation, opt.x, camera.detector_parity)
    if not opt.success or not fitted.is_monotonic():
        raise RuntimeError('Joint camera minimisation did not converge monotonically')
    return fitted


def profile_joint_candidate(camera, star_xy, catalogue, matches, vector_function,
                            jd_limits, *, star_sigma_arcmin=3., planet_sigma_arcmin=3.):
    """Refit ONE camera to BOTH stars and planets at every trial TDB epoch.

    The interval is the connected delta-cost=1.9207294 contour (nominal 95%
    one-parameter likelihood convention), conditional on fixed robust scales.
    A disconnected or unbounded profile is never declared bounded.
    """
    if not qualifies(matches):
        raise ValueError('Joint epoch requires distinct bodies and distinct detections')
    star_xy = np.asarray(star_xy, dtype=float)
    low, high = map(float, jd_limits)
    if not np.isfinite([low, high, star_sigma_arcmin, planet_sigma_arcmin]).all() or low >= high:
        raise ValueError('Finite increasing epoch limits and finite scales required')
    if min(star_sigma_arcmin, planet_sigma_arcmin) <= 0:
        raise ValueError('Positive angular uncertainty scales required')
    if len(star_xy) != len(catalogue.rows) or len(star_xy) < 12 or not np.isfinite(star_xy).all():
        raise ValueError('At least 12 finite paired stellar positions required')
    planet_xy = np.array([[m['measured_x_px'], m['measured_y_px']] for m in matches], float)
    if not np.isfinite(planet_xy).all():
        raise ValueError('Finite measured planet centroids required')
    xy = np.vstack([star_xy, planet_xy])
    sigmas = np.r_[np.full(len(star_xy), star_sigma_arcmin), np.full(len(matches), planet_sigma_arcmin)]
    cache = {}
    origin = (low+high)/2
    def evaluate(offset):
        jd = origin+float(offset)
        if jd not in cache:
            year = float(Time(jd, format='jd', scale='tdb').jyear)
            planets = np.array([vector_function(m['planet'].lower(), [jd])[0] for m in matches])
            sky = np.vstack([catalogue.at_year(year), planets])
            if sky.shape != (len(xy), 3) or not np.isfinite(sky).all():
                raise ValueError('Invalid trial ephemeris directions')
            fitted = _fit_weighted_camera(camera, xy, sky, sigmas)
            residual = tangent_residuals_arcmin(fitted.to_sky(xy), sky)
            robust = radial_soft_l1_residuals(residual/sigmas[:, None], 1.)
            costs = .5*np.sum(robust**2, axis=1)
            n = len(star_xy)
            cache[jd] = dict(jd_tdb=jd, cost=float(costs.sum()),
                stellar_cost=float(costs[:n].sum()), planet_cost=float(costs[n:].sum()),
                stellar_rms_arcmin=float(np.sqrt(np.mean(np.sum(residual[:n]**2, axis=1)))),
                planet_rms_arcmin=float(np.sqrt(np.mean(np.sum(residual[n:]**2, axis=1)))),
                camera=fitted.serialise(), _sky=planets)
        return cache[jd]
    grid = np.linspace(low-origin, high-origin, 17)
    values = [evaluate(x)['cost'] for x in grid]
    minima = [(grid[0], values[0]), (grid[-1], values[-1])]
    for i in range(1, len(grid)-1):
        if values[i] <= values[i-1] and values[i] <= values[i+1]:
            opt = minimize_scalar(lambda x: evaluate(x)['cost'],
                bounds=(grid[i-1], grid[i+1]), method='bounded', options={'xatol': 1e-6})
            if not opt.success:
                raise RuntimeError('Joint epoch minimisation failed')
            minima.append((float(opt.x), float(opt.fun)))
    best, cost = min(minima, key=lambda item: item[1])
    threshold = cost+1.920729410347062
    def crossing(direction):
        previous = best
        for x in sorted((x for x in grid if (x-best)*direction > 0), reverse=direction < 0):
            if evaluate(x)['cost'] > threshold:
                return float(origin+brentq(lambda z: evaluate(z)['cost']-threshold,
                                          min(x, previous), max(x, previous), xtol=1e-6))
            previous = x
        return None
    interval = [crossing(-1), crossing(1)]
    nodes = sorted(set([*map(float, grid), *[m[0] for m in minima]]))
    inside = [evaluate(x)['cost'] <= threshold for x in nodes]
    components = sum(yes and (i == 0 or not inside[i-1]) for i, yes in enumerate(inside))
    answer = {k: deepcopy(v) for k, v in evaluate(best).items() if k != '_sky'}
    fitted = BarghiniCamera.from_serialised(answer['camera'])
    predicted_sky = evaluate(best)['_sky']
    prediction = fitted.project(predicted_sky)
    residual = tangent_residuals_arcmin(fitted.to_sky(planet_xy), predicted_sky)
    fitted_matches = []
    for i, m in enumerate(matches):
        fitted_matches.append(dict(m, predicted_x_px=float(prediction[i, 0]),
            predicted_y_px=float(prediction[i, 1]), predicted_sky_vector=predicted_sky[i].tolist(),
            separation_px=float(np.linalg.norm(prediction[i]-planet_xy[i])),
            separation_arcmin=float(np.linalg.norm(residual[i]))))
    answer.update(matches=fitted_matches, epoch_tdb=Time(answer['jd_tdb'], format='jd', scale='tdb').isot,
        interval_95_jd_tdb=interval, bounded=all(x is not None for x in interval) and components == 1,
        confidence_components=components, search_limits_jd_tdb=[low, high],
        star_count=len(star_xy), planet_count=len(matches),
        star_sigma_arcmin=float(star_sigma_arcmin), planet_sigma_arcmin=float(planet_sigma_arcmin),
        profile=[{k: v for k, v in row.items() if k not in ('camera', '_sky')}
                 for _, row in sorted(cache.items())],
        objective='sum radial soft-L1 costs of angular residual / per-source sigma; scale=1',
        uncertainty='Conditional nominal 95% delta-cost interval; excludes correlated atmosphere, '
                    'frame, ephemeris and catalogue systematics, and global search false alarms')
    return answer
