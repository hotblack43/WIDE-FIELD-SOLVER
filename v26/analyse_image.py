#!/usr/bin/env python3
"""Solve one all-sky image and write astrometry, atmosphere, photometry and epoch products."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

from point_star_barghini import SOLVER_VERSION, run
from point_star_report import write_report
from point_star_fits import write_fits
from point_star_science import analyse_existing, compare_metadata


ROOT = Path(__file__).resolve().parent


def fits_export_messages(output, exported):
    """Describe the distinct machine-readable and annotated FITS products."""
    output = Path(output)
    if exported['status'] == 'exported':
        return [f"FITS for solve-field: {output / exported['file']}",
                f"FITS with overlays: {output / exported['annotated_file']}"]
    return [f"FITS export unavailable: {exported['reason']}"]


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', action='version', version=f'%(prog)s {SOLVER_VERSION}')
    p.add_argument('image', type=Path, help='JPEG, PNG, TIFF or FITS (including .fits.bz2) all-sky image')
    p.add_argument('--output', type=Path, required=True, help='New output directory (protected by default)')
    p.add_argument('--overwrite', action='store_true', help='Explicitly replace an existing output directory')
    p.add_argument('--database', type=Path,
                   help='Append all available results to SQLite, including reruns and failed analyses')
    p.add_argument('--epoch-mode', choices=('fit', 'fixed', 'catalog'), default='fit')
    p.add_argument('--epoch-year', type=float, help='Julian year required for fixed epoch mode')
    p.add_argument('--epoch-limits', type=float, nargs=2, default=(1850., 2036.), help='Requested Julian-year range; blind upper bound is capped at the current run time')
    p.add_argument('--catalog', type=Path, default=ROOT/'data/stars_tycho2_mag75.csv')
    p.add_argument('--labels', type=int, default=40)
    p.add_argument('--names-cache', type=Path)
    p.add_argument('--offline', action='store_true', help='Disable display-name network queries')
    p.add_argument('--fits-hdu', help='FITS image HDU name or zero-based index when selection is ambiguous')
    p.add_argument('--channel-order', choices=('RGB', 'RGGB', 'RG1G2B'),
                   help='Explicit order for an unlabelled three/four-plane stack')
    p.add_argument('--saturation-level',
                   help='One threshold for all planes or channel mapping such as R=4095,G1=4095,G2=4095,B=4095')
    p.add_argument('--visible-sky-mask-manifest', type=Path,
                   help='Approved installation-specific visible-sky mask manifest')
    p.add_argument('--camera-installation-id',
                   help='Camera installation identity required by the visible-sky mask')
    p.add_argument('--calibration-registry', type=Path,
                   help='User calibration registry layer for checksum assignment resolution')
    p.add_argument('--bundled-calibration-registry', type=Path, action='append', default=[],
                   help='Read-only bundled calibration registry layer; repeat as needed')
    p.add_argument('--installation-assignments', type=Path,
                   help='Append-only source-checksum installation assignments')
    p.add_argument('--allow-unconfigured-visible-sky', action='store_true',
                   help='In automatic mode only, allow a source with no assignment to run unmasked')
    p.add_argument('--blind-planets', action='store_true',
                   help='Ignore time metadata and force the full blind planetary epoch search')
    p.add_argument('--compare-metadata', action='store_true',
                   help='Compare metadata with completed stellar, zenith and planetary results')
    p.add_argument('--observation-time',
                   help='Explicit UTC time for separate validation; never bounds the v11 global planet fit')
    p.add_argument('--latitude', type=float)
    p.add_argument('--longitude', type=float)
    p.add_argument('--elevation-m', type=float, default=0.)
    return p


def validate_arguments(p, args):
    """Validate mode combinations without creating an output directory."""
    if (args.epoch_mode == 'fixed') != (args.epoch_year is not None):
        raise ValueError('--epoch-year is required exactly when --epoch-mode fixed is used')
    if (args.latitude is None) != (args.longitude is None):
        raise ValueError('--latitude and --longitude must be supplied together')
    explicit_any = (
        args.visible_sky_mask_manifest is not None
        or args.camera_installation_id is not None
    )
    explicit_complete = (
        args.visible_sky_mask_manifest is not None
        and args.camera_installation_id is not None
    )
    registries = tuple(args.bundled_calibration_registry) + (
        ((args.calibration_registry,) if args.calibration_registry is not None else ())
    )
    automatic_any = bool(registries) or args.installation_assignments is not None
    automatic_complete = bool(registries) and args.installation_assignments is not None
    if explicit_any and not explicit_complete:
        raise ValueError(
            '--visible-sky-mask-manifest and --camera-installation-id must be supplied together'
        )
    if explicit_any and automatic_any:
        raise ValueError('explicit and automatic visible-sky calibration modes cannot be combined')
    if automatic_any and not automatic_complete:
        raise ValueError(
            'automatic visible-sky calibration requires a registry layer and '
            '--installation-assignments'
        )
    if args.allow_unconfigured_visible_sky and not automatic_complete:
        raise ValueError(
            '--allow-unconfigured-visible-sky requires complete automatic calibration options'
        )
    if args.database and (args.database.resolve() == args.output.resolve()
                         or args.output.resolve() in args.database.resolve().parents):
        raise ValueError('--database must be outside --output')


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_visible_sky_configuration(args):
    """Resolve automatic checksum assignment into the existing explicit pair."""
    registries = tuple(args.bundled_calibration_registry) + (
        ((args.calibration_registry,) if args.calibration_registry is not None else ())
    )
    if not registries:
        return {
            'mode': 'explicit' if args.visible_sky_mask_manifest else 'unmanaged',
            'status': 'explicit' if args.visible_sky_mask_manifest else 'not_configured',
        }
    source = args.image.expanduser().resolve(strict=True)
    source_sha256 = _file_sha256(source)
    registry_paths = tuple(Path(path).expanduser().resolve(strict=True)
                           for path in registries)
    assignments_path = args.installation_assignments.expanduser().resolve()
    from visible_sky_registry import (
        assignment_for_source,
        load_registry,
        resolve_source_calibration,
    )
    # Configuration corruption is fatal even when this particular checksum is
    # explicitly permitted to continue without a configured mask.
    load_registry(registry_paths)
    assignment = assignment_for_source(assignments_path, source_sha256)
    registry_layers = [
        {'path': str(path), 'sha256': _file_sha256(path)}
        for path in registry_paths
    ]
    if assignment is None:
        if args.allow_unconfigured_visible_sky:
            return {
                'mode': 'automatic',
                'status': 'not_configured',
                'source_sha256': source_sha256,
                'assignment_path': str(assignments_path),
                'registry_layers': registry_layers,
                'reason': 'source_checksum_has_no_installation_assignment',
            }
        raise ValueError(
            f'source checksum has no installation assignment: {source_sha256}'
        )
    calibration = resolve_source_calibration(
        registry_paths, assignments_path, source_sha256
    )
    manifest_path = Path(str(calibration['manifest_path'])).resolve(strict=True)
    args.visible_sky_mask_manifest = manifest_path
    args.camera_installation_id = str(calibration['installation_id'])
    return {
        'mode': 'automatic',
        'status': 'resolved',
        'source_sha256': source_sha256,
        'source_id': assignment.get('source_id'),
        'camera_id': assignment.get('camera_id'),
        'installation_id': calibration['installation_id'],
        'mask_id': calibration['mask_id'],
        'mask_sha256': calibration['mask_sha256'],
        'manifest_path': str(manifest_path),
        'manifest_sha256': calibration['manifest_sha256'],
        'assignment_path': str(assignments_path),
        'assignment_registry_sha256': _file_sha256(assignments_path),
        'assignment': assignment,
        'registry_layers': registry_layers,
    }


def main():
    p = parser()
    args = p.parse_args()
    try:
        validate_arguments(p, args)
        args.visible_sky_resolution = resolve_visible_sky_configuration(args)
    except ValueError as exc:
        p.error(str(exc))
    exit_code, error = 0, None
    try:
        analyse(args)
    except BaseException as exc:
        exit_code, error = 1, f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if args.database:
            from point_star_database import append_run
            run_id = append_run(args.database, args.output, args.image,
                                exit_code=exit_code, error=error)
            print(f'Database: {args.database.resolve()} (run {run_id})', flush=True)
    # Run only on success, after the recording transaction. Storage housekeeping
    # must never turn an adopted fit into an apparent scientific failure.
    from point_star_storage import archive_intermediates
    try:
        storage = archive_intermediates(args.output)
        if storage['archived']:
            print(f"Intermediate evidence: {args.output / 'intermediate_products.zip'} "
                  f"({storage['before_bytes']} → {storage['after_bytes']} bytes)", flush=True)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f'Warning: intermediate archiving incomplete; evidence retained: {exc}', flush=True)


def analyse(args):
    """Finish scientific outputs before the caller records them in the database."""
    result = run(args.image, args.output, args.catalog, label_count=args.labels,
                 names_cache=args.names_cache, offline=args.offline,
                 observation_time=args.observation_time, latitude=args.latitude,
                 longitude=args.longitude, elevation_m=args.elevation_m,
                 overwrite=args.overwrite, epoch_mode=args.epoch_mode,
                 epoch_year=args.epoch_year, epoch_limits=args.epoch_limits,
                 fits_hdu=args.fits_hdu, channel_order=args.channel_order,
                 saturation_level=args.saturation_level,
                 visible_sky_mask_manifest=args.visible_sky_mask_manifest,
                 camera_installation_id=args.camera_installation_id)
    if hasattr(args, 'visible_sky_resolution'):
        result['visible_sky_calibration_resolution'] = args.visible_sky_resolution
    science = analyse_existing(args.image.resolve(), args.output, result, args.catalog,
                               force_blind_planets=args.blind_planets)
    from point_star_joint_epoch import refine_joint_epoch
    refine_joint_epoch(args.image.resolve(), args.output, result, science, args.catalog)
    result['fits_export'] = write_fits(args.image.resolve(), args.output, result, science)
    if args.compare_metadata:
        comparison = compare_metadata(result, science)
        (Path(args.output)/'metadata_comparison.json').write_text(__import__('json').dumps(comparison, indent=2)+'\n')
        result['metadata_revealed'] = True
    report = write_report(args.output, result, science=science)
    result['report_pdf'] = report.name
    (Path(args.output)/'result.json').write_text(__import__('json').dumps(result, indent=2)+'\n')
    planets = science['planets']
    print(f"Report: {report}")
    exported = result['fits_export']
    for message in fits_export_messages(args.output, exported):
        print(message)
    print(f"Stellar epoch: {science['stellar_epoch']['status']}")
    print(f"Refraction: {science['refraction']['status']}")
    print(f"Extinction: {science['photometry']['extinction_status']}")
    print(f"Planet epoch: {planets.get('derived_epoch_utc') or planets.get('best_candidate_epoch_tdb') or planets['status']} "
          f"[{planets.get('confidence', 'none')}]")


if __name__ == '__main__':
    main()
