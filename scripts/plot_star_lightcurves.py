#!/usr/bin/env python3
"""Read-only MMTO light curves from saved solver photometry and archive UTC times."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import random
import re
import socket
import sqlite3
import statistics
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def normalized_name(value):
    # Match saved aliases exactly, allowing whitespace and catalogue zero padding.
    value = re.sub(r'\s+', '', str(value).casefold()).removeprefix('*')
    return re.sub(r'\d+', lambda m: str(int(m.group())), value)


def utc_time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError(f'Observation time must include a timezone: {value}')
    return parsed.astimezone(timezone.utc)


def read_times(manifest):
    times = {}
    with Path(manifest).open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            url = urlparse(row.get('source_url', ''))
            if url.hostname != 'skycam.mmto.arizona.edu' or not url.path.startswith('/skycam/archive/'):
                continue
            digest, value = row.get('sha256'), row.get('utc_mid')
            if not digest or not value:
                continue
            timestamp = utc_time(value).isoformat().replace('+00:00', 'Z')
            if digest in times and times[digest] != timestamp:
                raise ValueError(f'Conflicting manifest UTC times for image hash {digest}')
            times[digest] = timestamp
    if not times:
        raise ValueError('Manifest contains no MMTO archive image hashes with UTC mid-exposure times')
    return times


def load_measurements(database, manifest, channel='G'):
    """Snapshot successful MMTO runs; latest run per image/catalogue, then quality cuts.

    Archive hash membership is mandatory: no filename clock guessing and no other
    cameras. Recording time chooses reruns only; it never becomes observation time.
    The read transaction ends before plotting so the active solver can keep writing.
    """
    times = read_times(manifest)
    audit = Counter()
    rows = []
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',
                                uri=True, timeout=10)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        runs = db.execute('''SELECT run_id,recorded_at_utc,source_path,source_sha256,
                                   catalogue_sha256,exit_code
                            FROM runs ORDER BY recorded_at_utc,run_id''').fetchall()
        latest = {}
        for run in runs:
            audit['database_runs'] += 1
            if run[5] != 0:
                audit['failed_runs_omitted'] += 1
                continue
            if run[3] not in times:
                audit['runs_without_manifest_time'] += 1
                continue
            key = (run[3], run[4])
            if key in latest:
                audit['duplicate_runs_omitted'] += 1
            latest[key] = run
        audit['selected_runs'] = len(latest)
        for run in latest.values():
            run_id, _, source_path, digest, catalogue, _ = run
            saved = db.execute("SELECT content FROM products WHERE run_id=? AND product='display_names.json'",
                               (run_id,)).fetchone()
            names = json.loads(saved[0]) if saved else {}
            seen = set()
            query = db.execute('''SELECT star_id,detection_id,values_json FROM measurements
                                  WHERE run_id=? AND product='stellar_photometry.csv'
                                  ORDER BY row_number''', (run_id,))
            for star_id, detection_id, payload in query:
                audit['input_photometry_rows'] += 1
                v = json.loads(payload)
                if not star_id:
                    audit['quality_rows_omitted'] += 1
                    continue
                if star_id in seen:
                    raise ValueError(f'Multiple photometry rows for {star_id} in run {run_id}')
                seen.add(star_id)
                seconds = finite(v.get('exposure_seconds'))
                rate = finite(v.get(channel+'_count_rate_adu_per_s'))
                flux = finite(v.get(channel+'_flux'))
                saturated = str(v.get(channel+'_saturated', v.get('saturated', ''))).lower()
                known = str(v.get('saturation_known', '')).lower() == 'true'
                if (seconds is None or seconds <= 0 or not known or saturated != 'false'
                        or v.get(channel+'_measurement_method', 'aperture') != 'aperture'):
                    audit['quality_rows_omitted'] += 1
                    continue
                if rate is None and flux is not None:
                    rate = flux/seconds
                if rate is None or rate <= 0:
                    audit['quality_rows_omitted'] += 1
                    continue
                details = names.get(star_id, {})
                aliases = [star_id, details.get('display_name', ''), details.get('main_id', '')]
                aliases += str(details.get('aliases', '')).split('|')
                rows.append(dict(run_id=run_id, source_path=source_path, source_sha256=digest,
                                 catalogue_sha256=catalogue or '', star_id=star_id,
                                 detection_id=detection_id, display_name=details.get('display_name', ''),
                                 aliases=[name for name in aliases if name], utc_mid=times[digest],
                                 channel=channel, exposure_seconds=seconds, count_rate_adu_per_s=rate,
                                 machine_magnitude=-2.5*math.log10(rate),
                                 catalogue_magnitude=finite(v.get('catalogue_magnitude')),
                                 altitude_deg=finite(v.get('altitude_deg')),
                                 airmass=finite(v.get('airmass'))))
        db.rollback()
    audit['usable_measurements'] = len(rows)
    return sorted(rows, key=lambda r: (utc_time(r['utc_mid']),r['star_id'])), dict(audit)


def select_stars(rows, *, count=4, min_points=10, min_mag=2.5, max_mag=6.0,
                 coverage=0.75, seed=42, stars=()):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['catalogue_sha256'], row['star_id'])].append(row)
    if stars:
        selected = []
        for name in stars:
            target = normalized_name(name)
            matches = [(key, group) for key, group in grouped.items()
                       if any(target == normalized_name(alias) for row in group for alias in row['aliases'])]
            if not matches:
                raise ValueError(f'Star {name!r} not found among usable MMTO measurements/saved aliases')
            if len({key[1] for key, _ in matches}) > 1:
                raise ValueError(f'Ambiguous saved alias {name!r}; use an exact catalogue ID')
            for match in sorted(matches):
                if match[0] not in [key for key, _ in selected]:
                    selected.append(match)
        return selected
    candidates = []
    for key, group in sorted(grouped.items()):
        mags = [r['catalogue_magnitude'] for r in group if r['catalogue_magnitude'] is not None]
        if mags and min_mag <= statistics.median(mags) <= max_mag:
            candidates.append((key, group))
    required = max(min_points, math.ceil(coverage*max((len(g) for _,g in candidates), default=0)))
    pool = [(key,g) for key,g in candidates if len(g) >= required]
    return random.Random(seed).sample(pool, min(count,len(pool)))


def default_database():
    destination = os.environ.get('WFS_RESULTS_DIR')
    if not destination:
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))
        config = config/'wide-field-solver'/('results-dir.'+socket.gethostname())
        if config.is_file():
            destination = config.read_text().splitlines()[0]
    return Path(destination or ROOT/'results')/'stars.sqlite'


def fit_polynomial_trend(seconds, magnitudes, max_degree=6):
    """Unweighted OLS, degree chosen by minimum leave-one-out prediction MSE.

    Chebyshev basis on [-1,1] avoids powers of large UTC timestamps. PRESS
    residuals e/(1-h) equal explicit leave-one-out refits for this linear model.
    Keep >=2 residual degrees of freedom where the sample size permits it.
    """
    import numpy as np

    t, y = np.asarray(seconds,dtype=float), np.asarray(magnitudes,dtype=float)
    if (t.ndim != 1 or y.shape != t.shape or not len(t) or max_degree < 0
            or not np.all(np.isfinite(t)) or not np.all(np.isfinite(y))):
        raise ValueError('Polynomial fitting requires finite paired times/magnitudes and nonnegative max-degree')
    centre = float((t.min()+t.max())/2)
    scale = float((t.max()-t.min())/2) or 1.0
    x = (t-centre)/scale
    limit = min(max_degree,max(0,len(t)-3),len(np.unique(t))-1)
    candidates = []
    for degree in range(limit+1):
        design = np.polynomial.chebyshev.chebvander(x,degree)
        coefficients,_,rank,_ = np.linalg.lstsq(design,y,rcond=None)
        if rank != degree+1:
            continue
        residuals = y-design@coefficients
        q,_ = np.linalg.qr(design,mode='reduced')
        remaining = 1-np.sum(q*q,axis=1)
        if len(t) == 1:
            cv_mse = None
        elif np.any(remaining < 1e-8):
            continue
        else:
            cv_mse = float(np.mean((residuals/remaining)**2))
            if not np.isfinite(cv_mse):
                continue
        candidates.append(dict(degree=degree,cv_mse_mag2=cv_mse,
                               coefficients=coefficients,residuals=residuals))
    if not candidates:
        raise ValueError('No numerically stable polynomial candidate')
    if len(t) == 1:
        best = candidates[0]
    else:
        lowest = min(row['cv_mse_mag2'] for row in candidates)
        # Prefer the lower degree for numerical ties, including exact polynomials.
        best = next(row for row in candidates if row['cv_mse_mag2'] <= lowest+max(1e-12,lowest*1e-9))
    residuals = best['residuals']
    dof = len(t)-best['degree']-1
    return dict(degree=best['degree'],max_degree_requested=max_degree,
                selection_method='minimum leave-one-out MSE; lower degree for numerical ties',
                basis='Chebyshev; x=(seconds-time_centre_seconds)/time_scale_seconds',
                time_centre_seconds=centre,time_scale_seconds=scale,
                coefficients=best['coefficients'].tolist(),
                fitted_magnitudes=(y-residuals).tolist(),residuals=residuals.tolist(),
                residual_sd_mag=float(np.std(residuals,ddof=1)) if len(t)>1 else None,
                residual_standard_error_mag=float(np.sqrt(np.sum(residuals**2)/dof)) if dof>0 else None,
                residual_degrees_of_freedom=dof,
                cv_rmse_mag=math.sqrt(best['cv_mse_mag2']) if best['cv_mse_mag2'] is not None else None,
                candidate_scores=[dict(degree=r['degree'],cv_mse_mag2=r['cv_mse_mag2']) for r in candidates])


def apply_cached_names(rows, cache_path):
    """Attach display aliases only; catalogue IDs and all measurements stay fixed."""
    if not cache_path.is_file():
        return
    cached = json.loads(cache_path.read_text())
    for row in rows:
        record = cached.get(row['star_id'])
        if not record:
            continue
        row['display_name'] = record.get('display_name') or row['display_name']
        row['aliases'] = list(dict.fromkeys(row['aliases'] + [row['display_name']]
                                           + record.get('aliases','').split('|')))


def resolve_plot_names(selected, cache_path, offline=False):
    """Reuse the repository's SIMBAD alias resolver; never modify solver data."""
    import importlib.util
    import tempfile

    spec = importlib.util.spec_from_file_location('lightcurve_names',ROOT/'v8a/point_star_names.py')
    names_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(names_module)
    cached = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    answer = {}
    for (_,star_id), group in selected:
        record = cached.get(star_id,{})
        saved_aliases = '|'.join(dict.fromkeys(alias for row in group for alias in row['aliases']))
        alias = names_module.choose_display_name(saved_aliases,star_id)
        friendly = next((r['display_name'] for r in group if r['display_name']
                         and not r['display_name'].startswith('Gaia DR3 ')),None)
        if (alias != star_id or friendly) and not (record.get('display_name') and record['display_name'] != star_id):
            record = dict(display_name=alias if alias != star_id else friendly,
                          name_source='saved database aliases',aliases=saved_aliases)
        if record.get('display_name') and record['display_name'] != star_id:
            answer[star_id] = record
    missing = [key[1] for key,_ in selected if key[1] not in answer]
    if missing:
        answer.update(names_module.resolve_names(missing,cache_path=cache_path if cache_path.is_file() else None,
                                                offline=offline))
    cached.update({sid:record for sid,record in answer.items() if record['display_name'] != sid})
    cache_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=cache_path.parent,delete=False,encoding='utf-8') as f:
        json.dump(cached,f,indent=2)
        f.write('\n')
        tmp_name=f.name
    os.replace(tmp_name,cache_path)
    for star_id,record in answer.items():
        if record['display_name'] == star_id:
            print(f'No ordinary alias resolved for {star_id}; retaining its catalogue identifier.')
    return answer


def scatter_statistics(groups, max_degree=6):
    """One residual-SD measurement per qualifying star/catalogue series."""
    points = []
    for (catalogue,star_id), group in groups:
        mags = [r['catalogue_magnitude'] for r in group if r['catalogue_magnitude'] is not None]
        if not mags or len(group)<2:
            continue
        times = [utc_time(r['utc_mid']) for r in group]
        fit = fit_polynomial_trend([(t-times[0]).total_seconds() for t in times],
                                   [r['machine_magnitude'] for r in group],max_degree=max_degree)
        points.append(dict(star_id=star_id,catalogue_sha256=catalogue,
                           display_name=next((r['display_name'] for r in group if r['display_name']),''),
                           catalogue_magnitude=statistics.median(mags),channel=group[0]['channel'],
                           measurements=len(group),polynomial_degree=fit['degree'],
                           residual_sd_mag=fit['residual_sd_mag'],
                           residual_standard_error_mag=fit['residual_standard_error_mag'],
                           cv_rmse_mag=fit['cv_rmse_mag'],first_utc=min(times).isoformat().replace('+00:00','Z'),
                           last_utc=max(times).isoformat().replace('+00:00','Z')))
    return sorted(points,key=lambda p:(p['catalogue_magnitude'],p['catalogue_sha256'],p['star_id']))


def write_scatter_plot(groups, output, args, lightcurve_summary):
    import matplotlib.pyplot as plt

    points = scatter_statistics(groups,args.max_degree)
    fields = ['star_id','catalogue_sha256','display_name','catalogue_magnitude','channel',
              'measurements','polynomial_degree','residual_sd_mag','residual_standard_error_mag',
              'cv_rmse_mag','first_utc','last_utc']
    selected = {(s['catalogue_sha256'],s['star_id']):s for s in lightcurve_summary}
    for point in points:
        chosen = selected.get((point['catalogue_sha256'],point['star_id']))
        if chosen:
            point['display_name'] = chosen['display_name']
    with (output/'sd_vs_magnitude.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(points)
    fig,ax=plt.subplots(figsize=(9,6))
    ax.scatter([p['catalogue_magnitude'] for p in points],[p['residual_sd_mag'] for p in points],
               s=23,alpha=.65,color='#356e9b',label=f'Qualifying MMTO stars (n={len(points)})')
    highlighted = False
    for point in points:
        if (point['catalogue_sha256'],point['star_id']) not in selected:
            continue
        x,y=point['catalogue_magnitude'],point['residual_sd_mag']
        ax.scatter([x],[y],s=75,facecolors='none',edgecolors='#c45c16',linewidths=1.5,
                   label='Light-curve panels' if not highlighted else None,zorder=4)
        highlighted=True
        name=point['display_name']
        if name and not name.startswith('Gaia DR3 '):
            ax.annotate(name,(x,y),xytext=(5,6),textcoords='offset points',fontsize=9)
    if not points:
        ax.text(.5,.5,'No stars meet the ensemble selection cuts',transform=ax.transAxes,ha='center')
    ax.set_xlabel('Catalogue magnitude')
    ax.set_ylabel(f'{args.channel} residual SD (mag)')
    ax.set_ylim(bottom=0)
    ax.set_title('MMTO residual scatter after polynomial detrending')
    ax.grid(alpha=.22)
    ax.legend(fontsize=9)
    fig.text(.5,.015,f'LOOCV degree selection (0–{args.max_degree}); sample residual SD (N−1). '
             f'Catalogue mag {args.min_mag:g}–{args.max_mag:g}; '
             f'N ≥ {max(2,args.min_points)}; coverage ≥ {args.coverage:.0%}.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.04,1,1))
    fig.savefig(output/'sd_vs_magnitude.png',dpi=160)
    fig.savefig(output/'sd_vs_magnitude.pdf')
    plt.close(fig)
    return len(points)


def update_latest(output):
    """Update one relative shortcut only after a complete default output run."""
    import uuid

    latest=output.parent/'latest'
    if latest.exists() and not latest.is_symlink():
        print(f'Latest shortcut not updated: {latest} is an existing non-symlink path.')
        return None
    temporary=output.parent/('.latest-'+uuid.uuid4().hex)
    try:
        temporary.symlink_to(output.name,target_is_directory=True)
        os.replace(temporary,latest)
    finally:
        if temporary.is_symlink():
            temporary.unlink()
    return latest


def write_outputs(selected, output, audit, args, scatter_groups=None):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    names = resolve_plot_names(selected,args.database.parent/'lightcurves/display_names.json',
                               offline=args.offline_names)
    output.mkdir(parents=True, exist_ok=False)
    fig, axes = plt.subplots(len(selected),1,figsize=(12,2.6*len(selected)+1),
                             sharex=True,squeeze=False)
    summary, flat, residual_rows = [], [], []
    colours = {'R':'#bc4040','G':'#23834c','B':'#386bc1','L':'#333333'}
    for panel, (ax, (key, group)) in enumerate(zip(axes[:,0],selected),1):
        times = [utc_time(row['utc_mid']) for row in group]
        seconds = [(t-times[0]).total_seconds() for t in times]
        mags = [row['machine_magnitude'] for row in group]
        fit = fit_polynomial_trend(seconds,mags,max_degree=args.max_degree)
        name = names[key[1]]['display_name']
        ax.scatter(times,mags,s=19,color=colours.get(args.channel,'#23834c'),zorder=3)
        grid = np.linspace(min(seconds),max(seconds),400)
        fitted_grid = np.polynomial.chebyshev.chebval(
            (grid-fit['time_centre_seconds'])/fit['time_scale_seconds'],fit['coefficients'])
        ax.plot([times[0]+timedelta(seconds=float(t)) for t in grid],fitted_grid,
                color='#c45c16',lw=1.7,label=f"Polynomial degree {fit['degree']} (LOOCV)")
        ax.invert_yaxis()
        ax.grid(alpha=0.22)
        cat_mags = [r['catalogue_magnitude'] for r in group if r['catalogue_magnitude'] is not None]
        cat_mag = statistics.median(cat_mags) if cat_mags else None
        title = name if not name.startswith('Gaia DR3 ') else f'Star {panel} (name unavailable)'
        if cat_mag is not None:
            title += f'   |   catalogue mag {cat_mag:.2f}'
        sd = fit['residual_sd_mag']
        title += f'   |   residual SD {sd:.3f} mag' if sd is not None else '   |   residual SD unavailable'
        title += f'   |   n = {len(group)}'
        if len({k[0] for k,_ in selected}) > 1:
            title += f'   |   catalogue {key[0][:8]}'
        ax.set_title(title,loc='left',fontsize=10)
        ax.set_ylabel(f'{args.channel} machine mag')
        ax.legend(loc='best',fontsize=8)
        for row,model,residual in zip(group,fit['fitted_magnitudes'],fit['residuals']):
            exported = dict(row,aliases='|'.join(row['aliases']),display_name=name,
                            polynomial_degree=fit['degree'],fitted_magnitude=model,residual_mag=residual)
            flat.append(exported)
            residual_rows.append({field:exported[field] for field in (
                'star_id','display_name','catalogue_sha256','utc_mid','channel','machine_magnitude',
                'fitted_magnitude','residual_mag','polynomial_degree','run_id','source_sha256')})
        fit_record = {k:v for k,v in fit.items() if k not in ('fitted_magnitudes','residuals')}
        fit_record['time_origin_utc'] = group[0]['utc_mid']
        summary.append(dict(star_id=key[1],display_name=name,name_provenance=names[key[1]],
                            catalogue_sha256=key[0],catalogue_magnitude=cat_mag,measurements=len(group),
                            first_utc=group[0]['utc_mid'],last_utc=group[-1]['utc_mid'],polynomial_fit=fit_record))
    for filename,records in [('measurements.csv',flat),('residuals.csv',residual_rows)]:
        with (output/filename).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    locator = mdates.AutoDateLocator(tz=timezone.utc)
    axes[-1,0].xaxis.set_major_locator(locator)
    axes[-1,0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator,tz=timezone.utc))
    axes[-1,0].set_xlabel('Observation midpoint (UTC; MMTO archive manifest)')
    fig.suptitle('MMTO instrumental photometry',fontsize=15)
    fig.text(0.5,0.01,'OLS polynomial; degree selected by leave-one-out CV. '
             'Residual SD: N−1; no clipping.',
             ha='center',fontsize=9)
    fig.tight_layout(rect=(0,0.055,1,0.965))
    fig.savefig(output/'lightcurves.png',dpi=160)
    fig.savefig(output/'lightcurves.pdf')
    plt.close(fig)
    scatter_count=write_scatter_plot(scatter_groups if scatter_groups is not None else selected,
                                     output,args,summary)
    record = dict(database=str(args.database),manifest=str(args.manifest),channel=args.channel,
                  time_basis='UTC exposure midpoint from hash-matched MMTO archive manifest',
                  magnitude_definition='-2.5*log10(unsaturated aperture ADU/s); zero point 0',
                  residual_definition='observed machine magnitude minus fitted polynomial',
                  residual_sd_definition='sample SD of residuals, ddof=1; not an independent precision estimate',
                  selection=dict(min_mag=args.min_mag,max_mag=args.max_mag,min_points=args.min_points,
                                 coverage=args.coverage,seed=args.seed,requested_stars=args.star),
                  audit=audit,stars=summary,
                  sd_vs_magnitude=dict(star_count=scatter_count,table='sd_vs_magnitude.csv',
                                       population='all qualifying MMTO series; independent of random panel selection'))
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',type=Path,default=None)
    p.add_argument('--manifest',type=Path,help='MMTO downloader manifest with source_url, sha256 and utc_mid')
    p.add_argument('--output',type=Path,help='New output directory (default: beside database/lightcurves/TIMESTAMP)')
    p.add_argument('--star',action='append',default=[],help='Exact saved name, alias or catalogue ID; repeat for several stars')
    p.add_argument('--channel',choices=['R','G','B','L','G1','G2'],default='G')
    p.add_argument('--count',type=int,default=4,help='Random panels when --star is absent (default: 4)')
    p.add_argument('--min-points',type=int,default=10)
    p.add_argument('--min-mag',type=float,default=2.5,help='Bright catalogue magnitude limit for random selection')
    p.add_argument('--max-mag',type=float,default=6.0,help='Faint catalogue magnitude limit for random selection')
    p.add_argument('--coverage',type=float,default=0.75,help='Minimum fraction of best-observed eligible star count')
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--max-degree',type=int,default=6,help='Largest polynomial degree considered by LOOCV (default: 6)')
    p.add_argument('--offline-names',action='store_true',help='Use saved/cached aliases without querying SIMBAD')
    args=p.parse_args(argv)
    if (args.max_degree < 0 or args.count < 1 or args.min_points < 1 or not 0 < args.coverage <= 1
            or not math.isfinite(args.min_mag) or not math.isfinite(args.max_mag)
            or args.min_mag > args.max_mag):
        p.error('Require nonnegative max-degree, positive count/min-points, 0 < coverage <= 1 and finite min-mag <= max-mag')
    try:
        args.database=(args.database or default_database()).expanduser().resolve()
        if args.manifest is None:
            args.manifest=next((path for path in [args.database.parent/'manifest.csv',
                                                args.database.parent.parent/'manifest.csv'] if path.is_file()),None)
        if args.manifest is None:
            raise ValueError('Supply --manifest /path/to/MMTO/manifest.csv for verified observation times')
        args.manifest=args.manifest.expanduser().resolve()
        rows,audit=load_measurements(args.database,args.manifest,args.channel)
        apply_cached_names(rows,args.database.parent/'lightcurves/display_names.json')
        selected=select_stars(rows,count=args.count,min_points=args.min_points,min_mag=args.min_mag,
                              max_mag=args.max_mag,coverage=args.coverage,seed=args.seed,stars=args.star)
        if not selected:
            raise ValueError('No qualifying MMTO stars yet; wait for more runs or lower --min-points/--coverage')
        if not args.star and len(selected)<args.count:
            print(f'Only {len(selected)} stars qualify; plotting those without relaxing the cuts.')
        output=args.output or args.database.parent/'lightcurves'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        scatter_groups=select_stars(rows,count=len(rows),min_points=args.min_points,min_mag=args.min_mag,
                                    max_mag=args.max_mag,coverage=args.coverage,seed=args.seed)
        output=output.expanduser().resolve()
        summary=write_outputs(selected,output,audit,args,scatter_groups=scatter_groups)
        latest=update_latest(output) if args.output is None else None
    except (ValueError,OSError,sqlite3.Error) as exc:
        p.exit(2,f'Error: {exc}\n')
    for star in summary:
        print(f"{star['display_name']} ({star['star_id']}): {star['measurements']} measurements; "
              f"degree {star['polynomial_fit']['degree']}; residual SD {star['polynomial_fit']['residual_sd_mag']} mag")
    print('Audit:',json.dumps(audit,sort_keys=True))
    print('Output:',output)
    print('Light curves PNG:',output/'lightcurves.png')
    print('SD versus magnitude PNG:',output/'sd_vs_magnitude.png')
    if latest:
        print('Latest light curves:',latest/'lightcurves.png')
        print('Latest SD versus magnitude:',latest/'sd_vs_magnitude.png')


if __name__ == '__main__':
    main()
