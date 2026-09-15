"""Keep the legacy runtime, preserved v4 and active v5 complete and separate."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class PreservedVersionTests(unittest.TestCase):
    def test_legacy_runtime_still_matches_pre_gaia_snapshot(self):
        record = json.loads((ROOT/'docs/legacy-runtime.json').read_text())
        for name, expected in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected,
                                 'Legacy runtime changed: develop upgrades under v5/')

    def test_v4_runtime_and_launchers_match_release_checkpoint(self):
        record = json.loads((ROOT/'docs/v4-runtime.json').read_text())
        self.assertEqual(record['preserved_commit'],
                         'd8ca43891d9943e17c27ad56cdecb299df3cf1d5')
        source = json.loads((ROOT/'v4/SOURCE_MANIFEST.json').read_text())
        expected_files = {'v4/' + name for name in source['sha256'] | source['packaging_sha256']}
        expected_files.update({'v4/SOURCE_MANIFEST.json', 'go4.sh', 'go_v0.4.3.sh'})
        self.assertEqual(set(record['sha256']), expected_files)
        for name, expected in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected,
                                 'Preserved v4 changed: develop upgrades under v5/')

    def test_v4_snapshot_is_complete(self):
        record = json.loads((ROOT/'v4/SOURCE_MANIFEST.json').read_text())
        files = record['sha256'] | record['packaging_sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v4'/name).read_bytes()).hexdigest(), expected)
        # Runtime files must not escape the preservation record. Generated
        # outputs and environments are deliberately outside this inventory.
        runtime = {p.name for p in (ROOT/'v4').iterdir()
                   if p.is_file() and p.suffix in ('.py', '.sh')}
        self.assertEqual(runtime, {name for name in files
                                  if '/' not in name and Path(name).suffix in ('.py', '.sh')})


    def test_v5_manifest_covers_runtime_and_packaged_data(self):
        record = json.loads((ROOT/'v5/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(record['version'], '0.5.0')
        self.assertEqual(record['based_on_tag'], 'v0.4.3')
        files = record['sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v5'/name).read_bytes()).hexdigest(), expected)
        runtime = {p.name for p in (ROOT/'v5').iterdir()
                   if p.is_file() and p.suffix in ('.py', '.sh')}
        self.assertEqual(runtime, {name for name in files
                                  if '/' not in name and Path(name).suffix in ('.py', '.sh')})
        parent = json.loads((ROOT/'v4/SOURCE_MANIFEST.json').read_text())
        self.assertTrue(set(parent['sha256'] | parent['packaging_sha256']).issubset(files))


if __name__ == '__main__':
    unittest.main()
