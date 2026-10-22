"""Regression boundary for the independent v22 runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
V21_ROOT_FILES = {
    "calibrate_mmto_extinction_v21.sh",
    "go21.sh",
    "go_v0.21.0.sh",
    "go_mmto_photometry_v21.sh",
    "plot_mmto_variable_stars_v21.sh",
    "scripts/calibrate_nightly_extinction_v21.py",
    "scripts/map_mmto_sidereal_transmission_v21.py",
    "scripts/run_mmto_photometry_pipeline_v21.py",
    "scripts/validate_mmto_site_time_v21.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked_runtime(version: str, root_files: set[str]) -> set[str]:
    package = f"v{version}"
    names = subprocess.run(
        ["git", "ls-files", package],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return root_files | {
        name for name in names if name != f"{package}/SOURCE_MANIFEST.json"
    }


class V22RuntimeBoundaryTests(unittest.TestCase):
    def test_v21_snapshot_covers_final_runtime(self):
        snapshot = json.loads((ROOT / "docs/v21-runtime.json").read_text())
        self.assertEqual(snapshot["version"], "0.21.0")
        self.assertEqual(snapshot["snapshot_kind"], "v21-runtime-at-v22-boundary")
        expected = _tracked_runtime("21", V21_ROOT_FILES)
        self.assertEqual(set(snapshot["sha256"]), expected)
        self.assertEqual(
            snapshot["sha256"],
            {name: _sha256(ROOT / name) for name in sorted(expected)},
        )

    def test_v22_launchers_report_0220_without_a_branch(self):
        for name in ("go22.sh", "go_v0.22.0.sh"):
            completed = subprocess.run(
                [str(ROOT / name), "--version"],
                cwd=Path("/tmp"),
                env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("0.22.0", completed.stdout)

    def test_v22_manifest_and_lock_are_complete(self):
        package = ROOT / "v22"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.22.0")
        self.assertEqual(manifest["based_on_version"], "0.21.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v21-runtime.json")
        names = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v22"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        expected = {
            name.removeprefix("v22/")
            for name in names
            if name.startswith("v22/") and name != "v22/SOURCE_MANIFEST.json"
        }
        self.assertEqual(set(manifest["sha256"]), expected)
        self.assertEqual(
            manifest["sha256"],
            {name: _sha256(package / name) for name in sorted(expected)},
        )
        project = tomllib.loads((package / "pyproject.toml").read_text())
        lock = tomllib.loads((package / "uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.22.0")
        packages = {row["name"]: row["version"] for row in lock["package"]}
        self.assertEqual(packages[project["project"]["name"]], "0.22.0")
        self.assertEqual(packages["scikit-learn"], "1.9.1")

    def test_v22_owns_inherited_scientific_data(self):
        parent = ROOT / "v21" / "data"
        child = ROOT / "v22" / "data"
        relative_paths = {
            path.relative_to(parent)
            for path in parent.rglob("*")
            if path.is_file()
        }
        self.assertTrue(relative_paths)
        self.assertEqual(
            relative_paths,
            {path.relative_to(child) for path in child.rglob("*") if path.is_file()},
        )
        for relative in sorted(relative_paths):
            self.assertFalse((child / relative).is_symlink())
            self.assertEqual(_sha256(parent / relative), _sha256(child / relative))

    def test_mmto_launcher_pins_v22_and_canonical_results(self):
        completed = subprocess.run(
            ["bash", "-x", str(ROOT / "go_mmto_photometry_v22.sh"), "--help"],
            cwd=Path("/tmp"),
            env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("run_mmto_photometry_pipeline_v22.py", completed.stdout)
        self.assertIn(f"--results-dir {ROOT / 'results'}", completed.stdout)


if __name__ == "__main__":
    unittest.main()
