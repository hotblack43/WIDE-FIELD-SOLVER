"""V18 continues MMTO work from frozen v16 while v17 remains independent."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


def repository_v18_files() -> set[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v18"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        path.removeprefix("v18/")
        for path in output
        if path.startswith("v18/") and path != "v18/SOURCE_MANIFEST.json"
    }


class V18BoundaryTests(unittest.TestCase):
    def test_v18_is_an_independent_mmto_continuation_of_v16(self):
        package = ROOT / "v18"
        self.assertTrue(package.is_dir(), "v18 runtime is missing")
        project = tomllib.loads((package / "pyproject.toml").read_text())
        lock = tomllib.loads((package / "uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.18.0")
        self.assertEqual(
            next(
                item["version"]
                for item in lock["package"]
                if item["name"] == project["project"]["name"]
            ),
            "0.18.0",
        )
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.18.0")
        self.assertEqual(manifest["based_on_version"], "0.16.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v16-runtime.json")

    def test_versioned_launchers_use_v18_without_repointing_v17(self):
        for launcher in ("go18.sh", "go_v0.18.0.sh"):
            with self.subTest(launcher=launcher):
                path = ROOT / launcher
                self.assertTrue(path.is_file(), f"missing launcher: {launcher}")
                answer = subprocess.run(
                    [str(path), "--version"],
                    cwd="/tmp",
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(answer.returncode, 0, answer.stderr)
                self.assertIn("go18", answer.stdout)
                self.assertIn("0.18.0", answer.stdout)
        v17 = subprocess.run(
            [str(ROOT / "go17.sh"), "--version"],
            cwd="/tmp",
            text=True,
            capture_output=True,
        )
        self.assertEqual(v17.returncode, 0, v17.stderr)
        self.assertIn("0.17.0", v17.stdout)

    def test_v18_owns_runtime_assets(self):
        for relative in (
            "uv.lock",
            "data/stars_gaia_dr3_g75.csv",
            "data/planet-reference-1850-2036.npz",
            "examples/mmto/2026_09_19__02_20_01.fits.bz2",
        ):
            with self.subTest(path=relative):
                owned = ROOT / "v18" / relative
                parent = ROOT / "v16" / relative
                self.assertTrue(owned.is_file())
                self.assertFalse(owned.is_symlink())
                self.assertNotEqual(owned.resolve(), parent.resolve())

    def test_manifest_covers_runtime_and_matches_files(self):
        manifest_path = ROOT / "v18/SOURCE_MANIFEST.json"
        self.assertTrue(manifest_path.is_file(), "v18 source manifest is missing")
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(set(manifest["sha256"]), repository_v18_files())
        for name, digest in manifest["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / "v18" / name).read_bytes()).hexdigest(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main()
