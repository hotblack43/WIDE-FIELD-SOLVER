#!/usr/bin/env python3
"""Benchmark isolated v5/v6 planet stages on copies of one fitted analysis."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]


def timing_summary(v5_seconds, v6_seconds):
    v5 = [float(value) for value in v5_seconds]
    v6 = [float(value) for value in v6_seconds]
    if not v5 or not v6 or min(v5+v6) <= 0:
        raise ValueError('Benchmark timings must be nonempty and positive')
    v5_median = float(statistics.median(v5))
    v6_median = float(statistics.median(v6))
    return {'v5_seconds': v5, 'v6_seconds': v6,
            'v5_median_seconds': v5_median,
            'v6_median_seconds': v6_median,
            'speedup_ratio': v5_median/v6_median}


def _identities(answer):
    return [tuple((row['planet'], int(row['detection_id']))
                  for row in candidate.get('matches', []))
            for candidate in answer.get('candidates', [])]


def compare_science(v5, v6, *, epoch_tolerance_seconds=.25,
                    residual_tolerance_px=1e-6):
    reasons = []
    science_fields = (
        'status', 'confidence', 'reason', 'refined_visit_count',
        'joint_trial_count', 'match_count', 'candidate_count',
        'competing_candidates', 'matches', 'candidates', 'source_candidates',
        'visibility', 'visibility_sources', 'negative_evidence',
        'source_identity_alternatives', 'predicted_planets',
        '_benchmark_products')

    def compare(left, right, path='answer'):
        key = path.rsplit('.', 1)[-1]
        if isinstance(left, dict) and isinstance(right, dict):
            if set(left) != set(right):
                reasons.append(f'{path} fields differ')
                return
            for child in sorted(left):
                if child.endswith('epoch_tdb'):
                    continue
                compare(left[child], right[child], f'{path}.{child}')
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                reasons.append(f'{path} length differs')
                return
            for index, (a, b) in enumerate(zip(left, right)):
                compare(a, b, f'{path}[{index}]')
        elif (isinstance(left, int) and not isinstance(left, bool)
              and isinstance(right, int) and not isinstance(right, bool)):
            if left != right:
                reasons.append(f'{path} differs')
        elif (isinstance(left, (int, float)) and not isinstance(left, bool)
              and isinstance(right, (int, float)) and not isinstance(right, bool)):
            tolerance = (epoch_tolerance_seconds/86400. if 'jd_tdb' in key
                         else residual_tolerance_px)
            if abs(float(left)-float(right)) > tolerance:
                reasons.append(f'{path} differs')
        elif left != right:
            reasons.append(f'{path} differs')

    for key in science_fields:
        if key in v5 or key in v6:
            compare(v5.get(key), v6.get(key), key)
    left, right = v5.get('candidates', []), v6.get('candidates', [])
    if len(left) != len(right):
        reasons.append('candidate count differs')
    if _identities(v5) != _identities(v6) and 'candidate identities differ' not in reasons:
        reasons.append('candidate identities differ')
    pairs = list(zip(left, right))
    epoch = [abs(float(a['jd_tdb'])-float(b['jd_tdb']))*86400. for a, b in pairs]
    residual = [abs(float(a['rms_px'])-float(b['rms_px'])) for a, b in pairs]
    max_epoch = max(epoch, default=0.)
    max_residual = max(residual, default=0.)
    if max_epoch > epoch_tolerance_seconds:
        reasons.append('candidate epoch difference exceeds tolerance')
    if max_residual > residual_tolerance_px:
        reasons.append('candidate residual difference exceeds tolerance')
    reasons = list(dict.fromkeys(reasons))
    return {'equivalent': not reasons, 'reasons': reasons,
            'max_epoch_difference_seconds': max_epoch,
            'max_rms_difference_px': max_residual,
            'candidate_count_v5': len(left), 'candidate_count_v6': len(right)}


def _run(version, analysis, image, workers):
    interpreter = ROOT/version/'.venv/bin/python'
    if not interpreter.is_file():
        raise ValueError(f'Missing locked interpreter: {interpreter}')
    with tempfile.TemporaryDirectory(prefix=f'wfs-{version}-benchmark-') as temporary:
        destination = Path(temporary)/'analysis'
        shutil.copytree(analysis, destination)
        code = (
            "import json,pathlib; from point_star_planets import fit_blind_planet_epoch; "
            f"p=pathlib.Path({str(destination)!r}); "
            "r=json.loads((p/'result.json').read_text()); "
            f"fit_blind_planet_epoch({str(image)!r},p,r)")
        environment = os.environ.copy()
        if version == 'v6':
            environment['WFS_PLANET_WORKERS'] = str(workers)
        started = time.perf_counter()
        completed = subprocess.run(
            [str(interpreter), '-c', code], cwd=ROOT/version,
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True)
        elapsed = time.perf_counter()-started
        if completed.returncode:
            raise RuntimeError(f'{version} benchmark failed: {completed.stderr}')
        answer = json.loads((destination/'planet_epoch.json').read_text())
        products = {}
        for filename in ('planet_candidates.csv', 'planet_source_candidates.csv',
                         'planet_visibility.csv'):
            with (destination/filename).open(newline='') as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                for key, value in list(row.items()):
                    if key.endswith('epoch_tdb'):
                        row.pop(key)
                    elif value == '':
                        row[key] = None
                    else:
                        try:
                            row[key] = float(value)
                        except ValueError:
                            pass
            products[filename] = rows
        products['planet_non_detections.json'] = json.loads(
            (destination/'planet_non_detections.json').read_text())
        answer['_benchmark_products'] = products
    return elapsed, answer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v5-analysis', type=Path, required=True)
    parser.add_argument('--v6-analysis', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--json', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.repetitions <= 0 or args.workers <= 0:
        parser.error('repetitions and workers must be positive')
    timings = {'v5': [], 'v6': []}
    answers = {'v5': [], 'v6': []}
    for version, analysis in (('v5', args.v5_analysis), ('v6', args.v6_analysis)):
        for _ in range(args.repetitions):
            elapsed, answer = _run(version, analysis, args.image.resolve(), args.workers)
            timings[version].append(elapsed)
            answers[version].append(answer)
    comparisons = []
    for index in range(args.repetitions):
        comparisons.append(compare_science(answers['v5'][index], answers['v6'][index]))
    for version in ('v5', 'v6'):
        for index in range(1, args.repetitions):
            comparison = compare_science(answers[version][0], answers[version][index])
            comparison.update(kind='repeatability', version=version,
                              left_repetition=1, right_repetition=index+1)
            comparisons.append(comparison)
    science = {
        'equivalent': all(row['equivalent'] for row in comparisons),
        'repetitions': comparisons,
        'max_epoch_difference_seconds': max(
            (row['max_epoch_difference_seconds'] for row in comparisons), default=0.),
        'max_rms_difference_px': max(
            (row['max_rms_difference_px'] for row in comparisons), default=0.),
    }
    record = {
        'schema_version': 1,
        'machine': {'platform': platform.platform(), 'processor': platform.processor(),
                    'cpu_count': os.cpu_count()},
        'repetitions': args.repetitions,
        'v6_workers': args.workers,
        'timing': timing_summary(timings['v5'], timings['v6']),
        'cache_states': {version: [answer.get('planet_search_performance', {}).get('cache', {})
                                  for answer in values]
                         for version, values in answers.items()},
        'science': science,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n')
    print(json.dumps(record, indent=2, allow_nan=False))
    return 0 if record['science']['equivalent'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
