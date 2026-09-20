#!/usr/bin/env python3
"""MMTO database inspection: RGB catalogue comparisons, lightcurves, airmass and colours."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, closing
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.mmt_archive.download_mmt import exposure_metadata

LOCAL = ZoneInfo('America/Phoenix')
BANDS = {'R': 'RP', 'G': 'G', 'B': 'BP'}
BLIND_AIRMASS_SOURCES = {'blind_photometric_zenith', 'blind_centred_full_horizon_geometry'}


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def machine_magnitude(rate):
    rate = finite(rate)
    return -2.5 * math.log10(rate) if rate is not None and rate > 0 else float('nan')


def local_night(utc_mid):
    local = datetime.fromisoformat(utc_mid.replace('Z', '+00:00')).astimezone(LOCAL)
    noon = local.replace(hour=12, minute=0, second=0, microsecond=0)
    if local < noon:
        noon -= timedelta(days=1)
    return noon.date().isoformat(), (local - noon).total_seconds() / 3600


def json_object(value):
    try:
        result = json.loads(value) if value else {}
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def read_catalogue(path):
    with path.open(newline='') as handle:
        return {'Gaia DR3 ' + r['source_id']: {
            band: finite(r.get(column)) for band, column in
            [('G', 'phot_g_mean_mag'), ('RP', 'phot_rp_mean_mag'), ('BP', 'phot_bp_mean_mag')]
        } for r in csv.DictReader(handle)}


def cached_names(paths):
    names = {}
    for path in paths:
        if not path.is_file():
            continue
        for sid, record in json_object(path.read_text()).items():
            if not isinstance(record, dict):
                continue
            name = record.get('display_name', '')
            if not name or name == sid or name.startswith('Gaia DR3 '):
                continue
            names[sid] = name
            for alias in str(record.get('aliases', '')).split('|'):
                if alias.strip().startswith('Gaia DR3 '):
                    names[alias.strip()] = name
    return names


def image_metadata(source, digest, image_root):
    """Validate image identity, MMTO site and its documented FITS clock convention.

    The filename is only a locator. DATE-OBS supplies exposure start in MST;
    DATE independently checks its UTC conversion against exposure end.
    """
    from astropy.io import fits
    original = Path(source)
    candidates = [original]
    if not original.is_file() and image_root.is_dir():
        candidates.extend(image_root.rglob(original.name))
    for path in candidates:
        if not path.is_file():
            continue
        with path.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != digest:
                continue
        try:
            header = fits.getheader(path)
            # Do not use filenames as clocks: archive names can lag DATE by seconds.
            result = exposure_metadata(header, '')
        except (OSError, KeyError, TypeError, ValueError) as error:
            return None, f'FITS metadata rejected: {error}'
        result['verified_image_path'] = str(path.resolve())
        result['local_noon_day'], result['hours_since_local_noon'] = local_night(result['utc_mid'])
        return result, None
    return None, 'No original FITS file matching the database SHA-256'


def reduction_configuration(result, manifest):
    """Fingerprint saved settings, not fitted values, filenames or run timestamps.

    Historical runs do not save the complete CLI. This describes only recorded
    provenance, not proof that every unrecorded option was identical.
    """
    code = result.get('code_sha256')
    manifest_hashes = manifest.get('sha256')
    if (not result.get('model') or result.get('epoch_mode') not in ('fit', 'fixed', 'catalog')
            or not (isinstance(code, dict) and code
                    or isinstance(manifest_hashes, dict) and manifest_hashes)):
        return None
    config = {key: result.get(key) for key in
              ('model', 'epoch_mode', 'blind', 'metadata_used', 'configuration')}
    config['code_sha256'] = code
    # Conservative separation also covers dependencies absent from code_sha256.
    config['source_manifest_sha256'] = (hashlib.sha256(json.dumps(
        manifest_hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if manifest_hashes else None)
    if result['epoch_mode'] == 'fixed':
        year = finite(result.get('coordinate_epoch_jyear'))
        if year is None:
            return None
        config['fixed_epoch_jyear'] = year
    elif result['epoch_mode'] == 'fit':
        epoch = result.get('stellar_epoch') or {}
        if not isinstance(epoch, dict):
            return None
        limits = epoch.get('search_limits_jyear')
        if isinstance(limits, list) and len(limits) == 2:
            limits = list(limits)
            ceiling = result.get('causal_epoch_ceiling') or epoch.get('causal_epoch_ceiling') or {}
            if not isinstance(ceiling, dict):
                return None
            if (ceiling.get('source') == 'current_system_time_at_run_start'
                    and limits[1] == ceiling.get('jyear')):
                limits[1] = 'current_system_time_at_run_start'
            config['epoch_search_limits_jyear'] = limits
    return config


def select_mmto_runs(db, *, solver_version=None, config_sha256=None, catalogue_sha256=None):
    """Select the latest successful run per image, or one explicitly requested cohort.

    Call inside the caller's read transaction. Selection precedes all photometric
    quality cuts; an unusable new channel cannot resurrect an older measurement.
    """
    columns = ('run_id', 'recorded_at_utc', 'source_path', 'source_sha256',
               'catalogue_sha256', 'solver_version', 'result_json', 'source_manifest_json', 'exit_code')
    groups, configurations = defaultdict(list), {}
    audit = dict(failed_mmto_runs=0, unusable_provenance_runs=0, nonblind_control_runs=0,
                 other_solver_runs=0, successful_mmto_candidate_runs=0)
    database_connections = [(None, db)] if hasattr(db, 'execute') else list(db)
    all_runs = []
    for database_path, connection in database_connections:
        for values in connection.execute(
                'SELECT '+', '.join(columns)+' FROM runs ORDER BY recorded_at_utc, run_id'):
            run = dict(zip(columns, values))
            run['source_database'] = database_path
            all_runs.append(run)
    all_runs.sort(key=lambda run: (run['recorded_at_utc'], run['run_id'],
                                   run['source_database'] or ''))
    # A known MMTO content hash remains a candidate after a filename/path change.
    # Original FITS validation still checks the actual site before plotting.
    mmto_hashes = {r['source_sha256'] for r in all_runs if r['source_sha256']
                   and 'mmto' in (r['source_path'] or '').lower()}
    for run in all_runs:
        if ('mmto' not in (run['source_path'] or '').lower()
                and run['source_sha256'] not in mmto_hashes):
            continue
        if run['exit_code'] != 0:
            audit['failed_mmto_runs'] += 1
            continue
        audit['successful_mmto_candidate_runs'] += 1
        if solver_version is not None and run['solver_version'] != solver_version:
            audit['other_solver_runs'] += 1
            continue
        config = reduction_configuration(json_object(run.pop('result_json')),
                                         json_object(run.pop('source_manifest_json')))
        if (not run['source_sha256'] or not run['catalogue_sha256']
                or not run['solver_version'] or config is None):
            audit['unusable_provenance_runs'] += 1
            continue
        digest = hashlib.sha256(json.dumps(config, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        run['config_sha256'] = digest
        key = (run['solver_version'], digest, run['catalogue_sha256'])
        groups[key].append(run)
        configurations[key] = config
    available = [dict(solver_version=key[0], config_sha256=key[1], catalogue_sha256=key[2],
                      configuration=configurations[key], successful_runs=len(runs),
                      unique_images=len({r['source_sha256'] for r in runs}))
                 for key, runs in sorted(groups.items())]
    eligible = [key for key in groups if (config_sha256 is None or key[1] == config_sha256)
                and (catalogue_sha256 is None or key[2] == catalogue_sha256)]
    if not eligible:
        raise ValueError('No successful MMTO runs with usable provenance match '
                         f'solver={solver_version or "any"}, config={config_sha256}, '
                         f'catalogue={catalogue_sha256}. Use --list-reductions to inspect '
                         'available reduction groups.')
    if solver_version is None and config_sha256 is None and catalogue_sha256 is None:
        controls = [key for key in eligible if not (
            configurations[key].get('epoch_mode') == 'fit'
            and configurations[key].get('blind') is True
            and configurations[key].get('metadata_used') is not True)]
        audit['nonblind_control_runs'] = sum(len(groups[key]) for key in controls)
        eligible = [key for key in eligible if key not in controls]
        if not eligible:
            raise ValueError('No successful blind fitted-epoch MMTO runs with usable provenance; '
                             'use explicit reduction selectors to inspect control runs.')
        candidates = [run for key in eligible for run in groups[key]]
        latest = {}
        for run in candidates:
            latest[run['source_sha256']] = run
        runs = sorted(latest.values(), key=lambda r: (r['recorded_at_utc'], r['run_id'],
                                                      r['source_database'] or ''))
        versions = Counter(r['solver_version'] for r in runs)
        catalogues = Counter(r['catalogue_sha256'] for r in runs)
        selected_keys = {(r['solver_version'], r['config_sha256'], r['catalogue_sha256'])
                         for r in runs}
        audit.update(
            selection_mode='latest_successful_per_image_across_all_reductions',
            policy='latest successful usable-provenance run per image SHA-256 across all reductions before quality cuts',
            cohort_policy=None,
            configuration_scope='recorded settings and code provenance; historical CLI may be incomplete',
            available_reductions=available,
            selected=dict(scope='all_reductions',
                          solver_versions=dict(sorted(versions.items())),
                          catalogue_sha256s=dict(sorted(catalogues.items())),
                          reduction_cohorts=len(selected_keys),
                          successful_runs=len(candidates), unique_images=len(runs)),
            selected_run_ids=[r['run_id'] for r in runs],
            superseded_successful_runs=len(candidates)-len(runs),
            other_reduction_runs=0)
        return runs, audit
    # Coverage counts images, never repeated runs. Ties prefer the newest cohort,
    # then the lexical key for reproducibility within a database snapshot.
    chosen = max(eligible, key=lambda key: (
        len({r['source_sha256'] for r in groups[key]}),
        max((r['recorded_at_utc'], r['run_id'], r['source_database'] or '')
            for r in groups[key]), key))
    latest = {}
    for run in groups[chosen]:
        latest[run['source_sha256']] = run
    runs = sorted(latest.values(), key=lambda r: (r['recorded_at_utc'], r['run_id'],
                                                  r['source_database'] or ''))
    audit.update(selection_mode='explicit_reduction_cohort',
                 policy='one reduction cohort; latest successful run per image SHA-256 before quality cuts',
                 cohort_policy='most unique images; ties newest recorded run, then lexical key',
                 configuration_scope='recorded settings and code provenance; historical CLI may be incomplete',
                 available_reductions=available,
                 selected=next(r for r in available if
                               (r['solver_version'], r['config_sha256'], r['catalogue_sha256']) == chosen),
                 selected_run_ids=[r['run_id'] for r in runs],
                 superseded_successful_runs=len(groups[chosen])-len(runs),
                 other_reduction_runs=sum(len(v) for k, v in groups.items() if k != chosen))
    return runs, audit


def database_paths(database):
    if isinstance(database, (str, Path)):
        return [Path(database)]
    return [Path(path) for path in database]


def load_measurements(database, catalogue, image_root, *, solver_version=None,
                      config_sha256=None, catalogue_sha256=None):
    databases = database_paths(database)
    gaia = read_catalogue(catalogue)
    names = cached_names([ROOT/'v10/data/display_names.json'] +
                         [path.parent/'lightcurves/display_names.json' for path in databases])
    rows, images = [], []
    audit = Counter()
    with ExitStack() as stack:
        connections = {}
        for path in databases:
            resolved = str(path.resolve())
            connection = stack.enter_context(closing(sqlite3.connect(
                Path(resolved).as_uri()+'?mode=ro', uri=True)))
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            connections[resolved] = connection
        runs, run_selection = select_mmto_runs(list(connections.items()),
                                              solver_version=solver_version,
                                              config_sha256=config_sha256,
                                              catalogue_sha256=catalogue_sha256)
        for run in runs:
            db = connections[run['source_database']]
            run_id, source, digest, cat_sha = (run[k] for k in
                                             ('run_id', 'source_path', 'source_sha256', 'catalogue_sha256'))
            provenance_fields = {k: run[k] for k in ('solver_version', 'config_sha256', 'recorded_at_utc')}
            meta, error = image_metadata(source, digest, image_root)
            images.append(dict(run_id=run_id, source_path=source, source_sha256=digest,
                               catalogue_sha256=cat_sha, timing=meta, omission_reason=error,
                               source_database=run['source_database'],
                               **provenance_fields))
            if meta is None:
                audit['images_without_verified_mmto_time'] += 1
                continue
            audit['verified_images'] += 1
            photo = db.execute("SELECT content FROM products WHERE run_id=? AND product='photometry_summary.json'",
                               (run_id,)).fetchone()
            provenance = json_object(photo[0] if photo else None)
            airmass_source = provenance.get('airmass_source', '')
            airmass_verified = (provenance.get('metadata_used') is False
                                and airmass_source in BLIND_AIRMASS_SOURCES)
            saved = db.execute("SELECT content FROM products WHERE run_id=? AND product='display_names.json'",
                               (run_id,)).fetchone()
            for sid, details in json_object(saved[0] if saved else None).items():
                if isinstance(details, dict):
                    name = details.get('display_name', '')
                    if name and name != sid and not name.startswith('Gaia DR3 '):
                        names[sid] = name
            seen = set()
            for sid, detection, payload in db.execute('''SELECT star_id, detection_id, values_json
                    FROM measurements WHERE run_id=? AND product='stellar_photometry.csv'
                    ORDER BY row_number''', (run_id,)):
                if sid not in gaia or gaia[sid]['G'] is None:
                    continue
                if sid in seen:
                    raise ValueError(f'Duplicate star {sid} in run {run_id}')
                seen.add(sid)
                v = json_object(payload)
                seconds = finite(v.get('exposure_seconds'))
                if (v.get('exposure_status') != 'available' or seconds is None or seconds <= 0
                        or not math.isclose(seconds, meta['exposure_seconds'], rel_tol=1e-6)):
                    audit['rows_without_consistent_exposure'] += 1
                    continue
                for channel in 'RGB':
                    rate = finite(v.get(channel+'_count_rate_adu_per_s'))
                    if (rate is None or rate <= 0
                            or str(v.get('saturation_known', '')).lower() != 'true'
                            or str(v.get(channel+'_saturated', '')).lower() != 'false'
                            or v.get(channel+'_measurement_method') != 'aperture'):
                        audit[channel+'_rejected_rows'] += 1
                        continue
                    rows.append(dict(run_id=run_id, source_path=source, source_sha256=digest,
                        source_database=run['source_database'],
                        **provenance_fields,
                        catalogue_sha256=cat_sha, star_id=sid, detection_id=detection,
                        display_name=names.get(sid, ''), channel=channel,
                        gaia_g=gaia[sid]['G'], gaia_rp=gaia[sid]['RP'], gaia_bp=gaia[sid]['BP'],
                        exposure_seconds=seconds, count_rate_adu_per_s=rate,
                        airmass=finite(v.get('airmass')), airmass_source=airmass_source,
                        airmass_verified=airmass_verified,
                        machine_mag=machine_magnitude(rate), utc_mid=meta['utc_mid'],
                        local_noon_day=meta['local_noon_day'],
                        hours_since_local_noon=meta['hours_since_local_noon']))
        for db in connections.values():
            db.rollback()
    # Late saved aliases can name the same star in earlier runs.
    for row in rows:
        row['display_name'] = names.get(row['star_id'], '')
    return rows, dict(audit, run_selection=run_selection), images


def select_stars(rows, minimum=3, coverage=.6, target=5.):
    grouped = defaultdict(list)
    for row in rows:
        if row['channel'] == 'G':
            grouped[row['star_id']].append(row)
    if not grouped:
        return []
    limit = max(minimum, math.ceil(coverage * max(map(len, grouped.values()))))
    eligible = [(key, group) for key, group in grouped.items() if len(group) >= limit]
    bright = sorted(eligible, key=lambda item: (item[1][0]['gaia_g'], -len(item[1]), item[0]))[:4]
    used = {key for key, _ in bright}
    faint = sorted((item for item in eligible if item[0] not in used),
                   key=lambda item: (abs(item[1][0]['gaia_g']-target), -len(item[1]), item[0]))[:4]
    return [dict(catalogue_sha256=(group[0]['catalogue_sha256'] if len({
                     r['catalogue_sha256'] for r in group}) == 1 else None),
                 catalogue_sha256s=sorted({r['catalogue_sha256'] for r in group}), star_id=key,
                 display_name=next((r['display_name'] for r in group if r['display_name']), ''),
                 gaia_g=group[0]['gaia_g'], g_measurements=len(group),
                 column=col, row=index)
            for col, sample in enumerate((bright, faint)) for index, (key, group) in enumerate(sample)]


def night_styles(rows):
    nights = sorted({r['local_noon_day'] for r in rows})
    colours = plt.get_cmap('tab10')
    return {night: (colours(i % 10), ('o', 's', '^', 'D', 'v')[i % 5])
            for i, night in enumerate(nights)}


def catalogue_page(rows, selected, args):
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    styles = night_styles(rows)
    for ax, channel in zip(axes, 'RGB'):
        band = 'G' if args.catalogue_band == 'G' else BANDS[channel]
        field = 'gaia_'+band.lower()
        values = [r for r in rows if r['channel'] == channel and r[field] is not None]
        for night, (colour, marker) in styles.items():
            group = [r for r in values if r['local_noon_day'] == night]
            if group:
                ax.scatter([r[field] for r in group], [r['machine_mag'] for r in group],
                           s=7, alpha=.35, color=colour, marker=marker, linewidths=0,
                           rasterized=True, label=night)
        ax.set(title=f'{channel} versus Gaia {band} | N={len(values):,}',
               xlabel=f'Gaia {band} [mag]', ylabel=f'{channel} machine magnitude [mag]')
        ax.invert_xaxis(); ax.invert_yaxis(); ax.grid(alpha=.2)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5, .92),
               ncol=max(1, len(labels)), frameon=False, markerscale=2)
    fig.suptitle('MMTO: R, G and B machine magnitudes versus Gaia', fontsize=17)
    fig.text(.5, .035, 'Machine magnitude = −2.5 log₁₀(ADU/s). Nights labelled by local-noon date.\n'
             'Camera and Gaia passbands differ; these are uncalibrated instrumental magnitudes.',
             ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .1, 1, .84))
    return fig


def lightcurve_page(rows, selected, args, channel, *, against_airmass=False):
    compact = channel == 'RGB'
    fig, axes = plt.subplots(4, 6 if compact else 2,
                             figsize=(24, 12) if compact else (15, 12), sharex=True)
    styles = night_styles(rows)
    lookup = defaultdict(list)
    for row in rows:
        lookup[(row['star_id'], row['channel'])].append(row)
    for ax in axes.flat:
        ax.set_visible(False)
    if compact:
        panels = [(s, axes[s['row'], 3*s['column']+c], ch)
                  for s in selected for c, ch in enumerate('RGB')]
    else:
        panels = [(s, axes[s['row'], s['column']], channel) for s in selected]
    page_magnitudes = []
    for star, ax, panel_channel in panels:
        band = 'G' if args.catalogue_band == 'G' else BANDS[panel_channel]
        catalogue_field = 'gaia_'+band.lower()
        ax.set_visible(True)
        group = lookup[(star['star_id'], panel_channel)]
        original_count = len(group)
        if against_airmass:
            group = [r for r in group if r.get('airmass_verified')
                     and finite(r.get('airmass')) is not None and r['airmass'] >= 1
                     and finite(r.get(catalogue_field)) is not None]
        label = star['display_name'] or f"Star {star['row']+1+4*star['column']} (name unavailable)"
        for night, (colour, marker) in styles.items():
            points = sorted((r for r in group if r['local_noon_day'] == night),
                            key=lambda r: r['utc_mid'])
            if points:
                x = [r['airmass'] if against_airmass else r['hours_since_local_noon'] for r in points]
                y = [r['machine_mag']-r[catalogue_field] if against_airmass else r['machine_mag'] for r in points]
                page_magnitudes.extend(value for value in map(finite, y) if value is not None)
                ax.scatter(x, y, s=32, alpha=.85,
                           color=colour, marker=marker, label=night)
        omission = f' | omitted={original_count-len(group)}' if len(group) < original_count else ''
        ax.set_title(f"{label} | Gaia G {star['gaia_g']:.2f} | N={len(group)}{omission}",
                     loc='left', fontsize=8 if compact else 10)
        ax.set_ylabel(f'{panel_channel} machine − Gaia {band} [mag]' if against_airmass else f'{panel_channel} machine mag')
        if not against_airmass:
            ax.invert_yaxis()
        ax.grid(alpha=.22)
        if not group:
            message = 'No verified airmass/catalogue pairs' if against_airmass else 'No usable rates in this channel'
            ax.text(.5, .5, message, ha='center', transform=ax.transAxes)
    if page_magnitudes:
        low, high = min(page_magnitudes), max(page_magnitudes)
        padding = max(.05, .05*(high-low))
        for _, ax, _ in panels:
            ax.set_ylim((low-padding, high+padding) if against_airmass
                        else (high+padding, low-padding))
    if not selected:
        axes[0, 0].set_visible(True)
        axes[0, 0].text(.5, .5, 'Insufficient repeated stars for the requested coverage',
                        ha='center', transform=axes[0, 0].transAxes)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=c, marker=m, linestyle='', label=n) for n, (c, m) in styles.items()]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.5, .952),
               ncol=max(1, len(styles)), frameon=False, title='Local-noon day')
    comparison = 'G' if args.catalogue_band == 'G' else ('RP/G/BP' if compact else BANDS[channel])
    title = (f'MMTO: {channel} machine magnitude − Gaia {comparison} versus airmass' if against_airmass
             else f'MMTO: selected-star {channel} machine magnitudes versus time')
    fig.suptitle(title, fontsize=17, y=.99)
    if compact:
        fig.text(.255, .89, 'Bright sample', ha='center', weight='bold')
        fig.text(.745, .89, f'Near Gaia G = {args.target_mag:g}', ha='center', weight='bold')
        for block in range(2):
            for column, panel_channel in enumerate('RGB'):
                fig.text((block*3+column+.5)/6, .865, panel_channel+' channel',
                         ha='center', weight='bold')
    else:
        fig.text(.27, .893, 'Bright sample', ha='center', weight='bold')
        fig.text(.76, .893, f'Near Gaia G = {args.target_mag:g}', ha='center', weight='bold')
    fig.supxlabel('Stored airmass from the blind image solution' if against_airmass
                  else 'Hours since preceding local noon at MMTO (America/Phoenix)', y=.045)
    footer = ('Machine mag = −2.5 log₁₀(stored ADU/s). Stored blind airmass; common y-range; '
              'no fit or clipping. Camera/Gaia passbands differ.' if against_airmass else
              '−2.5 log₁₀(stored ADU/s); exposure midpoint from verified FITS clocks. '
              'Same stars in R/G/B; common y-range. No detrending or clipping.')
    fig.text(.5, .012, footer, ha='center', fontsize=9)
    fig.subplots_adjust(left=.06 if compact else .08, right=.985, bottom=.10,
                        top=.82 if compact else .86, hspace=.38, wspace=.30 if compact else .24)
    return fig


def colour_measurements(rows, max_mag=5.5):
    """Pair accepted channels of one detection, never different images or reductions."""
    grouped = defaultdict(dict)
    for row in rows:
        key = (row.get('source_database'),) + tuple(
            row[k] for k in ('catalogue_sha256', 'run_id', 'source_sha256',
                             'star_id', 'detection_id'))
        if row['channel'] in grouped[key]:
            raise ValueError(f'Duplicate colour channel for {key}')
        grouped[key][row['channel']] = row
    result = []
    for channels in grouped.values():
        if not all(c in channels for c in 'RGB'):
            continue
        g = channels['G']
        mags = {c: machine_magnitude(channels[c]['count_rate_adu_per_s']) for c in 'RGB'}
        catalogue = [finite(g.get(k)) for k in ('gaia_g', 'gaia_bp', 'gaia_rp')]
        if (any(v is None for v in catalogue) or catalogue[0] > max_mag
                or not all(math.isfinite(v) for v in mags.values())):
            continue
        airmass = finite(g.get('airmass'))
        if not g.get('airmass_verified') or airmass is None or airmass < 1:
            continue
        record = {k: g[k] for k in ('catalogue_sha256', 'run_id', 'source_sha256',
                                   'star_id', 'detection_id', 'utc_mid', 'local_noon_day', 'gaia_g')}
        record.update(gaia_bp_minus_rp=catalogue[1]-catalogue[2],
                      machine_b_minus_g=mags['B']-mags['G'],
                      machine_g_minus_r=mags['G']-mags['R'], airmass=airmass)
        result.append(record)
    return result


def colour_page(rows, selected, args):
    values = colour_measurements(rows, args.colour_max_mag)
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    options = dict(s=9, alpha=.4, linewidths=0, rasterized=True)
    if values:
        scatter = axes[0].scatter([v['machine_g_minus_r'] for v in values],
                                 [v['machine_b_minus_g'] for v in values],
                                 c=[v['gaia_bp_minus_rp'] for v in values], cmap='coolwarm', **options)
        fig.colorbar(scatter, ax=axes[0], label='Gaia BP − RP [mag]', location='bottom', pad=.18)
    axes[0].set(title='Camera colour–colour', xlabel='Machine G − R [mag]', ylabel='Machine B − G [mag]')
    norm = None
    if values:
        # A shared logarithmic scale retains the full horizon range without clipping.
        from matplotlib.colors import LogNorm
        lo, hi = min(v['airmass'] for v in values), max(v['airmass'] for v in values)
        norm = LogNorm(vmin=lo, vmax=hi if hi > lo else lo*1.01)
    for ax, field, label in zip(axes[1:], ('machine_b_minus_g', 'machine_g_minus_r'), ('B − G', 'G − R')):
        if values:
            scatter = ax.scatter([v['gaia_bp_minus_rp'] for v in values], [v[field] for v in values],
                                 c=[v['airmass'] for v in values], cmap='viridis', norm=norm, **options)
            fig.colorbar(scatter, ax=ax, label='Stored blind airmass (log scale)', location='bottom', pad=.18)
        ax.set(title=f'Camera {label} versus Gaia colour', xlabel='Gaia BP − RP [mag]',
               ylabel=f'Machine {label} [mag]')
    for ax in axes:
        ax.grid(alpha=.2)
        if not values:
            ax.text(.5, .5, 'No usable same-exposure RGB colours', ha='center', transform=ax.transAxes)
    stars = len({(v['catalogue_sha256'], v['star_id']) for v in values})
    fig.suptitle(f'MMTO: instrumental colours | Gaia G ≤ {args.colour_max_mag:g} | '
                 f'{stars:,} stars, {len(values):,} star–exposure pairs', fontsize=16)
    fig.text(.5, .025, 'Colours from −2.5 log₁₀(stored ADU/s), with all three channels usable in the same exposure.\n'
             'Individual measurements; no averaging, fitting or extinction correction. Camera and Gaia passbands differ.',
             ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .10, 1, .93))
    return fig


PLOT_REGISTRY = {'rgb_catalogue': catalogue_page}
for _channel in 'RGB':
    PLOT_REGISTRY['lightcurves_'+_channel] = (
        lambda rows, selected, args, channel=_channel: lightcurve_page(rows, selected, args, channel))
for _channel in 'RGB':
    PLOT_REGISTRY['airmass_'+_channel] = (
        lambda rows, selected, args, channel=_channel:
        lightcurve_page(rows, selected, args, channel, against_airmass=True))
PLOT_REGISTRY['colours'] = colour_page
PLOT_REGISTRY['lightcurves_RGB'] = lambda rows, selected, args: lightcurve_page(rows, selected, args, 'RGB')
PLOT_REGISTRY['airmass_RGB'] = lambda rows, selected, args: lightcurve_page(rows, selected, args, 'RGB', against_airmass=True)
DEFAULT_PLOTS = ['rgb_catalogue', 'lightcurves_RGB', 'airmass_RGB', 'colours']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, action='append',
                        help='solution database; repeat to combine databases (default: main and automatic MMTO)')
    parser.add_argument('--solver-version',
                        help='restrict plots to one exact saved solver version; default: latest successful solution per image across all versions')
    parser.add_argument('--config-sha256', help='pin a recorded configuration fingerprint from --list-reductions')
    parser.add_argument('--catalogue-sha256', help='pin the solver catalogue digest (not the Gaia comparison CSV)')
    parser.add_argument('--list-reductions', action='store_true', help='show eligible reduction groups without plotting')
    parser.add_argument('--catalogue', type=Path, default=ROOT/'v10/data/stars_gaia_dr3_g75.gaia-source.csv')
    parser.add_argument('--image-root', type=Path, default=ROOT/'raw_allsky_samples')
    parser.add_argument('--output', type=Path, default=ROOT/'results/inspection')
    parser.add_argument('--overwrite', action='store_true', help='replace this tool\'s generated files')
    parser.add_argument('--plots', default=','.join(DEFAULT_PLOTS),
                        help='comma-separated registry keys; default: four compact pages; all: every variant')
    parser.add_argument('--catalogue-band', choices=('matched', 'G'), default='matched',
                        help='matched: R/RP, G/G, B/BP; G: compare all channels with Gaia G')
    parser.add_argument('--min-points', type=int, default=3)
    parser.add_argument('--coverage', type=float, default=.6)
    parser.add_argument('--target-mag', type=float, default=5.)
    parser.add_argument('--colour-max-mag', type=float, default=5.5,
                        help='faint Gaia G limit for same-exposure RGB colour diagrams')
    args = parser.parse_args(argv)
    databases = args.database or [ROOT/'results/stars.sqlite']
    automatic_database = ROOT/'results/mmto-automatic/stars.sqlite'
    if args.database is None and automatic_database.is_file():
        databases.append(automatic_database)
    keys = list(PLOT_REGISTRY) if args.plots == 'all' else args.plots.split(',')
    if not keys or any(k not in PLOT_REGISTRY for k in keys):
        parser.error('Choose plot keys from: '+', '.join(PLOT_REGISTRY))
    if args.min_points < 2 or not 0 < args.coverage <= 1:
        parser.error('Require --min-points >= 2 and 0 < --coverage <= 1')
    if finite(args.colour_max_mag) is None:
        parser.error('Require finite --colour-max-mag')
    selection_options = dict(solver_version=args.solver_version, config_sha256=args.config_sha256,
                             catalogue_sha256=args.catalogue_sha256)
    try:
        if args.list_reductions:
            with ExitStack() as stack:
                connections = []
                for path in databases:
                    db = stack.enter_context(closing(sqlite3.connect(
                        path.resolve().as_uri()+'?mode=ro', uri=True)))
                    db.execute('PRAGMA query_only=ON')
                    db.execute('BEGIN')
                    connections.append((str(path.resolve()), db))
                _, selection = select_mmto_runs(connections, **selection_options)
            print(json.dumps(selection, indent=2))
            return
        rows, audit, images = load_measurements(databases, args.catalogue, args.image_root,
                                                **selection_options)
    except (ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    if not rows:
        parser.error('No MMTO rates with verified original FITS metadata; check --database and --image-root')
    run_selection = audit.pop('run_selection')
    for row in rows:
        band = 'G' if args.catalogue_band == 'G' else BANDS[row['channel']]
        catalogue_mag = row['gaia_'+band.lower()]
        row['comparison_catalogue_band'] = band
        row['machine_minus_catalogue_mag'] = (row['machine_mag']-catalogue_mag
                                              if catalogue_mag is not None else None)
    selected = select_stars(rows, args.min_points, args.coverage, args.target_mag)
    args.output.mkdir(parents=True, exist_ok=True)
    products = ['inspection.pdf', 'measurements.csv', 'selected_stars.json', 'summary.json']
    colours = colour_measurements(rows, args.colour_max_mag) if 'colours' in keys else []
    if 'colours' in keys:
        products.append('colours.csv')
    products += [f'{i:02d}_{key}.png' for i, key in enumerate(keys, 1)]
    previous_summary = json_object((args.output/'summary.json').read_text()
                                   if (args.output/'summary.json').is_file() else None)
    previous_products = previous_summary.get('generated_files', [])
    stale_generated_plots = []
    if args.overwrite and isinstance(previous_products, list):
        for name in previous_products:
            if (not isinstance(name, str) or name in products or Path(name).name != name
                    or len(name) < 8 or not name[:2].isdigit() or name[2] != '_'
                    or not name.endswith('.png')):
                continue
            path = args.output/name
            if path.is_file() or path.is_symlink():
                stale_generated_plots.append(path)
        stale_generated_plots.sort()
    if not args.overwrite and any((args.output/p).exists() for p in products):
        parser.error('Output exists; use --overwrite to regenerate')
    with PdfPages(args.output/'inspection.pdf') as pdf:
        for index, key in enumerate(keys, 1):
            fig = PLOT_REGISTRY[key](rows, selected, args)
            fig.savefig(args.output/f'{index:02d}_{key}.png', dpi=170)
            pdf.savefig(fig); plt.close(fig)
    with (args.output/'measurements.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    if 'colours' in keys:
        with (args.output/'colours.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                'catalogue_sha256', 'run_id', 'source_sha256', 'star_id', 'detection_id',
                'utc_mid', 'local_noon_day', 'gaia_g', 'gaia_bp_minus_rp',
                'machine_b_minus_g', 'machine_g_minus_r', 'airmass'])
            writer.writeheader(); writer.writerows(colours)
    (args.output/'selected_stars.json').write_text(json.dumps(selected, indent=2)+'\n')
    solver_versions = dict(sorted(Counter(i['solver_version'] for i in images).items()))
    catalogue_sha256s = sorted({i['catalogue_sha256'] for i in images})
    summary = dict(database=str(databases[0].resolve()),
                   databases=[str(path.resolve()) for path in databases],
                   dataset='MMTO', plots=keys,
                   solver_version=next(iter(solver_versions)) if len(solver_versions) == 1 else None,
                   solver_versions=solver_versions, run_selection=run_selection,
                   plotter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   comparison_catalogue_sha256=hashlib.sha256(args.catalogue.read_bytes()).hexdigest(),
                   rate_only=True, magnitude_definition='-2.5 log10(stored ADU/s)',
                   catalogue_band=args.catalogue_band,
                   catalogue_sha256=catalogue_sha256s[0] if len(catalogue_sha256s) == 1 else None,
                   catalogue_sha256s=catalogue_sha256s,
                   local_timezone='America/Phoenix', time_axis='hours since preceding local noon',
                   measurements_by_channel=dict(Counter(r['channel'] for r in rows)),
                   airmass_definition='Stored blind image-solution airmass; finite values >= 1',
                   selected_airmass_points_by_channel={c: sum(
                       r['channel'] == c and r['airmass_verified'] and r['airmass'] is not None
                       and r['airmass'] >= 1 and r['machine_minus_catalogue_mag'] is not None
                       and any(s['star_id'] == r['star_id'] for s in selected)
                       for r in rows) for c in 'RGB'},
                   images_by_local_noon_day={night: len({r['source_sha256'] for r in rows
                       if r['local_noon_day'] == night}) for night in night_styles(rows)},
                   selection=dict(min_points=args.min_points, coverage=args.coverage,
                                  target_mag=args.target_mag, stars=selected,
                                  rgb_page_star_ids=[s['star_id'] for s in selected]),
                   colours=dict(enabled='colours' in keys, max_gaia_g=args.colour_max_mag,
                                star_exposure_pairs=len(colours),
                                stars=len({v['star_id'] for v in colours})),
                   audit=audit, image_provenance=images, generated_files=products,
                   removed_stale_generated_plots=[p.name for p in stale_generated_plots])
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    for path in stale_generated_plots:
        path.unlink()
    print(args.output/'inspection.pdf')
    image_count = len(run_selection['selected_run_ids'])
    verified_image_count = audit.get('verified_images', 0)
    night_count = len(summary['images_by_local_noon_day'])
    if run_selection['selection_mode'] == 'latest_successful_per_image_across_all_reductions':
        print(f"Selected latest successful solution for each image: {image_count} unique "
              f"database image{'s' if image_count != 1 else ''}; verified FITS data for "
              f"{verified_image_count} across {night_count} plotted "
              f"night{'s' if night_count != 1 else ''}.")
    else:
        selected = run_selection['selected']
        print(f"Selected explicit solver {selected['solver_version']} reduction "
              f"{selected['config_sha256']}: {image_count} unique database "
              f"image{'s' if image_count != 1 else ''}; verified FITS data for "
              f"{verified_image_count} across {night_count} plotted "
              f"night{'s' if night_count != 1 else ''}.")
    print('Solver versions used: '+', '.join(
        f'{version} ({count} image{"s" if count != 1 else ""})'
        for version, count in solver_versions.items()))
    print(f"Plots: {len(keys)} pages ({', '.join(keys)}).")
    print('Measurements: '+', '.join(
        f'{channel}={summary["measurements_by_channel"].get(channel, 0)}' for channel in 'RGB')+'.')
    print('Nights: '+', '.join(
        f'{night}={count} image{"s" if count != 1 else ""}'
        for night, count in summary['images_by_local_noon_day'].items())+'.')
    exclusions = [
        (run_selection['superseded_successful_runs'],
         'superseded successful run', 'superseded successful runs'),
        (run_selection['other_reduction_runs'],
         'successful run from another reduction cohort',
         'successful runs from other reduction cohorts'),
        (run_selection['other_solver_runs'],
         'successful run from another solver version',
         'successful runs from other solver versions'),
        (run_selection['failed_mmto_runs'], 'failed MMTO run', 'failed MMTO runs'),
        (run_selection['nonblind_control_runs'],
         'non-blind control run', 'non-blind control runs'),
        (run_selection['unusable_provenance_runs'],
         'successful run with unusable provenance',
         'successful runs with unusable provenance'),
    ]
    print('Excluded: '+', '.join(
        f'{count} {singular if count == 1 else plural}'
        for count, singular, plural in exclusions)+'.')
    if stale_generated_plots:
        print(f'Removed {len(stale_generated_plots)} stale generated plot file'
              f'{"s" if len(stale_generated_plots) != 1 else ""}.')


if __name__ == '__main__':
    main()
