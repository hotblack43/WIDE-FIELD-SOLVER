"""Standalone point-star calibration with the Barghini (2019) O/Z equations.

Input is the original untrailed image. The dot finder supplies measured pixels.
Tetra3 supplies a blind pattern bootstrap only; all final fitting uses equations
(5), (6), (11). Z is a fixed celestial reference direction, not a terrestrial
zenith. Stellar epoch is fitted from catalogue proper motions by default;
no observing location or timestamp seeds that search.
"""
import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

from barghini_model import (
    BarghiniParameters, detector_to_horizontal, horizontal_to_detector, radial_du_dr)
from point_star_detection import write_products
from point_star_plotting import save_png
from point_star_time_bounds import capture_time_ceiling, limit_epoch_range


SOLVER_VERSION = '0.6.0'


def vectors(ra, dec):
    ra, dec = np.deg2rad(ra), np.deg2rad(dec)
    return np.c_[np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)]


@dataclass
class BarghiniCamera:
    shape: tuple
    reference_rotation: np.ndarray
    p: np.ndarray

    @property
    def scale(self):
        return float(np.linalg.norm(self.shape)/2)

    @classmethod
    def initial(cls, shape, focal, rotation):
        scale = np.linalg.norm(shape)/2
        centre = (np.array(shape[::-1])-1)/(2*scale)
        return cls(tuple(shape), np.asarray(rotation),
                   np.r_[0., centre, centre, np.log(scale/focal), 0., 1.])

    @property
    def physical(self):
        p, scale = self.p, self.scale
        return BarghiniParameters(p[0], *list(p[1:5]*scale),
                                  np.exp(p[5])/scale, p[6], p[7]/scale)

    def to_sky(self, xy):
        a, z = detector_to_horizontal(*np.asarray(xy).T, self.physical)
        ray = np.c_[np.sin(z)*np.cos(a), np.sin(z)*np.sin(a), np.cos(z)]
        return ray @ self.reference_rotation.T

    def project(self, sky):
        ray = np.asarray(sky) @ self.reference_rotation
        a = np.arctan2(ray[:, 1], ray[:, 0])
        z = np.arctan2(np.linalg.norm(ray[:, :2], axis=1), ray[:, 2])
        x, y = horizontal_to_detector(a, z, self.physical)
        return np.c_[x, y]

    def radial_slopes(self):
        h, w = self.shape
        q = self.physical
        limit = np.linalg.norm(np.array([[0, 0], [w-1, 0], [0, h-1], [w-1, h-1]])
                               - [q.x_o, q.y_o], axis=1).max()
        return radial_du_dr(np.array([0., limit]), q.v, q.s, q.d)

    def is_monotonic(self):
        return bool(np.all(self.radial_slopes() > 0))

    def serialise(self):
        from dataclasses import asdict
        return dict(model='Barghini_2019_equations_5_6_11',
                    parameters=asdict(self.physical), normalised_parameters=self.p.tolist(),
                    reference_rotation=self.reference_rotation.tolist(), shape=list(self.shape),
                    reference_Z='fixed celestial direction from current blind bootstrap; not local zenith',
                    monotonic_on_detector=self.is_monotonic())


def fit_camera(camera, xy, sky, max_nfev=300):
    scale = camera.scale
    h, w = camera.shape
    lower = [-np.pi, -.5, -.5, -.5, -.5, -2., -.8, .01]
    upper = [np.pi, w/scale+.5, h/scale+.5, w/scale+.5, h/scale+.5, 3., .8, 5.]

    def residual(p):
        model = BarghiniCamera(camera.shape, camera.reference_rotation, p)
        return np.r_[((model.to_sky(xy)-sky)*scale).ravel(),
                     np.maximum(1e-6-model.radial_slopes(), 0)*scale*1e4]

    opt = least_squares(residual, camera.p, bounds=(lower, upper),
                        loss='soft_l1', f_scale=1., x_scale='jac',
                        max_nfev=max_nfev, ftol=1e-10, xtol=1e-10, gtol=1e-10)
    fitted = BarghiniCamera(camera.shape, camera.reference_rotation, opt.x)
    return fitted, dict(success=bool(opt.success), nfev=opt.nfev, cost=float(opt.cost))


def bootstrap(xy, shape):
    """Blind identification from training dots; no saved solutions or trail imports."""
    import tetra3
    # Compatibility needed by this repository's pinned tetra3 with NumPy 2.
    if not hasattr(np, 'math'):
        np.math = math
    solver = tetra3.Tetra3()
    h, w = shape
    attempts = []
    patches = [(fraction, dx, dy) for fraction in (.18, .25, .14)
               for dx, dy in ((0, 0), (-.125, 0), (.125, 0), (0, -.125), (0, .125))]
    # Preserve the established search before trying a cheaper local hypothesis.
    # A wide distortion range can exhaust tetra3's lookup budget before reaching
    # a valid pattern. Zero local distortion is only a bootstrap hypothesis;
    # the full Barghini lens model is still fitted to the original centroids.
    for distortion in ([-.2, .2], 0.):
        for fraction, dx, dy in patches:
            size = round(min(shape)*fraction)
            origin = np.array([(w-size)//2+round(dx*w), (h-size)//2+round(dy*h)])
            local = xy-origin
            keep = np.all((local >= 0) & (local < size), axis=1)
            local = local[keep][:80]
            if len(local) < 8:
                continue
            answer = solver.solve_from_centroids(local[:, ::-1]+.5, (size, size),
                pattern_checking_stars=20, match_radius=.012, match_threshold=1e-6,
                solve_timeout=5000, distortion=distortion, return_matches=True)
            record = dict(origin_xy=origin.tolist(), size=size, dots=len(local),
                          matches=answer.get('Matches'), probability=answer.get('Prob'),
                          distortion_hypothesis=distortion, solve_time_ms=answer.get('T_solve'))
            attempts.append(record)
            print('Point pattern bootstrap:', record, flush=True)
            if answer.get('RA') is None or answer['Matches'] < 8:
                continue
            matched_xy = np.asarray(answer['matched_centroids'])[:, ::-1]-.5+origin
            matched = np.asarray(answer['matched_stars'])
            sky = vectors(matched[:, 0], matched[:, 1])
            focal = size/(2*np.tan(np.deg2rad(answer['FOV'])/2))
            initial = BarghiniCamera.initial(shape, focal, np.eye(3))
            ray = initial.to_sky(matched_xy)
            u, _, vt = np.linalg.svd(ray.T @ sky)
            rotation = vt.T @ np.diag([1., 1., np.linalg.det(vt.T @ u.T)]) @ u.T
            camera = BarghiniCamera.initial(shape, focal, rotation)
            # Small patch cannot constrain every lens term: establish pose and scale first.
            camera, info = fit_camera(camera, matched_xy, sky)
            return camera, dict(method='tetra3_blind_bootstrap_from_new_training_dots',
                attempts=attempts, fit=info, seed_stars=len(sky),
                seed_fov_deg=float(answer['FOV']), metadata_used=False)
    raise RuntimeError('No blind catalogue bootstrap from the measured training dots')


def associate(camera, xy, catalogue, gate_px):
    """Exclusive nearest neighbours, gated in actual detector pixels."""
    ray = camera.to_sky(xy)
    _, nearest = cKDTree(catalogue).query(ray)
    _, reverse = cKDTree(ray).query(catalogue)
    indices = np.arange(len(xy))
    mutual = reverse[nearest] == indices
    ii = indices[mutual]
    jj = nearest[mutual]
    distance = np.linalg.norm(camera.project(catalogue[jj])-xy[ii], axis=1)
    return ii[distance < gate_px], jj[distance < gate_px]


def stats(delta):
    radius = np.linalg.norm(delta, axis=1)
    return dict(count=len(radius), rms_px=float(np.sqrt(np.mean(radius**2))) if len(radius) else None,
                median_px=float(np.median(radius)) if len(radius) else None,
                p90_px=float(np.percentile(radius, 90)) if len(radius) else None)


def select_labels(rows, count=20):
    """Prefer bright, well-matched dots, then maximise spatial coverage."""
    good = [r for r in rows if float(r['residual_px']) < 1.
            and r.get('source_class', 'compact') == 'compact']
    bright = [r for r in good if float(r['magnitude']) <= 4.5]
    candidates = bright if len(bright) >= count else good
    if not candidates or count <= 0:
        return []
    xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in candidates])
    first = min(range(len(candidates)), key=lambda i: float(candidates[i]['magnitude']))
    chosen = [first]
    nearest = np.linalg.norm(xy-xy[first], axis=1)
    while len(chosen) < min(count, len(candidates)):
        nearest[chosen] = -1
        pick = int(np.argmax(nearest))
        chosen.append(pick)
        nearest = np.minimum(nearest, np.linalg.norm(xy-xy[pick], axis=1))
    return [candidates[i] for i in chosen]


def annotate_stars(image_path, records, output, count=40, *, names_cache=None, offline=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rgb = np.asarray(Image.open(image_path).convert('RGB'))
    from point_star_names import plot_label, resolve_names
    selected = [dict(r) for r in select_labels(records, count)]
    names = resolve_names([r['star_id'] for r in selected],
                          cache_path=names_cache, offline=offline)
    for r in selected:
        r.update(display_name=names[r['star_id']]['display_name'],
                 name_source=names[r['star_id']]['name_source'])
    (output/'display_names.json').write_text(json.dumps(names, ensure_ascii=False, indent=2)+'\n')
    fig, ax = plt.subplots(figsize=(13, 12))
    ax.imshow(rgb)
    for r in selected:
        x, y = float(r['x_px']), float(r['y_px'])
        ax.plot(x, y, 'o', ms=8, mfc='none', mec='#ffe66d', mew=1.)
        label = plot_label(r)
        if label is None:
            continue
        right = x < .82*rgb.shape[1]
        ax.annotate(label, (x, y), xytext=(10 if right else -10, -13 if y < 70 else 10),
                    textcoords='offset points', ha='left' if right else 'right',
                    fontsize=9, color='#ffe66d',
                    bbox=dict(boxstyle='round,pad=.2', fc='black', ec='none', alpha=.6),
                    arrowprops=dict(arrowstyle='-', color='#ffe66d', lw=.6))
    ax.set_xlim(-.5, rgb.shape[1]-.5); ax.set_ylim(rgb.shape[0]-.5, -.5)
    ax.set_title(f'Barghini point-star solution — {len(selected)} identified stars')
    ax.axis('off')
    fig.tight_layout(); save_png(fig, output/f'identified_{len(selected)}_stars.png', dpi=160); plt.close(fig)
    (output/'labelled_stars.json').write_text(json.dumps(dict(
        selection='bright compact catalogue matches; residual < 1 pixel; farthest-point spatial coverage',
        stars=selected), ensure_ascii=False, indent=2)+'\n')


def prepare_output(output, *, overwrite=True):
    output = Path(output).expanduser()
    resolved = output.resolve()
    repository = Path(__file__).resolve().parent
    working_directory = Path.cwd().resolve()
    protected = {repository, *repository.parents,
                 working_directory, *working_directory.parents}
    roots = [repository] + [parent for parent in repository.parents if (parent/'.git').exists()]
    preserved = [root/name for root in roots for name in ('examples', 'data', '.git')]
    if any(resolved == path or path in resolved.parents for path in preserved):
        raise ValueError(f'Refusing to overwrite preserved repository assets: {output}')
    if resolved in protected:
        raise ValueError(f'Refusing to use protected directory as output: {output}')
    if output.exists() or output.is_symlink():
        if not overwrite:
            raise FileExistsError(f'Refusing to overwrite output: {output}')
        if output.is_symlink() or output.is_file():
            output.unlink()
        else:
            shutil.rmtree(output)
    output.mkdir(parents=True)
    return output


def run(image_path, output, catalog_path, *, label_count=40, names_cache=None, offline=False,
        overwrite=False, observation_time=None, latitude=None, longitude=None,
        elevation_m=0., pressure_hpa=None, temperature_c=10., relative_humidity=.5,
        extinction_mag_per_airmass=None, epoch_mode='fit', epoch_year=None,
        epoch_limits=(1850., 2036.)):
    if epoch_mode not in ('fit', 'fixed', 'catalog'):
        raise ValueError('Unknown epoch mode')
    if (epoch_mode == 'fixed') != (epoch_year is not None):
        raise ValueError('Supply epoch_year exactly when epoch_mode is fixed')
    if epoch_year is not None and not np.isfinite(epoch_year):
        raise ValueError('Supplied epoch must be finite')
    if len(epoch_limits) != 2 or not np.isfinite(epoch_limits).all() or epoch_limits[0] >= epoch_limits[1]:
        raise ValueError('Epoch limits must be finite and increasing')
    # An existing image cannot be from after this run. The system clock is a
    # causal bound, independent of observing timestamps and site metadata.
    causal_epoch_ceiling = capture_time_ceiling() if epoch_mode == 'fit' else None
    if causal_epoch_ceiling is not None:
        epoch_limits = limit_epoch_range(epoch_limits, causal_epoch_ceiling)
    started = time.monotonic()
    image_path = Path(image_path).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    for source in (image_path, Path(catalog_path).expanduser().resolve(),
                   Path(names_cache).expanduser().resolve() if names_cache else None):
        if source is not None and (source == destination or destination in source.parents):
            raise ValueError(f'Output would remove an input file: {source}')
    output = prepare_output(output, overwrite=overwrite)
    detection = write_products(image_path, output/'dots')
    with (output/'dots/star_candidates.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    xy = np.array([[float(r['x_px']), float(r['y_px'])] for r in rows])
    if len(xy) < 12:
        raise RuntimeError('Too few point sources for catalogue matching')
    # First feasibility experiment: every dot is available for association and fitting.
    train = np.arange(len(xy))
    shape = (detection['height_px'], detection['width_px'])
    camera, seed_audit = bootstrap(xy[train], shape)
    (output/'bootstrap.json').write_text(json.dumps(seed_audit, indent=2)+'\n')
    with Path(catalog_path).open() as handle:
        catalog_rows = list(csv.DictReader(handle))
    sky = vectors([float(r['ra_deg']) for r in catalog_rows],
                  [float(r['dec_deg']) for r in catalog_rows])
    stellar_epoch = None
    if epoch_mode != 'catalog':
        from point_star_epoch import Catalogue, fit_epoch, write_epoch_products
        catalogue = Catalogue.from_rows(catalog_rows)
        sky = catalogue.at_year(epoch_year if epoch_mode == 'fixed' else 2000.)
    mags = np.array([float(r['mag']) for r in catalog_rows])
    centre = (np.array(shape[::-1])-1)/2
    radius = np.linalg.norm(xy[train]-centre, axis=1)
    stages = []
    # Barghini's progressive matching: increase catalogue depth, reduce correlation radius.
    for radial_fraction, mag, gate in ((.30, 5., 12.), (.40, 5.5, 12.),
                                      (.50, 6., 10.), (.65, 6.5, 8.),
                                      (1., 7., 6.), (1., 7.5, 4.), (1., 7.5, 3.)):
        use = train[radius < radial_fraction*min(shape)]
        cat_use = np.flatnonzero(mags <= mag)
        for iteration in range(3):
            ii, jj = associate(camera, xy[use], sky[cat_use], gate)
            if len(ii) < 12:
                stages.append(dict(radius_fraction=radial_fraction, magnitude=mag,
                                   gate_px=gate, matches=len(ii), fitted=False))
                break
            camera, info = fit_camera(camera, xy[use[ii]], sky[cat_use[jj]])
            record = dict(radius_fraction=radial_fraction, magnitude=mag,
                          gate_px=gate, matches=len(ii), fitted=True, **info)
            stages.append(record)
            print('Barghini point fit:', record, flush=True)
    train_i, train_j = associate(camera, xy[train], sky, 3.)
    if len(train_i) < 20:
        raise RuntimeError('Insufficient catalogue associations after Barghini refinement')
    # Refine all current catalogue associations together.
    camera, final_fit = fit_camera(camera, xy[train[train_i]], sky[train_j], max_nfev=600)
    if epoch_mode != 'catalog':
        # Each epoch profile uses a fixed set. All dots remain eligible when
        # reassociating between profiles, including large/saturated sources.
        for association_iteration in range(6):
            camera, final_fit, stellar_epoch = fit_epoch(
                camera, xy[train[train_i]], catalogue.subset(train_j), epoch_limits,
                fixed_year=epoch_year)
            sky = catalogue.at_year(stellar_epoch['applied_epoch_jyear'])
            next_i, next_j = associate(camera, xy[train], sky, 3.)
            if np.array_equal(next_i, train_i) and np.array_equal(next_j, train_j):
                break
            if len(next_i) < 20:
                raise RuntimeError('Insufficient associations after proper-motion propagation')
            train_i, train_j = next_i, next_j
        else:
            raise RuntimeError('Proper-motion association did not converge after six profiles')
        stellar_epoch.update(association_iterations=association_iteration+1,
                             association_converged=True)
        if causal_epoch_ceiling is not None:
            stellar_epoch['causal_epoch_ceiling'] = causal_epoch_ceiling
        write_epoch_products(output, stellar_epoch)
    train_delta = camera.project(sky[train_j])-xy[train[train_i]]
    fit_score = stats(train_delta)
    accepted = final_fit['success'] and camera.is_monotonic()
    result = dict(status='point_star_fit_converged' if accepted else 'point_star_fit_not_converged',
        source=str(image_path), source_sha256=detection['source_sha256'],
        model='Barghini_2019_O_Z_FET', metadata_used=False, trails_used=False,
        catalogue_sha256=hashlib.sha256(Path(catalog_path).read_bytes()).hexdigest(),
        camera=camera.serialise(), stages=stages, final_fit=final_fit,
        fit=fit_score, detection_count=len(xy), withheld_stars=0,
        unmatched_dots=len(xy)-len(train_i),
        limitation='All stars are available for fitting; no stars are withheld. Residuals describe '
          'the fitted associations, selected with a 3-pixel matching gate; they are not independent '
          'validation or a completeness measurement. No date, terrestrial orientation, '
          'proper-motion epoch or atmospheric-refraction solution is claimed.',
        elapsed_seconds=time.monotonic()-started)
    result.update(solver_version=SOLVER_VERSION, epoch_mode=epoch_mode, blind=epoch_mode != 'fixed',
                  coordinate_frame='ICRS')
    if causal_epoch_ceiling is not None:
        result['causal_epoch_ceiling'] = causal_epoch_ceiling
    if stellar_epoch is not None:
        result['stellar_epoch'] = stellar_epoch
        result['coordinate_epoch_jyear'] = stellar_epoch['applied_epoch_jyear']
        result['metadata_used'] = epoch_mode == 'fixed'
        result['limitation'] = (
            'All detected sources are available; no stars are withheld. Residuals describe '
            'fitted associations with a 3-pixel gate, not independent validation. '
            + stellar_epoch['limitation'])
    pairs = [(train[train_i], train_j, 'fitted')]
    matched_records = []
    with (output/'star_coordinates.csv').open('w') as handle:
        writer = csv.writer(handle)
        writer.writerow(['detection_id', 'star_id', 'catalog_ra_deg', 'catalog_dec_deg',
                         'magnitude', 'x_px', 'y_px', 'predicted_x_px', 'predicted_y_px',
                         'residual_px', 'usage', 'source_class', 'saturated'] +
                        (['propagated_ra_deg', 'propagated_dec_deg', 'coordinate_epoch_jyear',
                          'reference_epoch_jyear', 'proper_motion_available',
                          'measured_ra_deg', 'measured_dec_deg'] if stellar_epoch else []))
        for measured, reference, split in pairs:
            prediction = camera.project(sky[reference])
            for i, j, p in zip(measured, reference, prediction):
                r = catalog_rows[j]
                extra = []
                if stellar_epoch is not None:
                    measured_sky = camera.to_sky(xy[i:i+1])[0]
                    extra = [np.rad2deg(np.arctan2(sky[j, 1], sky[j, 0])) % 360,
                             np.rad2deg(np.arctan2(sky[j, 2], np.linalg.norm(sky[j, :2]))),
                             stellar_epoch['applied_epoch_jyear'], r['reference_epoch_jyear'],
                             bool(catalogue.has_motion[j]),
                             np.rad2deg(np.arctan2(measured_sky[1], measured_sky[0])) % 360,
                             np.rad2deg(np.arctan2(measured_sky[2], np.linalg.norm(measured_sky[:2])))]
                writer.writerow([rows[i]['detection_id'], r['star_id'], r['ra_deg'], r['dec_deg'],
                                 r['mag'], *xy[i], *p, np.linalg.norm(p-xy[i]), split,
                                 rows[i]['source_class'], rows[i]['saturated']] + extra)
                matched_records.append(dict(detection_id=int(rows[i]['detection_id']),
                    star_id=r['star_id'], magnitude=float(r['mag']),
                    x_px=float(xy[i, 0]), y_px=float(xy[i, 1]),
                    residual_px=float(np.linalg.norm(p-xy[i])), source_class=rows[i]['source_class']))
    # Every blob survives in an object table, including those without any stellar match.
    world = camera.to_sky(xy)
    ra = np.rad2deg(np.arctan2(world[:, 1], world[:, 0])) % 360
    dec = np.rad2deg(np.arctan2(world[:, 2], np.linalg.norm(world[:, :2], axis=1)))
    identified = {r['detection_id']: r['star_id'] for r in matched_records}
    blobs = []
    for i, row in enumerate(rows):
        if row['source_class'] != 'broad_blob' and row['saturated'] != 'True':
            continue
        blobs.append(dict(**row, fitted_ra_deg=float(ra[i]), fitted_dec_deg=float(dec[i]),
                          catalogue_star_id=identified.get(int(row['detection_id']), ''),
                          classification='unclassified_object'))
    blob_fields = list(rows[0])+['fitted_ra_deg', 'fitted_dec_deg', 'catalogue_star_id', 'classification']
    with (output/'blob_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=blob_fields)
        writer.writeheader(); writer.writerows(blobs)
    result['broad_or_saturated_objects'] = len(blobs)
    result['broad_or_saturated_without_star_match'] = sum(not r['catalogue_star_id'] for r in blobs)
    result['code_sha256'] = {name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
        for name in ['point_star_detection.py', 'point_star_footprint.py',
                     'point_star_barghini.py', 'barghini_model.py',
                     'point_star_names.py', 'point_star_diagnostics.py', 'point_star_report.py',
                     'point_star_epoch.py', 'point_star_zenith.py', 'point_star_science.py',
                     'point_star_time_bounds.py']}
    if observation_time is not None:
        result['observation'] = dict(time_utc=observation_time, latitude_deg=latitude,
            longitude_deg=longitude, elevation_m=elevation_m, pressure_hpa=pressure_hpa,
            temperature_c=temperature_c, relative_humidity=relative_humidity,
            extinction_mag_per_airmass=extinction_mag_per_airmass)
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    annotate_stars(image_path, matched_records, output, label_count,
                   names_cache=names_cache, offline=offline)
    from point_star_diagnostics import write_diagnostics
    write_diagnostics(image_path, xy[train[train_i]], camera.project(sky[train_j]), output,
                      unmatched=xy[np.setdiff1d(train, train[train_i])])
    from point_star_report import write_report
    report = write_report(output, result, observation_time=observation_time,
                          latitude=latitude, longitude=longitude, elevation_m=elevation_m,
                          pressure_hpa=pressure_hpa, temperature_c=temperature_c,
                          relative_humidity=relative_humidity,
                          extinction_mag_per_airmass=extinction_mag_per_airmass)
    result['report_pdf'] = report.name
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status', 'fit', 'unmatched_dots', 'withheld_stars')}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=f'%(prog)s {SOLVER_VERSION}')
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog', type=Path,
                        default=Path(__file__).resolve().parent/'data/stars_tycho2_mag75.csv')
    parser.add_argument('--annotations-from', type=Path,
                        help='Annotate an existing solution without rerunning detection or fitting')
    parser.add_argument('--labels', type=int, default=40,
                        help='Number of spatially distributed star labels (default: 40)')
    parser.add_argument('--names-cache', type=Path, help='Display-only name cache JSON')
    parser.add_argument('--offline', action='store_true', help='Disable SIMBAD name queries')
    parser.add_argument('--no-overwrite', action='store_true',
                        help='Refuse to replace an existing output directory (default)')
    parser.add_argument('--overwrite', action='store_true', help='Explicitly replace the output directory')
    parser.add_argument('--epoch-mode', choices=('fit', 'fixed', 'catalog'), default='fit',
                        help='Fit stellar epoch (default), use supplied year, or replay native catalogue positions')
    parser.add_argument('--epoch-year', type=float, help='Julian year required with --epoch-mode fixed')
    parser.add_argument('--epoch-limits', type=float, nargs=2, default=(1850., 2036.), metavar=('MIN', 'MAX'))
    parser.add_argument('--observation-time',
                        help='UTC observation time for planets/refraction, for example 2026-09-13T22:00:00')
    parser.add_argument('--latitude', type=float, help='Observing-site latitude in degrees')
    parser.add_argument('--longitude', type=float, help='Observing-site longitude in degrees east')
    parser.add_argument('--elevation-m', type=float, default=0., help='Site elevation in metres')
    parser.add_argument('--pressure-hpa', type=float,
                        help='Atmospheric pressure; default estimates it from elevation')
    parser.add_argument('--temperature-c', type=float, default=10.,
                        help='Air temperature for refraction (default: 10 C)')
    parser.add_argument('--relative-humidity', type=float, default=.5,
                        help='Relative humidity from 0 to 1 (default: 0.5)')
    parser.add_argument('--extinction-mag-per-airmass', type=float,
                        help='Assumed extinction coefficient for the report')
    args = parser.parse_args()
    if args.overwrite and args.no_overwrite:
        parser.error('--overwrite conflicts with --no-overwrite')
    if (args.epoch_mode == 'fixed') != (args.epoch_year is not None):
        parser.error('--epoch-year is required exactly when --epoch-mode fixed is used')
    if args.labels < 1:
        parser.error('--labels must be positive')
    if (args.latitude is None) != (args.longitude is None):
        parser.error('--latitude and --longitude must be supplied together')
    if args.latitude is not None and not -90 <= args.latitude <= 90:
        parser.error('--latitude must be between -90 and 90 degrees')
    if args.longitude is not None and not -180 <= args.longitude <= 180:
        parser.error('--longitude must be between -180 and 180 degrees')
    if args.pressure_hpa is not None and args.pressure_hpa <= 0:
        parser.error('--pressure-hpa must be positive')
    if not 0 <= args.relative_humidity <= 1:
        parser.error('--relative-humidity must be between 0 and 1')
    if args.extinction_mag_per_airmass is not None and args.extinction_mag_per_airmass < 0:
        parser.error('--extinction-mag-per-airmass cannot be negative')
    if args.annotations_from:
        result = json.loads((args.annotations_from/'result.json').read_text())
        source = args.image.expanduser().resolve()
        if hashlib.sha256(source.read_bytes()).hexdigest() != result['source_sha256']:
            parser.error('The image does not match this astrometric solution')
        with (args.annotations_from/'star_coordinates.csv').open() as handle:
            records = list(csv.DictReader(handle))
        output = prepare_output(args.output, overwrite=args.overwrite)
        annotate_stars(source, records, output, args.labels,
                       names_cache=args.names_cache, offline=args.offline)
        return
    result = run(args.image, args.output, args.catalog, label_count=args.labels,
                 names_cache=args.names_cache, offline=args.offline,
                 overwrite=args.overwrite, observation_time=args.observation_time,
                 latitude=args.latitude, longitude=args.longitude, elevation_m=args.elevation_m,
                 pressure_hpa=args.pressure_hpa, temperature_c=args.temperature_c,
                 relative_humidity=args.relative_humidity,
                 extinction_mag_per_airmass=args.extinction_mag_per_airmass,
                 epoch_mode=args.epoch_mode, epoch_year=args.epoch_year, epoch_limits=args.epoch_limits)
    raise SystemExit(0 if result['status'] == 'point_star_fit_converged' else 1)


if __name__ == '__main__':
    main()
