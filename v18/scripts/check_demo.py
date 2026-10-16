"""Check a newly computed example against the preserved numerical baseline."""
import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))


def check_result(result, labels, baseline):
    limits = baseline['acceptance']
    fit = result['fit']
    h, w = result['camera']['shape']
    checks = {
        'original image checksum': result['source_sha256'] == baseline['source_sha256'],
        'frozen catalogue checksum': result['catalogue_sha256'] == baseline['catalogue_sha256'],
        'converged fit': result['status'] == 'point_star_fit_converged',
        'monotonic radial model': result['camera']['monotonic_on_detector'] is True,
        'no metadata or trails': result['metadata_used'] is False and result['trails_used'] is False,
        'no withheld stars': result['withheld_stars'] == 0,
        'detection count': result['detection_count'] >= limits['minimum_detections'],
        'association count': fit['count'] >= limits['minimum_associated_stars'],
        'RMS residual': 0 <= fit['rms_px'] <= limits['maximum_rms_px'],
        'median residual': 0 <= fit['median_px'] <= limits['maximum_median_px'],
        '90th percentile residual': 0 <= fit['p90_px'] <= limits['maximum_p90_px'],
        'large/saturated objects retained': result['broad_or_saturated_objects'] >= limits['minimum_broad_or_saturated_objects'],
        'unique star labels': len(labels) == len({r['star_id'] for r in labels}) == limits['label_count'],
    }
    for key, extent in [('x_px', w), ('y_px', h)]:
        span = max((float(r[key]) for r in labels), default=0)-min((float(r[key]) for r in labels), default=0)
        checks[f'label coverage {key}'] = span/extent >= limits['minimum_label_span_fraction']
    return [name for name, passed in checks.items() if not passed]


def check_coordinates(result, rows, reference, baseline):
    from point_star_barghini import BarghiniCamera, stats, vectors
    if not rows:
        return ['empty coordinate table']
    saved = result['camera']
    camera = BarghiniCamera.from_serialised(saved)
    sky = vectors([float(r['catalog_ra_deg']) for r in rows],
                  [float(r['catalog_dec_deg']) for r in rows])
    measured = np.array([[float(r['x_px']), float(r['y_px'])] for r in rows])
    stored = np.array([[float(r['predicted_x_px']), float(r['predicted_y_px'])] for r in rows])
    prediction = camera.project(sky)
    score = stats(prediction-measured)
    key = lambda row: (str(row['detection_id']), row['star_id'])
    previous = {key(r): r for r in reference}
    shared = [r for r in rows if key(r) in previous]
    checks = {
        'saved camera reproduces coordinates': np.allclose(prediction, stored, atol=.001, rtol=0),
        'exported association count': len(rows) == result['fit']['count'],
        'exclusive associations': len({r['detection_id'] for r in rows}) == len({r['star_id'] for r in rows}) == len(rows),
        'preserved catalogue identities': len(shared) >= baseline['acceptance']['minimum_associated_stars'],
        'saved radial model is monotonic': camera.is_monotonic(),
        'physical parameter export': all(np.isclose(value, saved['parameters'][name], rtol=1e-10, atol=1e-12)
                                         for name, value in asdict(camera.physical).items()),
    }
    for name in ('rms_px', 'median_px', 'p90_px'):
        checks[f'recomputed {name}'] = bool(np.isclose(score[name], result['fit'][name], atol=1e-6, rtol=0))
    for name, tolerance in [('x_px', .05), ('y_px', .05), ('catalog_ra_deg', 1e-6), ('catalog_dec_deg', 1e-6)]:
        checks[f'preserved {name}'] = all(abs(float(r[name])-float(previous[key(r)][name])) <= tolerance for r in shared)
    return [name for name, passed in checks.items() if not passed]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = json.loads((args.output/'result.json').read_text())
    labels = json.loads((args.output/'labelled_stars.json').read_text())['stars']
    baseline = json.loads((ROOT/'examples/milky_way/baseline.json').read_text())
    failures = check_result(result, labels, baseline)
    with (args.output/'star_coordinates.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    with (ROOT/'examples/milky_way/reference/star_coordinates.csv').open() as handle:
        reference = list(csv.DictReader(handle))
    failures.extend(check_coordinates(result, rows, reference, baseline))
    if failures:
        raise SystemExit('Baseline FAILED: '+', '.join(failures))
    print(f"Baseline PASS: {result['fit']['count']} associations, "
          f"RMS {result['fit']['rms_px']:.6f} px, {len(labels)} distributed labels")


if __name__ == '__main__':
    main()
