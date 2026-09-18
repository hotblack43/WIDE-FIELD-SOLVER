"""Exercise packaged v9 dispatch without a worktree or scientific dependencies."""
import ast
import json
import os
from unittest.mock import patch
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHERS = ('go9.sh', 'go_v0.9.0.sh')
VERSION = '0.9.0'


class V9LauncherTests(unittest.TestCase):
    def setUp(self):
        self.config = tempfile.TemporaryDirectory()
        self.addCleanup(self.config.cleanup)
        self.environment = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.config.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop('WFS_RESULTS_DIR', None)

    def test_package_version_interfaces_agree(self):
        project = tomllib.loads((ROOT/'v9/pyproject.toml').read_text())
        lock = tomllib.loads((ROOT/'v9/uv.lock').read_text())
        self.assertEqual(project['project']['version'], VERSION)
        self.assertEqual(next(p['version'] for p in lock['package']
                              if p['name'] == project['project']['name']), VERSION)
        module = ast.parse((ROOT/'v9/point_star_barghini.py').read_text())
        version = next(ast.literal_eval(node.value) for node in module.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'SOLVER_VERSION'
                               for t in node.targets))
        self.assertEqual(version, VERSION)

    def make_package(self, root, version=VERSION):
        (root/'v9/data').mkdir(parents=True)
        for name in LAUNCHERS + ('v9/run.sh',):
            destination = root/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, destination)
        (root/'v9/data/stars_gaia_dr3_g75.csv').write_text('fixture')
        stub = root/'v9/analyse.sh'
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

    def test_launcher_runs_local_v9_and_preserve_each_output(self):
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
                    self.assertIn('Solver: Wide-field solver 0.9.0, Gaia DR3', completed.stdout)
            runs = sorted((root/'results/runs').iterdir())
            self.assertEqual(len(runs), 2 * len(LAUNCHERS))
            for run in runs:
                self.assertIn('-v0.9.0-', run.name)
                args = json.loads((run/'analysis/args.json').read_text())
                self.assertEqual(args, [str(image), '--catalog',
                                       str(root/'v9/data/stars_gaia_dr3_g75.csv'),
                                       '--epoch-mode', 'fit', '--output', str(run/'analysis'),
                                       '--database', str(root/'results/stars.sqlite')])
                self.assertTrue((run/'analysis/report.pdf').exists())
                self.assertTrue((run/'run.log').exists())

    def test_results_location_config_environment_and_cli_precedence(self):
        with tempfile.TemporaryDirectory(prefix='solver outputs ') as tmp:
            root = Path(tmp)/'repo'
            self.make_package(root)
            image = root/'image.jpg'
            image.write_bytes(b'fixture')
            configured = Path(tmp)/'configured results'
            configured.mkdir()
            config = Path(self.config.name)/'wide-field-solver'
            config.mkdir()
            host = subprocess.check_output(['hostname'], text=True).strip()
            (config/('results-dir.'+host)).write_text(str(configured)+'\n')
            locations = [configured, Path(tmp)/'environment results', Path(tmp)/'explicit results']
            for index, destination in enumerate(locations):
                env = os.environ.copy()
                if index:
                    env['WFS_RESULTS_DIR'] = str(locations[1])
                command = [str(root/'go9.sh'), str(image)]
                if index == 2:
                    command += ['--results-dir', str(destination)]
                completed = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                run = next((destination/'runs').iterdir())
                args = json.loads((run/'analysis/args.json').read_text())
                self.assertEqual(args[args.index('--database')+1], str(destination/'stars.sqlite'))
                self.assertNotIn('--results-dir', args)
                self.assertIn(str(destination/'stars.sqlite'), completed.stdout)
            self.assertFalse((root/'results').exists())

    def test_unavailable_configured_storage_fails_without_local_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'repo'
            self.make_package(root)
            image = root/'image.jpg'
            image.write_bytes(b'fixture')
            config = Path(self.config.name)/'wide-field-solver'
            config.mkdir()
            host = subprocess.check_output(['hostname'], text=True).strip()
            missing = Path(tmp)/'unmounted storage'
            (config/('results-dir.'+host)).write_text(str(missing)+'\n')
            completed = subprocess.run([str(root/'go9.sh'), str(image)], capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn('Configured results directory is unavailable', completed.stderr)
            self.assertFalse((root/'results').exists())
            self.assertFalse(missing.exists())

    def test_another_hosts_storage_setting_does_not_affect_home_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_package(root)
            image = root/'image.jpg'
            image.write_bytes(b'fixture')
            config = Path(self.config.name)/'wide-field-solver'
            config.mkdir()
            (config/'results-dir.another-computer').write_text('/unavailable/dmidata\n')
            completed = subprocess.run([str(root/'go9.sh'), str(image)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((root/'results/runs').is_dir())

    def test_help_version_and_invalid_input_need_no_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_package(root)
            (root/'v9/analyse.sh').unlink()
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

    def test_blind_planet_override_is_forwarded_by_both_launchers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_package(root)
            image = root/'image.jpg'
            image.write_bytes(b'fixture')
            for launcher in LAUNCHERS:
                completed = subprocess.run(
                    [str(root/launcher), str(image), '--blind-planets'], cwd='/tmp',
                    capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            for run in (root/'results/runs').iterdir():
                args = json.loads((run/'analysis/args.json').read_text())
                self.assertIn('--blind-planets', args)

    def test_version_mismatch_refuses_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_package(root, version='0.6.0')
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
