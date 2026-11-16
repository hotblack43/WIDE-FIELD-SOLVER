"""The release check must actually reject regression, including NaN scores."""
import copy
import csv
import json
from pathlib import Path
import unittest

from scripts.check_demo import check_result, check_coordinates


class DemoChecksTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent
        self.baseline = json.loads((root/'examples/milky_way/baseline.json').read_text())
        self.labels = json.loads((root/'examples/milky_way/reference/labelled_stars.json').read_text())['stars']
        self.result = dict(
            source_sha256=self.baseline['source_sha256'],
            catalogue_sha256=self.baseline['catalogue_sha256'],
            status='point_star_fit_converged', metadata_used=False, trails_used=False,
            withheld_stars=0, detection_count=3688, broad_or_saturated_objects=962,
            camera=dict(monotonic_on_detector=True, shape=[1444, 1569]),
            fit=dict(count=3653, rms_px=.398, median_px=.249, p90_px=.606))

    def test_accepts_known_baseline(self):
        self.assertEqual(check_result(self.result, self.labels, self.baseline), [])

    def test_rejects_bad_fit_nan_and_withholding(self):
        for key, value in [('rms_px', 2.), ('rms_px', float('nan')), ('count', 100)]:
            result = copy.deepcopy(self.result)
            result['fit'][key] = value
            self.assertTrue(check_result(result, self.labels, self.baseline))
        self.result['withheld_stars'] = 1
        self.assertTrue(check_result(self.result, self.labels, self.baseline))

    def test_rejects_clustered_labels_and_changed_input(self):
        labels = [dict(r, x_px=10., y_px=10.) for r in self.labels]
        self.assertTrue(check_result(self.result, labels, self.baseline))
        self.result['source_sha256'] = 'changed'
        self.assertTrue(check_result(self.result, self.labels, self.baseline))

    def test_checks_exported_camera_and_coordinates(self):
        reference = Path(__file__).parent/'examples/milky_way/reference'
        result = json.loads((reference/'result.json').read_text())
        with (reference/'star_coordinates.csv').open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(check_coordinates(result, rows, rows, self.baseline), [])
        changed = copy.deepcopy(result)
        changed['camera']['reference_rotation'] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assertTrue(check_coordinates(changed, rows, rows, self.baseline))
        bad_rows = [dict(r, predicted_x_px=float(r['predicted_x_px'])+1) for r in rows]
        self.assertTrue(check_coordinates(result, bad_rows, rows, self.baseline))
        wrong_ids = [dict(r, star_id='wrong') for r in rows]
        self.assertTrue(check_coordinates(result, wrong_ids, rows, self.baseline))
