"""Deliberately refresh the independent v11 source manifest (not other versions)."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package = root/'v11'
boundary = json.loads((root/'docs/v10-runtime.json').read_text())
names = {str(Path(p).relative_to('v10')) for p in boundary['sha256']
         if p.startswith('v10/') and p != 'v10/SOURCE_MANIFEST.json'}
names.update(['point_star_joint_epoch.py', 'point_star_joint_report.py', 'test_joint_epoch.py',
              'docs/V11_JOINT_EPOCH.md'])
manifest = dict(version='0.11.0', based_on_version='0.10.0',
    based_on_commit=boundary['base_commit'], parent_snapshot='../docs/v10-runtime.json',
    parent_snapshot_section='working_tree_parent_snapshot',
    release_status='development; see docs/V11_JOINT_EPOCH.md for numerical changes and acceptance',
    changes=[
        'Independent v11 package preserves current v10 bytes without changing or committing another window work.',
        'Global planet search never bounded by observation metadata; supplied timestamps are validation only.',
        'Refit common Barghini camera and epoch using stellar proper motions and at least two distinct moving bodies.',
        'Soft ephemeris relative brightness after native-channel zero-point profiling; saturation neutral.',
        'Conservative alias, membership, visibility, solar, and causal-interval checks retain stellar fallback.',
        'Joint authoritative product view shared by PDF/FITS/identified photometry; recoverable staged adoption.',
        'Report actual-position crops, joint profile, finite boundary-truncated interval and metadata discrepancy.',
        'Correct inherited double exposure normalization: raw counts enter counts/exposure magnitude helper once.'
    ], sha256={name: hashlib.sha256((package/name).read_bytes()).hexdigest() for name in sorted(names)})
(package/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
