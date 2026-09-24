"""V12 is independent while the public v11 runtime remains frozen."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


def repository_v12_files() -> set[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v12"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        path.removeprefix("v12/")
        for path in output
        if path.startswith("v12/") and path != "v12/SOURCE_MANIFEST.json"
    }


class V12BoundaryTests(unittest.TestCase):
    def test_v11_snapshot_is_unchanged(self):
        saved = json.loads((ROOT / "docs/v11-runtime.json").read_text())
        self.assertEqual(saved["version"], "0.11.0")
        for name, digest in saved["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                    digest,
                )

    def test_independent_version_and_launchers(self):
        self.assertTrue((ROOT / "v12/pyproject.toml").is_file())
        project = tomllib.loads((ROOT / "v12/pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "v12/uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.12.0")
        self.assertEqual(
            next(
                package["version"]
                for package in lock["package"]
                if package["name"] == project["project"]["name"]
            ),
            "0.12.0",
        )
        for launcher in ("go12.sh", "go_v0.12.0.sh"):
            with self.subTest(launcher=launcher):
                answer = subprocess.run(
                    [str(ROOT / launcher), "--version"],
                    cwd="/tmp",
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(answer.returncode, 0, answer.stderr)
                self.assertIn("0.12.0", answer.stdout)

    def test_v12_owns_runtime_assets(self):
        required = (
            "uv.lock",
            "data/stars_gaia_dr3_g75.csv",
            "data/planet-reference-1850-2036.npz",
            "data/minor-planet-reference-1850-2036.npz",
            "examples/milky_way/input.jpeg",
            "examples/mmto/2026_09_19__02_20_01.fits.bz2",
        )
        for relative in required:
            with self.subTest(path=relative):
                owned = ROOT / "v12" / relative
                parent = ROOT / "v11" / relative
                self.assertTrue(owned.is_file())
                self.assertFalse(owned.is_symlink())
                self.assertNotEqual(owned.resolve(), parent.resolve())

    def test_manifest_covers_runtime_and_matches_files(self):
        manifest_path = ROOT / "v12/SOURCE_MANIFEST.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["version"], "0.12.0")
        self.assertEqual(manifest["based_on_version"], "0.11.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v11-runtime.json")
        self.assertEqual(manifest["release_status"], "development")
        self.assertEqual(set(manifest["sha256"]), repository_v12_files())
        for name, digest in manifest["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / "v12" / name).read_bytes()).hexdigest(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main()
