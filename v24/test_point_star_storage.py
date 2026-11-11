"""Lossless, recoverable storage changes without touching final science files."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import point_star_database
from test_point_star_database import products


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.analysis = self.root/'analysis'
        products(self.analysis)
        (self.analysis/'joint_epoch.json').write_text('{"adopted":true}')
        for name in ('joint_candidate_solution', 'stellar_only_products'):
            folder = self.analysis/name
            folder.mkdir()
            (folder/'evidence.json').write_bytes(b'{"padding":"'+b'x'*200000+b'"}\n')
            (folder/'rows.csv').write_bytes(b'detection_id,star_id,flux\n1,HIP 42,nan\n')
            (folder/'image.npz').write_bytes(b'\x00\xffbinary evidence')
        self.original = {p.relative_to(self.analysis).as_posix():p.read_bytes()
                         for p in self.analysis.rglob('*') if p.is_file()}
        self.db = self.root/'stars.sqlite'
        self.image = self.root/'source.jpg'
        self.image.write_bytes(b'image')

    def archive(self):
        # Explicit assertion gives a useful RED before the module exists.
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('point_star_storage'), 'archive helper is not implemented')
        from point_star_storage import archive_intermediates
        return archive_intermediates(self.analysis)

    def test_archive_roundtrip_keeps_final_files_and_reimported_evidence(self):
        one = point_star_database.append_run(self.db, self.analysis, self.image)
        stats = self.archive()
        self.assertLess(stats['after_bytes'], stats['before_bytes']/5)
        archive = self.analysis/'intermediate_products.zip'
        with zipfile.ZipFile(archive) as zipped:
            for name, content in self.original.items():
                if name.startswith(('joint_candidate_solution/', 'stellar_only_products/')):
                    self.assertEqual(zipped.read(name), content)
                    self.assertFalse((self.analysis/name).exists())
                else:
                    self.assertEqual((self.analysis/name).read_bytes(), content)
        two = point_star_database.append_run(self.db, self.analysis, self.image)
        with closing(sqlite3.connect(self.db)) as db:
            for table, order in [('products','product'), ('measurements','product,row_number')]:
                a = db.execute(f'SELECT * FROM {table} WHERE run_id=? ORDER BY {order}', (one,)).fetchall()
                b = db.execute(f'SELECT * FROM {table} WHERE run_id=? ORDER BY {order}', (two,)).fetchall()
                self.assertEqual([r[1:] for r in a], [r[1:] for r in b])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.archive()
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)

    def test_unadopted_staging_is_left_loose(self):
        (self.analysis/'joint_epoch.json').write_text('{"adopted":false}')
        self.archive()
        self.assertTrue((self.analysis/'joint_candidate_solution/evidence.json').exists())
        self.assertFalse((self.analysis/'intermediate_products.zip').exists())

    def test_failed_archive_keeps_every_original(self):
        # Disk failure is the external boundary; all archive logic stays real.
        with patch.object(zipfile.ZipFile, 'write', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.archive()
        for name, data in self.original.items():
            self.assertEqual((self.analysis/name).read_bytes(), data)
        self.assertFalse((self.analysis/'intermediate_products.zip').exists())

    def test_symlink_is_not_followed_or_deleted(self):
        outside = self.root/'outside.txt'
        outside.write_text('outside')
        link = self.analysis/'joint_candidate_solution/link.txt'
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.archive()
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_text(), 'outside')

    def test_main_archives_only_after_successful_recording(self):
        import analyse_image
        args = ['analyse', str(self.image), '--output', str(self.analysis), '--database', str(self.db)]
        with patch('sys.argv', args), patch.object(analyse_image, 'analyse'):
            analyse_image.main()
        self.assertTrue((self.analysis/'intermediate_products.zip').exists())
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM products WHERE product='joint_candidate_solution/evidence.json'").fetchone()[0], 1)

    def test_science_failure_does_not_archive(self):
        import analyse_image
        args = ['analyse', str(self.image), '--output', str(self.analysis), '--database', str(self.db)]
        with patch('sys.argv', args), patch.object(analyse_image, 'analyse', side_effect=RuntimeError('fit failed')):
            with self.assertRaisesRegex(RuntimeError, 'fit failed'):
                analyse_image.main()
        self.assertFalse((self.analysis/'intermediate_products.zip').exists())
        self.assertTrue((self.analysis/'joint_candidate_solution/evidence.json').is_file())

    def test_archive_failure_does_not_change_successful_run(self):
        import analyse_image
        args = ['analyse', str(self.image), '--output', str(self.analysis), '--database', str(self.db)]
        with patch('sys.argv', args), patch.object(analyse_image, 'analyse'), \
                patch.object(zipfile.ZipFile, 'write', side_effect=OSError('disk full')):
            analyse_image.main()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT exit_code FROM runs').fetchall(), [(0,)])
        self.assertTrue((self.analysis/'joint_candidate_solution/evidence.json').is_file())

    def test_interrupted_cleanup_resumes_and_conflicting_loose_file_is_refused(self):
        original_unlink = Path.unlink
        def fail_evidence(path, *args, **kwargs):
            if path.name == 'evidence.json':
                raise OSError('interrupted cleanup')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_evidence):
            with self.assertRaisesRegex(OSError, 'interrupted cleanup'):
                self.archive()
        self.assertTrue((self.analysis/'intermediate_products.zip').exists())
        self.archive()
        folder = self.analysis/'joint_candidate_solution'
        folder.mkdir()
        (folder/'evidence.json').write_text('different')
        with self.assertRaisesRegex(ValueError, 'verification'):
            self.archive()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            point_star_database.append_run(self.db, self.analysis, self.image)
        self.assertEqual((folder/'evidence.json').read_text(), 'different')


if __name__ == '__main__':
    unittest.main()
