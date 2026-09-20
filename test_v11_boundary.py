"""V11 owns its runtime and must not change its v10 parent snapshot."""
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest

ROOT = Path(__file__).resolve().parent


class V11BoundaryTests(unittest.TestCase):
    def test_v10_snapshot_is_unchanged(self):
        saved = json.loads((ROOT/'docs/v10-runtime.json').read_text())
        # V11 was forked from a captured working parent, not the older commit.
        # Both inventories were recorded at that boundary; do not rehash either.
        working = saved['working_tree_parent_snapshot']
        self.assertEqual(working['version'], saved['version'])
        self.assertEqual(working['base_commit'], saved['base_commit'])
        self.assertEqual(set(working['sha256']), set(saved['sha256']))
        changed = {name for name, digest in working['sha256'].items()
                   if digest != saved['sha256'][name]}
        self.assertEqual(changed, set(working['dirty_paths']))
        for name, digest in working['sha256'].items():
            with self.subTest(path=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), digest)

    def test_v10_committed_checkpoint_matches_recorded_history(self):
        saved = json.loads((ROOT/'docs/v10-runtime.json').read_text())
        for name, digest in saved['sha256'].items():
            with self.subTest(path=name):
                content = subprocess.check_output(
                    ['git', 'show', f"{saved['preserved_commit']}:{name}"], cwd=ROOT)
                self.assertEqual(hashlib.sha256(content).hexdigest(), digest)

    def test_independent_version_and_launchers(self):
        project = tomllib.loads((ROOT/'v11/pyproject.toml').read_text())
        lock = tomllib.loads((ROOT/'v11/uv.lock').read_text())
        self.assertEqual(project['project']['version'], '0.11.0')
        self.assertEqual(next(p['version'] for p in lock['package']
                             if p['name'] == project['project']['name']), '0.11.0')
        for launcher in ('go11.sh', 'go_v0.11.0.sh'):
            answer = subprocess.run([str(ROOT/launcher), '--version'], cwd='/tmp',
                                    text=True, capture_output=True)
            self.assertEqual(answer.returncode, 0, answer.stderr)
            self.assertIn('0.11.0', answer.stdout)

    def test_manifest_covers_joint_runtime_and_matches_files(self):
        manifest = json.loads((ROOT/'v11/SOURCE_MANIFEST.json').read_text())
        self.assertEqual(manifest['version'], '0.11.0')
        self.assertEqual(manifest['release_status'], 'released as v0.11.0')
        for name in ('point_star_joint_epoch.py', 'point_star_joint_report.py', 'uv.lock',
                     'data/stars_gaia_dr3_g75.csv', 'data/planet-reference-1850-2036.npz',
                     'examples/mmto/2026_09_19__02_20_01.fits.bz2',
                     'examples/mmto/baseline.json', 'scripts/check_mmto_demo.py',
                     'scripts/run_mmto_demo.py', 'test_mmto_demo.py'):
            self.assertIn(name, manifest['sha256'])
        self.assertEqual(
            manifest['sha256']['examples/mmto/2026_09_19__02_20_01.fits.bz2'],
            'd7278337c18a87e19b4254dbd053769cc10233732f1ce686a44b235a567fa960')
        tracked = {
            path.removeprefix('v11/') for path in subprocess.run(
                ['git', 'ls-files', 'v11'], cwd=ROOT, check=True,
                capture_output=True, text=True).stdout.splitlines()
        }
        tracked.discard('SOURCE_MANIFEST.json')
        self.assertEqual(set(manifest['sha256']), tracked)
        for name, digest in manifest['sha256'].items():
            with self.subTest(path=name):
                self.assertEqual(hashlib.sha256((ROOT/'v11'/name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
