"""V16 owns planet-only empirical extinction while v15 remains frozen."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


def repository_v16_files() -> set[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v16"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        path.removeprefix("v16/")
        for path in output
        if path.startswith("v16/") and path != "v16/SOURCE_MANIFEST.json"
    }


class V16BoundaryTests(unittest.TestCase):
    def test_v15_snapshot_is_recorded_and_unchanged(self):
        saved = json.loads((ROOT / "docs/v15-runtime.json").read_text())
        self.assertEqual(saved["version"], "0.15.0")
        self.assertTrue(
            {
                "plot_mmto_lightcurves.sh",
                "calibrate_mmto_extinction.sh",
                "plot_ALL_planets.sh",
                "scripts/plot_star_lightcurves.py",
                "scripts/calibrate_nightly_extinction.py",
                "scripts/nightly_extinction.py",
                "scripts/plot_planet_photometry.py",
                "scripts/plot_planet_colours.py",
                "scripts/plot_brightness_matched_planet_extinction.py",
                "pyproject.toml",
                "uv.lock",
                "sources.json",
            }.issubset(saved["sha256"])
        )
        self.assertTrue(
            {
                path
                for path in subprocess.run(
                    ["git", "ls-files", "allsky_download"],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
            }.issubset(saved["sha256"])
        )
        for name, digest in saved["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest
                )

    def test_independent_version_and_launchers(self):
        project = tomllib.loads((ROOT / "v16/pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "v16/uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.16.0")
        self.assertEqual(
            next(
                package["version"]
                for package in lock["package"]
                if package["name"] == project["project"]["name"]
            ),
            "0.16.0",
        )
        for launcher in ("go16.sh", "go_v0.16.0.sh"):
            with self.subTest(launcher=launcher):
                answer = subprocess.run(
                    [str(ROOT / launcher), "--version"],
                    cwd="/tmp",
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(answer.returncode, 0, answer.stderr)
                self.assertIn("0.16.0", answer.stdout)

    def test_v16_owns_runtime_assets(self):
        for relative in (
            "uv.lock",
            "data/stars_gaia_dr3_g75.csv",
            "data/planet-reference-1850-2036.npz",
            "examples/mmto/2026_09_19__02_20_01.fits.bz2",
        ):
            with self.subTest(path=relative):
                owned = ROOT / "v16" / relative
                parent = ROOT / "v15" / relative
                self.assertTrue(owned.is_file())
                self.assertFalse(owned.is_symlink())
                self.assertNotEqual(owned.resolve(), parent.resolve())

    def test_manifest_covers_runtime_and_matches_files(self):
        manifest = json.loads((ROOT / "v16/SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.16.0")
        self.assertEqual(manifest["based_on_version"], "0.15.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v15-runtime.json")
        self.assertEqual(set(manifest["sha256"]), repository_v16_files())
        for name, digest in manifest["sha256"].items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((ROOT / "v16" / name).read_bytes()).hexdigest(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main()
