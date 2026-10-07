"""V15 owns early celestial gating while v14 remains frozen."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


def repository_v15_files() -> set[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v15"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        path.removeprefix("v15/")
        for path in output
        if path.startswith("v15/") and path != "v15/SOURCE_MANIFEST.json"
    }


class V15BoundaryTests(unittest.TestCase):
    def test_v14_snapshot_is_recorded_and_unchanged(self):
        saved = json.loads((ROOT / "docs/v14-runtime.json").read_text())
        self.assertEqual(saved["version"], "0.14.0")
        for name, digest in saved["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest
                )

    def test_independent_version_and_launchers(self):
        project = tomllib.loads((ROOT / "v15/pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "v15/uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.15.0")
        self.assertEqual(
            next(
                package["version"]
                for package in lock["package"]
                if package["name"] == project["project"]["name"]
            ),
            "0.15.0",
        )
        for launcher in ("go15.sh", "go_v0.15.0.sh"):
            with self.subTest(launcher=launcher):
                answer = subprocess.run(
                    [str(ROOT / launcher), "--version"],
                    cwd="/tmp",
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(answer.returncode, 0, answer.stderr)
                self.assertIn("0.15.0", answer.stdout)

    def test_v15_owns_runtime_assets(self):
        for relative in (
            "uv.lock",
            "data/stars_gaia_dr3_g75.csv",
            "data/planet-reference-1850-2036.npz",
            "examples/mmto/2026_09_19__02_20_01.fits.bz2",
        ):
            with self.subTest(path=relative):
                owned = ROOT / "v15" / relative
                parent = ROOT / "v14" / relative
                self.assertTrue(owned.is_file())
                self.assertFalse(owned.is_symlink())
                self.assertNotEqual(owned.resolve(), parent.resolve())

    def test_manifest_covers_runtime_and_matches_files(self):
        manifest = json.loads((ROOT / "v15/SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.15.0")
        self.assertEqual(manifest["based_on_version"], "0.14.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v14-runtime.json")
        self.assertEqual(set(manifest["sha256"]), repository_v15_files())
        for name, digest in manifest["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / "v15" / name).read_bytes()).hexdigest(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main()
