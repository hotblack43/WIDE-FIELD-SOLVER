"""A checkout must keep Tycho legacy and Gaia v4 launchers separate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class LauncherRouteTests(unittest.TestCase):
    def run_launcher(self, launcher):
        with tempfile.TemporaryDirectory(prefix='solver route ') as tmp:
            root = Path(tmp)
            # Copy only the shell entrypoints and catalogue sentinels. There is
            # deliberately no .worktrees directory or development environment.
            for base in (ROOT, ROOT/'v4'):
                if not base.exists():
                    continue
                dest = root/base.relative_to(ROOT)
                dest.mkdir(exist_ok=True)
                for script in base.glob('*.sh'):
                    shutil.copy2(script, dest/script.name)
            for relative in ('data/stars_tycho2_mag75.csv', 'v4/data/stars_gaia_dr3_g75.csv'):
                p = root/relative
                p.parent.mkdir(parents=True, exist_ok=True)
                if (ROOT/relative).is_file():
                    p.touch()
            fake = root/'bin'; fake.mkdir()
            uv = fake/'uv'
            uv.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args=sys.argv[1:]
if '--version' in args:
    print('analyse_image.py 0.4.3')
else:
    with open(os.environ['CAPTURE'], 'a') as f:
        f.write(json.dumps(args)+'\\n')
    output=pathlib.Path(args[args.index('--output')+1])
    output.mkdir(parents=True, exist_ok=True)
    name = 'report.pdf' if pathlib.Path(args[args.index('--project')+1]).name == 'v4' else 'report_test.pdf'
    (output/name).write_bytes(b'%PDF-test')
''')
            uv.chmod(0o755)
            image = root/'test image.jpg'; image.touch()
            capture = root/'arguments.jsonl'
            env = dict(os.environ, PATH=str(fake)+os.pathsep+os.environ['PATH'], CAPTURE=str(capture))
            result = subprocess.run([str(root/launcher), str(image)], cwd=root,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            args = json.loads(capture.read_text().splitlines()[-1])
            project = Path(args[args.index('--project')+1]).relative_to(root)
            entry = next(Path(a).relative_to(root) for a in args if a.endswith('analyse_image.py'))
            catalogue = (Path(args[args.index('--catalog')+1]).relative_to(root)
                         if '--catalog' in args else None)
            return project, entry, catalogue, args

    def test_go_uses_preserved_root_tycho_workflow(self):
        project, entry, catalogue, args = self.run_launcher('go.sh')
        self.assertEqual(project, Path('.'))
        self.assertEqual(entry, Path('analyse_image.py'))
        # The untouched legacy analyser supplies its Tycho default.
        from analyse_image import parser
        parsed = parser().parse_args(['test.jpg', '--output', 'out'])
        self.assertEqual(parsed.catalog, ROOT/'data/stars_tycho2_mag75.csv')
        self.assertIsNone(catalogue)

    def test_go4_uses_packaged_gaia_and_blind_epoch(self):
        project, entry, catalogue, args = self.run_launcher('go4.sh')
        self.assertEqual(project, Path('v4'))
        self.assertEqual(entry, Path('v4/analyse_image.py'))
        self.assertEqual(catalogue, Path('v4/data/stars_gaia_dr3_g75.csv'))
        self.assertEqual(args[args.index('--epoch-mode')+1], 'fit')

    def test_versioned_v043_uses_the_packaged_runtime(self):
        project, entry, catalogue, args = self.run_launcher('go_v0.4.3.sh')
        self.assertEqual(project, Path('v4'))
        self.assertEqual(catalogue, Path('v4/data/stars_gaia_dr3_g75.csv'))


if __name__ == '__main__':
    unittest.main()
