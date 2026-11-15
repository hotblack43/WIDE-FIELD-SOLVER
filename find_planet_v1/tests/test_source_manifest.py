from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))


class SourceManifestTests(unittest.TestCase):
    def test_manifest_exactly_covers_independent_runtime(self):
        manifest_path = ROOT / "find_planet_v1" / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
        paths = [entry["path"] for entry in entries]
        self.assertEqual(len(paths), len(set(paths)))
        expected = {
            str(path.relative_to(ROOT))
            for path in (ROOT / "find_planet_v1" / "find_planet").glob("*.py")
        } | {
            "find_planet_v1/pyproject.toml",
            "find_planet_v1/uv.lock",
            "go_find_planet_controlled_v1.sh",
        }
        self.assertEqual(set(paths), expected)
        for entry in entries:
            path = ROOT / entry["path"]
            self.assertTrue(path.is_file())
            self.assertTrue(entry["role"])
            self.assertEqual(
                entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest(), entry["path"]
            )
        forbidden_fragments = ("results/", "v23/", "raw_allsky_samples/", "docs/v23-runtime")
        self.assertFalse(any(fragment in path for path in paths for fragment in forbidden_fragments))


if __name__ == "__main__":
    unittest.main()
