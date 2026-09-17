#!/usr/bin/env python3
"""Solve one all-sky image and write astrometry, atmosphere, photometry and epoch products."""
from __future__ import annotations

import argparse
from pathlib import Path

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
    p.add_argument('image', type=Path, help='JPEG, PNG, TIFF or FITS all-sky image')
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
    p.add_argument('--compare-metadata', action='store_true',
                   help='Reveal metadata only after all blind fits, for a separate comparison')
    p.add_argument('--observation-time', help='UTC metadata for optional post-fit comparison; never used to fit the blind epoch')
    p.add_argument('--latitude', type=float)
    p.add_argument('--longitude', type=float)
    p.add_argument('--elevation-m', type=float, default=0.)
    return p


def main():
    p = parser()
    args = p.parse_args()
    if (args.epoch_mode == 'fixed') != (args.epoch_year is not None):
        p.error('--epoch-year is required exactly when --epoch-mode fixed is used')
    if (args.latitude is None) != (args.longitude is None):
        p.error('--latitude and --longitude must be supplied together')
    if args.database and (args.database.resolve() == args.output.resolve()
                         or args.output.resolve() in args.database.resolve().parents):
        p.error('--database must be outside --output')
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


def analyse(args):
    """Finish scientific outputs before the caller records them in the database."""
    result = run(args.image, args.output, args.catalog, label_count=args.labels,
                 names_cache=args.names_cache, offline=args.offline,
                 observation_time=args.observation_time, latitude=args.latitude,
                 longitude=args.longitude, elevation_m=args.elevation_m,
                 overwrite=args.overwrite, epoch_mode=args.epoch_mode,
                 epoch_year=args.epoch_year, epoch_limits=args.epoch_limits,
                 fits_hdu=args.fits_hdu, channel_order=args.channel_order,
                 saturation_level=args.saturation_level)
    science = analyse_existing(args.image.resolve(), args.output, result, args.catalog)
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
