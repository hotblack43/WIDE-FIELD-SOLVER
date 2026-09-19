"""Check the boundary test itself against captured and subsequently edited bytes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_v11_boundary as boundary


class RuntimeSnapshotPolicyTests(unittest.TestCase):
    def test_captured_working_parent_is_accepted_but_later_edits_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'docs').mkdir()
            (root/'v10').mkdir()
            path = root/'v10/runtime.py'
            path.write_bytes(b'working parent captured at freeze\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            record = dict(version='0.10.0', base_commit='checkpoint',
                          sha256={'v10/runtime.py': hashlib.sha256(b'older committed parent\n').hexdigest()},
                          working_tree_parent_snapshot=dict(
                              version='0.10.0', base_commit='checkpoint',
                              dirty_paths=['v10/runtime.py'], sha256={'v10/runtime.py': digest}))
            manifest = root/'docs/v10-runtime.json'
            manifest.write_text(json.dumps(record))
            case = boundary.V11BoundaryTests('test_v10_snapshot_is_unchanged')
            with patch.object(boundary, 'ROOT', root):
                case.test_v10_snapshot_is_unchanged()
                path.write_bytes(b'unapproved later change\n')
                with self.assertRaises(AssertionError):
                    case.test_v10_snapshot_is_unchanged()
                path.write_bytes(b'working parent captured at freeze\n')
                record['working_tree_parent_snapshot']['sha256'] = {}
                manifest.write_text(json.dumps(record))
                with self.assertRaises(AssertionError):
                    case.test_v10_snapshot_is_unchanged()


if __name__ == '__main__':
    unittest.main()
