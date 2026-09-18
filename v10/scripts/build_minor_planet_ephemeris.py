#!/usr/bin/env python3
"""Build the offline Ceres/Vesta reference from NASA/JPL Horizons.

Network access is a release-time operation only. Runtime uses the committed NPZ.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np
import requests


API = 'https://ssd.jpl.nasa.gov/api/horizons.api'
TARGETS = {'ceres': '1;', 'vesta': '4;'}
CHUNK_DAYS = 8000


def _query(session, params):
    quoted = {key: (value if key == 'format' else f"'{value}'")
              for key, value in params.items()}
    for attempt in range(5):
        response = session.get(API, params=quoted, timeout=180)
        if response.ok and '$$SOE' in response.text:
            return response.text
        if attempt == 4:
            response.raise_for_status()
            raise RuntimeError(response.text[:1000])
        time.sleep(2**attempt)


def _rows(text):
    body = text.split('$$SOE', 1)[1].split('$$EOE', 1)[0]
    return [[item.strip() for item in row]
            for row in csv.reader(io.StringIO(body)) if row]


def _common(command):
    return dict(format='text', COMMAND=command, OBJ_DATA='NO', MAKE_EPHEM='YES',
                CENTER='500@399', CSV_FORMAT='YES')


def _time_params(dates):
    if len(dates) == 1:
        return dict(TLIST=f'{dates[0]:.9f}', TLIST_TYPE='JD')
    expected = dates[0] + np.arange(len(dates), dtype=float)
    if not np.array_equal(dates, expected):
        raise ValueError('A multi-date Horizons request must have a one-day grid')
    return dict(START_TIME=f'JD{dates[0]:.9f}', STOP_TIME=f'JD{dates[-1]:.9f}',
                STEP_SIZE='1 d')


def query_vectors(session, command, dates):
    params = _common(command)
    params.update(EPHEM_TYPE='VECTORS', TIME_TYPE='TDB', REF_SYSTEM='ICRF',
                  REF_PLANE='FRAME', VEC_CORR='LT+S', VEC_TABLE='1',
                  OUT_UNITS='AU-D', **_time_params(dates))
    rows = _rows(_query(session, params))
    returned = np.array([float(row[0]) for row in rows])
    xyz = np.array([[float(value) for value in row[2:5]] for row in rows])
    np.testing.assert_allclose(returned, dates, rtol=0, atol=5e-10)
    return xyz/np.linalg.norm(xyz, axis=1)[:, None]


def query_magnitudes(session, command, dates):
    params = _common(command)
    params.update(EPHEM_TYPE='OBSERVER', TIME_TYPE='TT', QUANTITIES='9',
                  CAL_FORMAT='JD', **_time_params(dates))
    rows = _rows(_query(session, params))
    returned = np.array([float(row[0]) for row in rows])
    magnitude = np.array([float(row[3]) for row in rows])
    np.testing.assert_allclose(returned, dates, rtol=0, atol=5e-10)
    return magnitude


def _digest(jd, arrays):
    digest = hashlib.sha256()
    for name, values in [('jd_tdb', jd), *sorted(arrays.items())]:
        digest.update(name.encode('ascii'))
        digest.update(np.asarray(values, dtype='<f8').tobytes())
    return digest.hexdigest()


def build(output, major_reference):
    with np.load(major_reference, allow_pickle=False) as source:
        jd = np.asarray(source['jd_tdb'], dtype=float)
    arrays = {}
    session = requests.Session()
    daily_count = len(jd)-1 if jd[-1]-jd[-2] != 1. else len(jd)
    for name, command in TARGETS.items():
        vectors = np.empty((len(jd), 3), float)
        magnitudes = np.empty(len(jd), float)
        for begin in range(0, daily_count, CHUNK_DAYS):
            end = min(begin+CHUNK_DAYS, daily_count)
            dates = jd[begin:end]
            print(f'{name}: {begin:,}-{end:,}/{len(jd):,}', flush=True)
            vectors[begin:end] = query_vectors(session, command, dates)
            magnitudes[begin:end] = query_magnitudes(session, command, dates)
        if daily_count < len(jd):
            vectors[-1:] = query_vectors(session, command, jd[-1:])
            magnitudes[-1:] = query_magnitudes(session, command, jd[-1:])
        arrays[name] = vectors
        arrays[f'{name}_v_mag'] = magnitudes
    provenance = dict(
        schema_version=1, authority='JPL Horizons', api=API,
        targets={'ceres': '1;', 'vesta': '4;'},
        target_solutions={'ceres': 'JPL#48', 'vesta': 'JPL#36'},
        observer='Earth geocenter', frame='ICRF', time_scale='TDB',
        vector_corrections='LT+S', vector_units='normalized direction',
        brightness='Horizons quantity 9 APmag, standard IAU H-G model',
        brightness_time_scale='TT (numerically sampled at the TDB grid JDs)',
        start_jd_tdb=float(jd[0]), end_jd_tdb=float(jd[-1]),
        samples=len(jd), step_days=1., includes_fractional_final_endpoint=True,
        runtime_network_required=False,
        limitation=('Daily cubic interpolation is used at runtime; brightness is approximate '
                    'visual magnitude and is not a camera-band calibration.'))
    provenance['content_sha256'] = _digest(jd, arrays)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, jd_tdb=jd,
                        provenance=np.asarray(json.dumps(provenance, sort_keys=True)),
                        **arrays)
    print(json.dumps({**provenance, 'path': str(output),
                      'bytes': output.stat().st_size}, indent=2))


def verify(path):
    with np.load(path, allow_pickle=False) as data:
        provenance = json.loads(str(data['provenance']))
        jd = data['jd_tdb']
        arrays = {name: data[name] for name in
                  ('ceres', 'ceres_v_mag', 'vesta', 'vesta_v_mag')}
    if provenance['content_sha256'] != _digest(jd, arrays):
        raise ValueError('Minor-planet reference digest mismatch')
    for name in ('ceres', 'vesta'):
        if arrays[name].shape != (len(jd), 3):
            raise ValueError(f'{name} track has the wrong shape')
        np.testing.assert_allclose(np.linalg.norm(arrays[name], axis=1), 1., atol=1e-12)
    print(json.dumps(provenance, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1]/'data/minor-planet-reference-1850-2036.npz')
    parser.add_argument('--major-reference', type=Path,
                        default=Path(__file__).resolve().parents[1]/'data/planet-reference-1850-2036.npz')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    verify(args.verify) if args.verify else build(args.output, args.major_reference)


if __name__ == '__main__':
    main()
