"""Append-only recording: repeated images and unusable measurements survive."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from point_star_database import append_run


def products(root):
    root.mkdir(parents=True)
    (root/'dots').mkdir()
    (root/'result.json').write_text(json.dumps({
        'source_sha256': 'image-hash', 'catalogue_sha256': 'catalogue-hash',
        'solver_version': '0.9.0', 'status': 'point_star_fit_converged',
        'coordinate_epoch_jyear': 2000., 'metadata_used': False}))
    (root/'science_summary.json').write_text('{"stellar_epoch":{"status":"not_identifiable"}}')
    (root/'star_coordinates.csv').write_text(
        'detection_id,star_id,measured_ra_deg,saturated\n'
        '1,Gaia DR3 1234567890123456789,12.25,True\n'
        '2,HIP 42,13.5,False\n')
    (root/'stellar_photometry.csv').write_text(
        'detection_id,star_id,G_flux,G_mag,G1_flux,G2_flux,photometry_usable\n'
        '1,Gaia DR3 1234567890123456789,456,nan,220,236,False\n')
    (root/'dots/star_candidates.csv').write_text(
        'detection_id,x_px,source_class\n1,10,broad_blob\n2,20,compact\n3,30,compact\n')
    (root/'planet_candidates.csv').write_text('detection_id,planet\n3,Mars\n')
    (root/'report.pdf').write_bytes(b'%PDF fixture')


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root/'analysis'
        products(self.output)
        self.db = self.root/'index/stars.sqlite'
        self.image = self.root/'image.jpg'
        self.image.write_bytes(b'image')

    def record(self, **kwargs):
        return append_run(self.db, self.output, self.image, **kwargs)

    def test_identical_import_and_identical_image_always_append(self):
        one, two = self.record(), self.record()
        self.assertNotEqual(one, two)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM star_measurements').fetchone()[0], 4)

    def test_duplicate_payloads_are_stored_once_but_all_paths_and_rows_survive(self):
        import shutil
        shutil.copytree(self.output/'dots', self.output/'snapshot/dots')
        self.record()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='products'").fetchone(), ('view',))
            physical = db.execute('SELECT count(*), sum(length(content)) FROM product_content').fetchone()
            bodies = db.execute('SELECT count(*) FROM measurement_content').fetchone()[0]
        self.record()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*), sum(length(content)) FROM product_content').fetchone(), physical)
            self.assertEqual(db.execute('SELECT count(*) FROM measurement_content').fetchone()[0], bodies)
            self.assertEqual(db.execute('SELECT count(*) FROM products').fetchone()[0], 14)
            self.assertEqual(db.execute('SELECT count(*) FROM measurements').fetchone()[0], 20)
            self.assertEqual(db.execute("SELECT json_extract(values_json, '$.G1_flux') FROM measurements WHERE product='stellar_photometry.csv'").fetchall(), [('220',), ('220',)])

    def test_legacy_database_migrates_and_frozen_writer_still_appends(self):
        spec = importlib.util.spec_from_file_location('frozen_database', Path(__file__).parents[1]/'v10/point_star_database.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        legacy.append_run(self.db, self.output, self.image)
        with closing(sqlite3.connect(self.db)) as db:
            before = db.execute('SELECT * FROM products ORDER BY product').fetchall()
            rows = db.execute('SELECT * FROM measurements ORDER BY product, row_number').fetchall()
        self.record()
        legacy.append_run(self.db, self.output, self.image)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='products'").fetchone(), ('view',))
            self.assertEqual(db.execute('SELECT * FROM products WHERE run_id=? ORDER BY product', (before[0][0],)).fetchall(), before)
            after = db.execute('SELECT * FROM measurements WHERE run_id=? ORDER BY product,row_number', (before[0][0],)).fetchall()
            self.assertEqual([r[:5]+(json.loads(r[5]),) for r in after], [r[:5]+(json.loads(r[5]),) for r in rows])
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM star_measurements').fetchone()[0], 6)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_preserves_saturated_missing_photometry_unmatched_and_extra_channels(self):
        self.record()
        with closing(sqlite3.connect(self.db)) as db, db:
            rows = db.execute('SELECT star_id, astrometry_json, photometry_json, detection_json '
                              'FROM star_measurements ORDER BY star_id').fetchall()
            self.assertEqual(rows[0][0], 'Gaia DR3 1234567890123456789')
            self.assertEqual(json.loads(rows[0][1])['saturated'], 'True')
            photo = json.loads(rows[0][2])
            self.assertEqual((photo['G_mag'], photo['G1_flux'], photo['G2_flux']), ('nan', '220', '236'))
            self.assertEqual(json.loads(rows[0][3])['source_class'], 'broad_blob')
            self.assertIsNone(rows[1][2])
            self.assertEqual(db.execute("SELECT count(*) FROM measurements WHERE product='dots/star_candidates.csv'").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM measurements WHERE product='planet_candidates.csv'").fetchone()[0], 1)

    def test_evidence_bytes_checksums_and_scientific_status_are_preserved(self):
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.record()
        with closing(sqlite3.connect(self.db)) as db, db:
            for name, payload, digest in db.execute('SELECT product, content, sha256 FROM products'):
                self.assertEqual(payload, before[Path(name)])
                self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(db.execute('SELECT catalogue_sha256 FROM runs').fetchone()[0], 'catalogue-hash')
        self.assertEqual(before, {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_failed_run_without_solution_keeps_partial_products(self):
        self.output = self.root/'partial'
        (self.output/'dots').mkdir(parents=True)
        (self.output/'dots/detection.json').write_text('{"candidates":3}')
        self.record(exit_code=1, error='Too few stars')
        with closing(sqlite3.connect(self.db)) as db, db:
            row = db.execute('SELECT exit_code, error, source_sha256 FROM runs').fetchone()
            self.assertEqual(row, (1, 'Too few stars', hashlib.sha256(b'image').hexdigest()))
            self.assertEqual(db.execute('SELECT count(*) FROM products').fetchone()[0], 1)

    def test_failure_before_output_exists_is_recorded(self):
        self.output = self.root/'absent'
        self.record(exit_code=1, error='input failed')
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

    def test_foreign_database_is_rejected_without_changes(self):
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE other (value TEXT)')
        with self.assertRaisesRegex(ValueError, 'database'):
            self.record()
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('other',)])

    def test_concurrent_writers_append_every_run(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.record(), range(8)))
        self.assertEqual(len(set(ids)), 8)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 8)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_import_failure_rolls_back_without_damaging_previous_runs(self):
        self.record()
        (self.output/'broken.csv').write_bytes(b'\xff')
        with self.assertRaises(UnicodeDecodeError):
            self.record()
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

    def test_unknown_schema_is_rejected_and_existing_rows_survive(self):
        self.record()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.record()
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

    def test_migration_refuses_custom_trigger_without_losing_it(self):
        spec = importlib.util.spec_from_file_location('frozen_database', Path(__file__).parents[1]/'v10/point_star_database.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        legacy.append_run(self.db, self.output, self.image)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TRIGGER custom AFTER INSERT ON products BEGIN SELECT 1; END')
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.record()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='products'").fetchone(), ('table',))
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='custom'").fetchone()[0], 1)

    def test_migration_refuses_modified_public_view_without_replacing_it(self):
        spec = importlib.util.spec_from_file_location('frozen_database', Path(__file__).parents[1]/'v10/point_star_database.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        legacy.append_run(self.db, self.output, self.image)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DROP VIEW star_measurements')
            db.execute('CREATE VIEW star_measurements AS SELECT run_id, product FROM products')
            before = db.execute('SELECT * FROM star_measurements ORDER BY product').fetchall()
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.record()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT * FROM star_measurements ORDER BY product').fetchall(), before)
            self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='products'").fetchone(), ('table',))

    def test_compaction_reclaims_space_without_dropping_runs_or_measurements(self):
        from point_star_database import compact_database
        spec = importlib.util.spec_from_file_location('frozen_database', Path(__file__).parents[1]/'v10/point_star_database.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        (self.output/'large.txt').write_text('Repeated immutable diagnostic\n'*40000)
        for _ in range(3):
            legacy.append_run(self.db, self.output, self.image)
        stats = compact_database(self.db)
        self.assertLess(stats['after_bytes'], stats['before_bytes']/2)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM measurements').fetchone()[0], 21)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.record()

    def test_failed_import_rolls_back_legacy_migration_too(self):
        spec = importlib.util.spec_from_file_location('frozen_database', Path(__file__).parents[1]/'v10/point_star_database.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        legacy.append_run(self.db, self.output, self.image)
        (self.output/'broken.csv').write_bytes(b'\xff')
        with self.assertRaises(UnicodeDecodeError):
            self.record()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='products'").fetchone(), ('table',))
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

    def test_database_inside_analysis_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            append_run(self.output/'stars.sqlite', self.output, self.image)

    def test_main_records_on_success_and_on_scientific_failure(self):
        import analyse_image
        args = ['analyse', str(self.image), '--output', str(self.output), '--database', str(self.db)]
        with patch('sys.argv', args), patch.object(analyse_image, 'analyse'):
            analyse_image.main()
        with patch('sys.argv', args), patch.object(analyse_image, 'analyse', side_effect=RuntimeError('fit failed')):
            with self.assertRaisesRegex(RuntimeError, 'fit failed'):
                analyse_image.main()
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT exit_code FROM runs ORDER BY rowid').fetchall(), [(0,), (1,)])

    def test_database_failure_is_not_reported_as_solver_success(self):
        import analyse_image
        args = ['analyse', str(self.image), '--output', str(self.output), '--database', str(self.db)]
        with patch('sys.argv', args), patch.object(analyse_image, 'analyse'), \
                patch('point_star_database.append_run', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'disk full'):
                analyse_image.main()


if __name__ == '__main__':
    unittest.main()
