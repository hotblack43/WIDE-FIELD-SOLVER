"""Exercise real fitting/export; only pixel detection and blind bootstrap are supplied."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from point_star_barghini import run, vectors
from point_star_report import _camera_from_result
from test_point_star_epoch import moving_field


class EpochIntegrationTests(unittest.TestCase):
    def test_new_run_refuses_to_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root/'existing'
            output.mkdir()
            sentinel = output/'important.txt'
            sentinel.write_text('preserve')
            source = root/'blank.png'
            Image.new('RGB', (100, 100)).save(source)
            with self.assertRaises(FileExistsError):
                run(source, output, root/'unused.csv')
            self.assertEqual(sentinel.read_text(), 'preserve')

    def test_saved_solution_uses_propagated_positions_and_final_camera(self):
        initial, xy, rows, target = moving_field(motion_scale=700., noise=.0005)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'image.png'
            Image.new('RGB', (1000, 800)).save(source)
            catalog = root/'stars.csv'
            with catalog.open('w') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)

            def detected(image, output):
                output.mkdir(parents=True)
                with (output/'star_candidates.csv').open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=['detection_id', 'x_px', 'y_px', 'source_class', 'saturated'])
                    writer.writeheader()
                    for i, (x, y) in enumerate(xy):
                        writer.writerow(dict(detection_id=i, x_px=x, y_px=y,
                                             source_class='compact', saturated=i == 0))
                return dict(height_px=800, width_px=1000,
                            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())

            output = root/'new-solution'
            with patch('point_star_barghini.write_products', side_effect=detected), \
                 patch('point_star_barghini.bootstrap', return_value=(initial, {'method': 'synthetic test fixture'})):
                result = run(source, output, catalog, offline=True, label_count=4,
                             epoch_mode='fixed', epoch_year=2060.)
            saved = json.loads((output/'result.json').read_text())
            with (output/'star_coordinates.csv').open() as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual(saved['stellar_epoch']['applied_epoch_jyear'], 2060.)
            self.assertEqual(saved['stellar_epoch']['fitted_count'], len(exported))
            self.assertEqual(saved['withheld_stars'], 0)
            saturated = [row for row in exported if row['saturated'] == 'True']
            self.assertEqual(len(saturated), 1)
            self.assertEqual(saturated[0]['detection_id'], '0')
            self.assertIn('fit', saturated[0]['usage'])
            self.assertEqual(saved['solver_version'], '0.4.3')
            camera = _camera_from_result(saved)
            propagated = vectors([float(r['propagated_ra_deg']) for r in exported],
                                 [float(r['propagated_dec_deg']) for r in exported])
            ids = np.array([int(r['star_id']) for r in exported])
            np.testing.assert_allclose(propagated, target[ids], atol=1e-9, rtol=0)
            prediction = camera.project(propagated)
            stored = np.array([[float(r['predicted_x_px']), float(r['predicted_y_px'])] for r in exported])
            measured = np.array([[float(r['x_px']), float(r['y_px'])] for r in exported])
            np.testing.assert_allclose(prediction, stored, atol=1e-7, rtol=0)
            np.testing.assert_allclose(measured, xy[ids], atol=1e-12, rtol=0)
            np.testing.assert_allclose(np.linalg.norm(prediction-measured, axis=1),
                                       [float(r['residual_px']) for r in exported], atol=1e-7)
            self.assertLess(result['fit']['rms_px'], .003)
            for r in exported:
                self.assertEqual(r['catalog_ra_deg'], rows[int(r['star_id'])]['ra_deg'])
                self.assertEqual(float(r['coordinate_epoch_jyear']), 2060.)
            self.assertTrue((output/'stellar_epoch_profile.png').is_file())
            self.assertEqual(json.loads((output/'stellar_epoch.json').read_text()), saved['stellar_epoch'])

    def test_science_reuses_integrated_epoch_without_refitting(self):
        from point_star_science import fit_stellar_epoch
        expected = dict(status='supplied_epoch', epoch_jyear=2026., applied_epoch_jyear=2026.,
                        fitted_count=80, withheld_count=0, profile=[])
        with tempfile.TemporaryDirectory() as tmp:
            result = fit_stellar_epoch(Path(tmp), {'stellar_epoch': expected}, Path(tmp)/'unused.csv')
        self.assertEqual(result, expected)

    def test_report_distinguishes_supplied_and_unresolved_epochs(self):
        from point_star_report import report_sections
        from test_point_star_report import ReportTests
        result = ReportTests().sample_result()
        fixed = dict(status='supplied_epoch', epoch_jyear=2026., applied_epoch_jyear=2026., fitted_count=80)
        text = report_sections(dict(result, stellar_epoch=fixed))['astrometry']
        self.assertIn('supplied', text.lower())
        self.assertNotIn('withheld', text.lower())
        unresolved = dict(status='not_identifiable', epoch_jyear=None, best_epoch_jyear=2010.,
                          applied_epoch_jyear=2000., boundary_limited=False)
        text = report_sections(dict(result, stellar_epoch=unresolved))['astrometry']
        self.assertIn('unresolved', text.lower())
        self.assertNotIn('boundary', text.lower())

    def test_overwrite_cannot_remove_input_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'image.png'
            Image.new('RGB', (100, 100)).save(source)
            with self.assertRaises(ValueError):
                run(source, root, root/'catalog.csv', overwrite=True)
            self.assertTrue(source.is_file())

    def test_overwrite_cannot_remove_historical_assets(self):
        from point_star_barghini import prepare_output
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'repo'
            for directory in ('examples/milky_way/reference', 'data'):
                preserved = root/directory
                preserved.mkdir(parents=True)
                sentinel = preserved/'evidence.txt'
                sentinel.write_text('preserve')
                with patch('point_star_barghini.__file__', str(root/'point_star_barghini.py')):
                    with self.assertRaises(ValueError):
                        prepare_output(preserved, overwrite=True)
                self.assertEqual(sentinel.read_text(), 'preserve')
