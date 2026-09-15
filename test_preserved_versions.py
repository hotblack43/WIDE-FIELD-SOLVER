"""Keep the legacy runtime and the initial v4 package complete and separate."""
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
                                 'Legacy runtime changed: develop upgrades under v4/')

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


if __name__ == '__main__':
    unittest.main()
