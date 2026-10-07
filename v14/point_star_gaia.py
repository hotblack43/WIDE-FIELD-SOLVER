"""Reproducible Gaia DR3 adapter for the solver's native seven-column catalogue."""
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
from scipy.spatial import cKDTree
from point_star_epoch import Catalogue

FIELDS = ('star_id', 'ra_deg', 'dec_deg', 'mag', 'reference_epoch_jyear',
          'pm_ra_cosdec_mas_per_year', 'pm_dec_mas_per_year')
ENDPOINT = 'https://gea.esac.esa.int/tap-server/tap/sync'
COLUMNS = ('source_id,ref_epoch,ra,dec,pmra,pmdec,phot_g_mean_mag,'
           'phot_bp_mean_mag,phot_rp_mean_mag,ruwe,astrometric_params_solved,'
           'duplicated_source,ra_error,dec_error,pmra_error,pmdec_error,parallax,radial_velocity')


def convert_rows(raw):
    """Map native Gaia fields without rotating coordinates or rounding identifiers."""
    result, seen = [], set()
    for row in raw:
        source = str(row['source_id']).strip()
        if not source.isdecimal() or source in seen:
            raise ValueError(f'Invalid or duplicate Gaia identifier: {source}')
        seen.add(source)
        result.append(dict(zip(FIELDS, [f'Gaia DR3 {source}', row['ra'], row['dec'],
            row['phot_g_mean_mag'], row['ref_epoch'], row['pmra'], row['pmdec']])))
    Catalogue.from_rows(result)
    if not all(np.isfinite(float(r['mag'])) for r in result):
        raise ValueError('Non-finite Gaia magnitude')
    return result


def supplement_bright(gaia, existing, limit=3., radius_arcsec=3.):
    """Keep missing bright references, checking duplication at a common epoch."""
    tree = cKDTree(Catalogue.from_rows(gaia).at_year(2016.))
    bright = [dict(r) for r in existing if float(r['mag']) <= limit]
    audit = dict(supplement_count=0, magnitude_limit=limit,
                 deduplication_epoch_jyear=2016., deduplication_radius_arcsec=radius_arcsec,
                 supplement_ids=[], suppressed_ids=[], ambiguous_neighbours=0)
    if not bright:
        return list(gaia), audit
    rays = Catalogue.from_rows(bright).at_year(2016.)
    neighbours = tree.query_ball_point(rays, 2*np.sin(np.deg2rad(radius_arcsec/3600)/2))
    extra = []
    for row, indices in zip(bright, neighbours):
        if indices:
            audit['suppressed_ids'].append(row['star_id'])
            audit['ambiguous_neighbours'] += int(len(indices)>1)
        else:
            extra.append(row)
            audit['supplement_ids'].append(row['star_id'])
    audit['supplement_count'] = len(extra)
    return list(gaia)+extra, audit


def fetch_csv(query):
    url = ENDPOINT+'?'+urlencode(dict(REQUEST='doQuery', LANG='ADQL', FORMAT='csv',
                                     MAXREC=500000, QUERY=query))
    with urlopen(url, timeout=180) as response:
        text = response.read().decode('utf-8')
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise RuntimeError('Gaia TAP returned an empty or invalid CSV response')
    return text, rows


def build(output, existing, magnitude_limit=7.5):
    if not math.isfinite(magnitude_limit) or not 0 < magnitude_limit <= 10:
        raise ValueError('Magnitude limit must be finite, positive and <=10 for this bright catalogue')
    output, existing = Path(output), Path(existing)
    raw_path = output.with_suffix('.gaia-source.csv')
    provenance_path = output.with_suffix('.provenance.json')
    for path in (output, raw_path, provenance_path):
        if path.exists() or path.resolve() == existing.resolve():
            raise FileExistsError(f'Catalogue products must be new files: {path}')
    selection = f'FROM gaiadr3.gaia_source WHERE phot_g_mean_mag <= {magnitude_limit:g}'
    _, count = fetch_csv('SELECT COUNT(*) AS n '+selection)
    expected = int(count[0]['n'])
    query = 'SELECT '+COLUMNS+' '+selection+' ORDER BY source_id'
    print(f'Downloading {expected} Gaia DR3 stars at G <= {magnitude_limit:g}', flush=True)
    raw_text, raw = fetch_csv(query)
    if len(raw) != expected:
        raise RuntimeError(f'Incomplete Gaia response: expected {expected}, got {len(raw)}')
    gaia = convert_rows(raw)
    with existing.open() as handle:
        old = list(csv.DictReader(handle))
    rows, supplement = supplement_bright(gaia, old)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw_text)
    with output.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)
    provenance = dict(release='Gaia DR3', endpoint=ENDPOINT, adql=query,
        retrieved_utc=datetime.now(timezone.utc).isoformat(), expected_gaia_rows=expected,
        gaia_rows=len(gaia), total_rows=len(rows), gaia_magnitude_passband='G',
        supplement_magnitude_passband='Tycho VT or Hipparcos V; see source IDs',
        proper_motion_rows=int(Catalogue.from_rows(rows).has_motion.sum()),
        quality_selection='None; all finite Gaia astrometry retained, including missing PM pairs',
        limitations='G and VT selections differ; Parallax, radial velocity and marginal errors are retained in raw data but not used by the seven-column model; full covariances are not fetched.',
        supplement=supplement, supplement_source=str(existing.resolve()),
        supplement_source_sha256=hashlib.sha256(existing.read_bytes()).hexdigest(),
        source_csv=raw_path.name, source_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        catalogue_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    provenance_path.write_text(json.dumps(provenance, indent=2)+'\n')
    print(f'Wrote {len(rows)} references ({len(gaia)} Gaia, {supplement["supplement_count"]} bright supplements): {output}', flush=True)
    return provenance
