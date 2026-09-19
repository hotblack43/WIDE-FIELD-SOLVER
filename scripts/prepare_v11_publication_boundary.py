"""Keep working-parent provenance while freezing the committed v10 runtime.

Run once before publishing v11 without other windows' v10 changes.
No v10 file or existing-version manifest is edited.
"""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
path = root/'docs/v10-runtime.json'
record = json.loads(path.read_text())
if 'working_tree_parent_snapshot' in record:
    raise SystemExit('Publication boundary already prepared')
original = dict(record)
commit = record['base_commit']
record['working_tree_parent_snapshot'] = original
record['snapshot_kind'] = 'committed v10 preservation boundary; working parent retained separately'
record['preserved_commit'] = commit
record['sha256'] = {
    name: hashlib.sha256(subprocess.check_output(
        ['git', 'show', f'{commit}:{name}'], cwd=root)).hexdigest()
    for name in original['sha256']
}
record.pop('dirty_paths', None)
path.write_text(json.dumps(record, indent=2)+'\n')
