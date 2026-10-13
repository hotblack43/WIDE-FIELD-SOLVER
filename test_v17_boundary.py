"""V17 owns KNALDGAS support while the completed v16 runtime remains frozen."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


def repository_v17_files() -> set[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v17"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        path.removeprefix("v17/")
        for path in output
        if path.startswith("v17/") and path != "v17/SOURCE_MANIFEST.json"
    }


class V17BoundaryTests(unittest.TestCase):
    def test_v16_snapshot_is_recorded_and_unchanged(self):
        saved = json.loads((ROOT / "docs/v16-runtime.json").read_text())
        self.assertEqual(saved["version"], "0.16.0")
        self.assertEqual(saved["snapshot_kind"], "v17-boundary")
        self.assertTrue(
            {
                "go16.sh",
                "go_v0.16.0.sh",
                "go_fits_v16.sh",
                "go_mmto_photometry_v16.sh",
                "v16/pyproject.toml",
                "v16/uv.lock",
                "v16/data/stars_gaia_dr3_g75.csv",
                "v16/data/planet-reference-1850-2036.npz",
            }.issubset(saved["sha256"])
        )
        for name, digest in saved["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest
                )

    def test_independent_version(self):
        project = tomllib.loads((ROOT / "v17/pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "v17/uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.17.0")
        self.assertEqual(
            next(
                package["version"]
                for package in lock["package"]
                if package["name"] == project["project"]["name"]
            ),
            "0.17.0",
        )
    def test_v17_owns_runtime_assets(self):
        for relative in (
            "uv.lock",
            "data/stars_gaia_dr3_g75.csv",
            "data/planet-reference-1850-2036.npz",
            "examples/mmto/2026_09_19__02_20_01.fits.bz2",
        ):
            with self.subTest(path=relative):
                owned = ROOT / "v17" / relative
                parent = ROOT / "v16" / relative
                self.assertTrue(owned.is_file())
                self.assertFalse(owned.is_symlink())
                self.assertNotEqual(owned.resolve(), parent.resolve())

    def test_manifest_covers_runtime_and_matches_files(self):
        manifest = json.loads((ROOT / "v17/SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.17.0")
        self.assertEqual(manifest["based_on_version"], "0.16.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v16-runtime.json")
        self.assertEqual(set(manifest["sha256"]), repository_v17_files())
        for name, digest in manifest["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / "v17" / name).read_bytes()).hexdigest(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main()
