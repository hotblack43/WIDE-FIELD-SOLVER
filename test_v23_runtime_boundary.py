"""Regression boundary for the independent v23 aperture-photometry runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
V22_ROOT_FILES = {
    "calibrate_mmto_extinction_v22.sh",
    "go22.sh",
    "go_v0.22.0.sh",
    "go_mmto_photometry_v22.sh",
    "plot_mmto_variable_stars_v22.sh",
    "run_v22_photometry_benchmark.sh",
    "scripts/calibrate_nightly_extinction_v22.py",
    "scripts/map_mmto_sidereal_transmission_v22.py",
    "scripts/run_mmto_photometry_pipeline_v22.py",
    "scripts/run_v22_photometry_benchmark.py",
    "scripts/validate_mmto_site_time_v22.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked_runtime(version: str, root_files: set[str]) -> set[str]:
    package = f"v{version}"
    names = subprocess.run(
        ["git", "ls-files", package], cwd=ROOT, check=True,
        capture_output=True, text=True).stdout.splitlines()
    return root_files | {
        name for name in names if name != f"{package}/SOURCE_MANIFEST.json"
    }


class V23RuntimeBoundaryTests(unittest.TestCase):
    def test_v23_pipeline_invokes_only_the_v23_solver(self):
        from scripts.run_mmto_photometry_pipeline_v23 import (
            SOLVER_LAUNCHER, SOLVER_VERSION,
        )

        self.assertEqual(SOLVER_VERSION, "0.23.0")
        self.assertEqual(SOLVER_LAUNCHER, "go23.sh")

    def test_v23_owns_the_planet_retry_wrapper_named_by_its_pipeline(self):
        wrapper = ROOT / "v23" / "plot_ALL_planets_v23.sh"
        self.assertTrue(wrapper.is_file())
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertFalse((ROOT / "v23" / "plot_ALL_planets_v22.sh").exists())

    def test_every_v23_pipeline_stage_program_exists(self):
        from scripts.run_mmto_photometry_pipeline_v23 import _stage_commands

        stages = _stage_commands(
            ROOT,
            ROOT / "results" / "stars.sqlite",
            ROOT / "raw_allsky_samples" / "manifest.sqlite",
            Path("/output"),
            v21_control=Path("/controls/v21"),
        )
        for name, command in stages:
            with self.subTest(name):
                program = Path(
                    command[4]
                    if command[:4] == ["uv", "run", "--frozen", "python"]
                    else command[0]
                )
                self.assertTrue(program.is_file(), program)

    def test_v22_snapshot_covers_final_runtime(self):
        snapshot = json.loads((ROOT / "docs/v22-runtime.json").read_text())
        self.assertEqual(snapshot["version"], "0.22.0")
        self.assertEqual(snapshot["snapshot_kind"], "v22-runtime-at-v23-boundary")
        expected = _tracked_runtime("22", V22_ROOT_FILES)
        self.assertEqual(set(snapshot["sha256"]), expected)
        self.assertEqual(
            snapshot["sha256"],
            {name: _sha256(ROOT / name) for name in sorted(expected)},
        )

    def test_v23_launchers_report_0230_without_a_branch(self):
        for name in ("go23.sh", "go_v0.23.0.sh"):
            completed = subprocess.run(
                [str(ROOT / name), "--version"], cwd=Path("/tmp"),
                env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("0.23.0", completed.stdout)

    def test_v23_manifest_and_lock_are_complete(self):
        package = ROOT / "v23"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.23.0")
        self.assertEqual(manifest["based_on_version"], "0.22.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v22-runtime.json")
        names = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v23"],
            cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
        expected = {
            name.removeprefix("v23/") for name in names
            if name.startswith("v23/") and name != "v23/SOURCE_MANIFEST.json"
        }
        self.assertEqual(set(manifest["sha256"]), expected)
        self.assertEqual(
            manifest["sha256"],
            {name: _sha256(package / name) for name in sorted(expected)},
        )
        project = tomllib.loads((package / "pyproject.toml").read_text())
        lock = tomllib.loads((package / "uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.23.0")
        packages = {row["name"]: row["version"] for row in lock["package"]}
        self.assertEqual(packages[project["project"]["name"]], "0.23.0")

    def test_v23_owns_inherited_scientific_data(self):
        parent = ROOT / "v22" / "data"
        child = ROOT / "v23" / "data"
        relative = {path.relative_to(parent) for path in parent.rglob("*") if path.is_file()}
        self.assertEqual(relative, {
            path.relative_to(child) for path in child.rglob("*") if path.is_file()
        })
        for path in sorted(relative):
            self.assertFalse((child / path).is_symlink())
            self.assertEqual(_sha256(parent / path), _sha256(child / path))


if __name__ == "__main__":
    unittest.main()
