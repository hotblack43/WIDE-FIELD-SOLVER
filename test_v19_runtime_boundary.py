"""Regression boundary for the independent v19 runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent
PRESERVED_TREE_SHA256 = {
    "v16": "f6c927df616fb0be71b7a3cbc2994f852d17cdb9f1f611d1f4aa863562a9ea44",
    "v17": "a19ffcb173801cb16c2826d9e0ef2b40fb260e143033aa575a3f4a42e5a65252",
    "v18": "0a9ce24eef8c9d4ac075e3c417501223d048beee0a2cc34d0d187c6caffcdcb1",
}


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
    )
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class V19RuntimeBoundaryTests(unittest.TestCase):
    def test_v19_launchers_report_0190(self):
        for name in ("go19.sh", "go_v0.19.0.sh"):
            launcher = ROOT / name
            completed = subprocess.run(
                [str(launcher), "--version"],
                cwd=ROOT,
                env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("0.19.0", completed.stdout)
            self.assertNotIn("does not match the project environment", completed.stdout)

    def test_v19_manifest_is_complete_and_based_on_v16(self):
        package = ROOT / "v19"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.19.0")
        self.assertEqual(manifest["based_on_version"], "0.16.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v16-runtime.json")
        actual = {
            path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in package.rglob("*")
            if path.is_file()
            and path.name != "SOURCE_MANIFEST.json"
            and ".venv" not in path.parts
            and "__pycache__" not in path.parts
        }
        self.assertEqual(manifest["sha256"], dict(sorted(actual.items())))

    def test_preserved_v16_v17_v18_bytes_match_preimplementation_snapshot(self):
        for version, expected in PRESERVED_TREE_SHA256.items():
            with self.subTest(version=version):
                self.assertEqual(_tree_sha256(ROOT / version), expected)


if __name__ == "__main__":
    unittest.main()
