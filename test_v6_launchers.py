"""Exercise packaged v6 dispatch without a worktree or scientific dependencies."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHERS = ('go6.sh', 'go_v0.6.0.sh')
VERSION = '0.6.0'


class V6LauncherTests(unittest.TestCase):
    def test_package_version_interfaces_agree(self):
        project = tomllib.loads((ROOT/'v6/pyproject.toml').read_text())
        lock = tomllib.loads((ROOT/'v6/uv.lock').read_text())
        self.assertEqual(project['project']['version'], VERSION)
        self.assertEqual(next(p['version'] for p in lock['package']
                              if p['name'] == project['project']['name']), VERSION)
        module = ast.parse((ROOT/'v6/point_star_barghini.py').read_text())
        version = next(ast.literal_eval(node.value) for node in module.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'SOLVER_VERSION'
                               for t in node.targets))
        self.assertEqual(version, VERSION)

    def make_package(self, root, version=VERSION):
        (root/'v6/data').mkdir(parents=True)
        for name in LAUNCHERS + ('v6/run.sh',):
            destination = root/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, destination)
        (root/'v6/data/stars_gaia_dr3_g75.csv').write_text('fixture')
        stub = root/'v6/analyse.sh'
        stub.write_text("#!/usr/bin/env python3\n"
                        "import json, pathlib, sys\n"
                        "if sys.argv[1:] == ['--version']:\n"
                        f"    print('Wide-field solver {version}'); sys.exit()\n"
                        "args = sys.argv[1:]\n"
                        "output = pathlib.Path(args[args.index('--output') + 1])\n"
                        "output.mkdir(parents=True)\n"
                        "(output/'args.json').write_text(json.dumps(args))\n"
                        "(output/'report.pdf').write_bytes(b'fixture')\n")
        stub.chmod(0o755)

    def test_both_launchers_run_local_v6_and_preserve_each_output(self):
        with tempfile.TemporaryDirectory(prefix='solver package ') as tmp:
            root = Path(tmp)
            self.make_package(root)
            image = root/'image with spaces.jpg'
            image.write_bytes(b'fixture')
            for launcher in LAUNCHERS:
                for _ in range(2):
                    completed = subprocess.run([str(root/launcher), str(image)], cwd='/tmp',
                                               capture_output=True, text=True)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertIn('Solver: Wide-field solver 0.6.0, Gaia DR3', completed.stdout)
            runs = sorted((root/'results/runs').iterdir())
            self.assertEqual(len(runs), 4)
            for run in runs:
                self.assertIn('-v0.6.0-', run.name)
                args = json.loads((run/'analysis/args.json').read_text())
                self.assertEqual(args, [str(image), '--catalog',
                                       str(root/'v6/data/stars_gaia_dr3_g75.csv'),
                                       '--epoch-mode', 'fit', '--output', str(run/'analysis')])
                self.assertTrue((run/'analysis/report.pdf').exists())
                self.assertTrue((run/'run.log').exists())

    def test_help_version_and_invalid_input_need_no_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_package(root)
            (root/'v6/analyse.sh').unlink()
            for launcher in LAUNCHERS:
                for option, fragment in (('--version', VERSION), ('--help', 'Usage:')):
                    completed = subprocess.run([str(root/launcher), option], cwd='/tmp',
                                               capture_output=True, text=True)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertIn(fragment, completed.stdout)
                completed = subprocess.run([str(root/launcher), 'missing.jpg'], cwd='/tmp',
                                           capture_output=True, text=True)
                self.assertEqual(completed.returncode, 2)
                self.assertFalse((root/'results').exists())

    def test_version_mismatch_refuses_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_package(root, version='0.5.0')
            image = root/'image.jpg'
            image.write_bytes(b'fixture')
            for launcher in LAUNCHERS:
                completed = subprocess.run([str(root/launcher), str(image)], cwd='/tmp',
                                           capture_output=True, text=True)
                self.assertEqual(completed.returncode, 2)
                self.assertIn('Version mismatch', completed.stderr)
                self.assertFalse((root/'results').exists())


if __name__ == '__main__':
    unittest.main()
