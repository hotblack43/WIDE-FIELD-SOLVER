"""Keep the legacy through v7 runtimes separate from active v8 development."""
import hashlib
import json
from pathlib import Path
import subprocess
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

    def test_v5_runtime_and_launchers_match_v6_parent_checkpoint(self):
        record = json.loads((ROOT/'docs/v5-runtime.json').read_text())
        self.assertEqual(record['preserved_commit'],
                         '27455801694a5e8d1338335f93d4e66d8410fc24')
        self.assertEqual(record['version'], '0.5.0')
        for name, expected in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected,
                                 'Preserved v5 changed: develop upgrades under v6/')

    def test_v6_manifest_covers_runtime_and_packaged_data(self):
        record = json.loads((ROOT/'v6/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(record['version'], '0.6.0')
        self.assertEqual(record['based_on_commit'],
                         '27455801694a5e8d1338335f93d4e66d8410fc24')
        files = record['sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v6'/name).read_bytes()).hexdigest(), expected)
        runtime = {p.name for p in (ROOT/'v6').iterdir()
                   if p.is_file() and p.suffix in ('.py', '.sh')}
        self.assertEqual(runtime, {name for name in files
                                  if '/' not in name and Path(name).suffix in ('.py', '.sh')})

    def test_v6_manifest_files_are_tracked_for_clean_exports(self):
        record = json.loads((ROOT/'v6/SOURCE_MANIFEST.json').read_text())
        paths = ['v6/' + name for name in record['sha256']]
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', '--', *paths], cwd=ROOT,
            capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0,
                         'Every v6 manifest asset must exist in git archives:\n' + tracked.stderr)

    def test_v6_runtime_and_launchers_match_v7_parent_checkpoint(self):
        record = json.loads((ROOT/'docs/v6-runtime.json').read_text())
        self.assertEqual(record['version'], '0.6.0')
        source = json.loads((ROOT/'v6/SOURCE_MANIFEST.json').read_text())
        expected_files = {'v6/' + name for name in source['sha256']}
        expected_files.update({'v6/SOURCE_MANIFEST.json', 'go6.sh', 'go_v0.6.0.sh'})
        self.assertEqual(set(record['sha256']), expected_files)
        for name, expected in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected,
                                 'Preserved v6 changed: develop upgrades under v7/')

    def test_v7_manifest_covers_runtime_and_packaged_data(self):
        record = json.loads((ROOT/'v7/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(record['version'], '0.7.0')
        self.assertEqual(record['based_on_version'], '0.6.0')
        files = record['sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v7'/name).read_bytes()).hexdigest(), expected)
        runtime = {p.name for p in (ROOT/'v7').iterdir()
                   if p.is_file() and p.suffix in ('.py', '.sh')}
        self.assertEqual(runtime, {name for name in files
                                  if '/' not in name and Path(name).suffix in ('.py', '.sh')})

    def test_v7_manifest_files_are_tracked_for_clean_exports(self):
        source = json.loads((ROOT/'v7/SOURCE_MANIFEST.json').read_text())
        paths = ['v7/' + name for name in source['sha256']]
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', '--', *paths], cwd=ROOT,
            capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0,
                         'Every v7 manifest asset must exist in git archives:\n' + tracked.stderr)

    def test_v7_runtime_and_launchers_match_v8_parent_checkpoint(self):
        record = json.loads((ROOT/'docs/v7-runtime.json').read_text())
        self.assertEqual(record['version'], '0.7.0')
        tracked = set(subprocess.run(
            ['git', 'ls-files', 'v7'], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.splitlines())
        expected = tracked | {'go7.sh', 'go_v0.7.0.sh'}
        self.assertEqual(set(record['sha256']), expected)
        for name, expected_digest in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(
                    hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),
                    expected_digest,
                    'Preserved v7 changed: develop upgrades under v8/')

    def test_v8_manifest_covers_runtime_and_packaged_data(self):
        record = json.loads((ROOT/'v8/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(record['version'], '0.8.0')
        self.assertEqual(record['based_on_version'], '0.7.0')
        files = record['sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v8'/name).read_bytes()).hexdigest(),
                                 expected)
        runtime = {p.name for p in (ROOT/'v8').iterdir()
                   if p.is_file() and p.suffix in ('.py', '.sh')}
        self.assertEqual(runtime, {name for name in files
                                  if '/' not in name and Path(name).suffix in ('.py', '.sh')})

    def test_v8_manifest_files_are_tracked_for_clean_exports(self):
        record = json.loads((ROOT/'v8/SOURCE_MANIFEST.json').read_text())
        paths = ['v8/' + name for name in record['sha256']]
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', '--', *paths], cwd=ROOT,
            capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0,
                         'Every v8 manifest asset must exist in git archives:\n' + tracked.stderr)

    def _assert_preserved_runtime(self, record_name, version, package, launchers):
        record = json.loads((ROOT/'docs'/record_name).read_text())
        self.assertEqual(record['version'], version)
        tracked = set(subprocess.run(
            ['git', 'ls-files', package], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.splitlines())
        expected = tracked | set(launchers)
        self.assertEqual(set(record['sha256']), expected)
        for name, expected_digest in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(
                    hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),
                    expected_digest,
                    f'Preserved {package} changed: develop upgrades under v9/')

    def test_v8_runtime_and_launchers_match_v9_parent_checkpoint(self):
        self._assert_preserved_runtime(
            'v8-runtime.json', '0.8.0', 'v8', ('go8.sh', 'go_v0.8.0.sh'))

    def test_v8a_runtime_and_launcher_match_v9_parent_checkpoint(self):
        self._assert_preserved_runtime(
            'v8a-runtime.json', '0.8.0', 'v8a', ('go8a.sh',))

    def test_v9_manifest_covers_runtime_and_packaged_data(self):
        record = json.loads((ROOT/'v9/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(record['version'], '0.9.0')
        self.assertEqual(record['based_on_version'], '0.8.0')
        files = record['sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v9'/name).read_bytes()).hexdigest(),
                                 expected)
        runtime = {p.name for p in (ROOT/'v9').iterdir()
                   if p.is_file() and p.suffix in ('.py', '.sh')}
        self.assertEqual(runtime, {name for name in files
                                  if '/' not in name and Path(name).suffix in ('.py', '.sh')})

    def test_v9_package_and_launchers_are_tracked_for_clean_clones(self):
        record = json.loads((ROOT/'v9/SOURCE_MANIFEST.json').read_text())
        paths = ['v9/' + name for name in record['sha256']]
        paths.extend(('v9/SOURCE_MANIFEST.json', 'go9.sh', 'go_v0.9.0.sh'))
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', '--', *paths], cwd=ROOT,
            capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0,
                         'Every v9 runtime asset and launcher must exist in git clones:\n'
                         + tracked.stderr)

    def test_v9_runtime_and_launchers_match_v10_parent_checkpoint(self):
        record = json.loads((ROOT/'docs/v9-runtime.json').read_text())
        self.assertEqual(record['version'], '0.9.0')
        tracked = set(subprocess.run(
            ['git', 'ls-files', 'v9'], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.splitlines())
        expected = tracked | {'go9.sh', 'go_v0.9.0.sh'}
        self.assertEqual(set(record['sha256']), expected)
        for name, expected_digest in record['sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(
                    hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),
                    expected_digest,
                    'Preserved v9 changed: develop upgrades under v10/')

    def test_v10_manifest_covers_runtime_and_packaged_data(self):
        record = json.loads((ROOT/'v10/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(record['version'], '0.10.0')
        self.assertEqual(record['based_on_version'], '0.9.0')
        files = record['sha256']
        for name, expected in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/'v10'/name).read_bytes()).hexdigest(),
                                 expected)
        tracked = {path.removeprefix('v10/') for path in subprocess.run(
            ['git', 'ls-files', 'v10'], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.splitlines()}
        tracked.discard('SOURCE_MANIFEST.json')
        self.assertEqual(set(files), tracked)

    def test_v10_package_and_launchers_are_tracked_for_clean_clones(self):
        record = json.loads((ROOT/'v10/SOURCE_MANIFEST.json').read_text())
        paths = ['v10/' + name for name in record['sha256']]
        paths.extend(('v10/SOURCE_MANIFEST.json', 'go10.sh', 'go_v0.10.0.sh'))
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', '--', *paths], cwd=ROOT,
            capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0,
                         'Every v10 runtime asset and launcher must exist in git clones:\n'
                         + tracked.stderr)


if __name__ == '__main__':
    unittest.main()
