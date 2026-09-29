"""V13 owns its runtime while every earlier version remains frozen."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


class V13BoundaryTests(unittest.TestCase):
    def test_v12_snapshot_is_recorded_and_unchanged(self):
        saved = json.loads((ROOT / "docs/v12-runtime.json").read_text())
        self.assertEqual(saved["version"], "0.12.0")
        for name, digest in saved["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest
                )

    def test_independent_version_and_launchers(self):
        project = tomllib.loads((ROOT / "v13/pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "v13/uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.13.0")
        self.assertEqual(
            next(
                package["version"]
                for package in lock["package"]
                if package["name"] == project["project"]["name"]
            ),
            "0.13.0",
        )
        for launcher in ("go13.sh", "go_v0.13.0.sh"):
            with self.subTest(launcher=launcher):
                answer = subprocess.run(
                    [str(ROOT / launcher), "--version"],
                    cwd="/tmp",
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(answer.returncode, 0, answer.stderr)
                self.assertIn("0.13.0", answer.stdout)

    def test_v13_owns_runtime_assets(self):
        for relative in (
            "uv.lock",
            "data/stars_gaia_dr3_g75.csv",
            "data/planet-reference-1850-2036.npz",
            "examples/mmto/2026_09_19__02_20_01.fits.bz2",
        ):
            with self.subTest(path=relative):
                owned = ROOT / "v13" / relative
                parent = ROOT / "v12" / relative
                self.assertTrue(owned.is_file())
                self.assertFalse(owned.is_symlink())
                self.assertNotEqual(owned.resolve(), parent.resolve())


if __name__ == "__main__":
    unittest.main()
