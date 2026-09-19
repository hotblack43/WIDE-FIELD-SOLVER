"""One-shot, non-overwriting v11 snapshot of tracked v10 working bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
target = root / 'v11'
if target.exists() or (root / 'docs/v10-runtime.json').exists():
    raise SystemExit('Refusing to overwrite an existing version boundary')
paths = subprocess.check_output(
    ['git', 'ls-files', '-z', 'v10', 'go10.sh', 'go_v0.10.0.sh'], cwd=root
).decode().strip('\0').split('\0')
hashes = {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
record = dict(version='0.10.0',
    base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip(),
    snapshot_kind='working-tree; pre-existing exposure-rate fix retained, not committed here',
    dirty_paths=subprocess.check_output(['git', 'diff', '--name-only', '--', 'v10'], cwd=root).decode().splitlines(),
    sha256=hashes)
(root/'docs/v10-runtime.json').write_text(json.dumps(record, indent=2)+'\n')
for p in paths:
    if not p.startswith('v10/'):
        continue
    dest = target / Path(p).relative_to('v10')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root/p, dest)
# Mechanical version substitution only; scientific changes are separate patches.
for name in ['run.sh', 'pyproject.toml', 'uv.lock', 'point_star_barghini.py',
             'test_epoch_integration.py', 'AGENTS.md']:
    path = target/name
    path.write_text(path.read_text().replace('0.10.0', '0.11.0')
                    .replace('go10', 'go11').replace('v10/', 'v11/')
                    .replace('$repo/v10', '$repo/v11'))
