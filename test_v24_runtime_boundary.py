"""Regression boundary for the independent v24 visible-sky-mask runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
V23_ROOT_FILES = {
    "calibrate_mmto_extinction_v23.sh",
    "go23.sh",
    "go_v0.23.0.sh",
    "go_mmto_photometry_v23.sh",
    "plot_mmto_variable_stars_v23.sh",
    "run_v23_aperture_radius_benchmark.sh",
    "run_v23_photometry_benchmark.sh",
    "scripts/calibrate_nightly_extinction_v23.py",
    "scripts/map_mmto_sidereal_transmission_v23.py",
    "scripts/run_mmto_photometry_pipeline_v23.py",
    "scripts/run_v23_aperture_radius_benchmark.py",
    "scripts/run_v23_photometry_benchmark.py",
    "scripts/validate_mmto_site_time_v23.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked_runtime(version: str, root_files: set[str]) -> set[str]:
    package = f"v{version}"
    names = subprocess.run(
        ["git", "ls-files", package], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.splitlines()
    return root_files | {
        name for name in names if name != f"{package}/SOURCE_MANIFEST.json"
    }


class V24RuntimeBoundaryTests(unittest.TestCase):
    def test_v23_snapshot_covers_final_runtime(self):
        snapshot = json.loads((ROOT / "docs/v23-runtime.json").read_text())
        self.assertEqual(snapshot["version"], "0.23.0")
        self.assertEqual(snapshot["snapshot_kind"], "v23-runtime-at-v24-boundary")
        expected = _tracked_runtime("23", V23_ROOT_FILES)
        self.assertEqual(set(snapshot["sha256"]), expected)
        self.assertEqual(
            snapshot["sha256"],
            {name: _sha256(ROOT / name) for name in sorted(expected)},
        )

    def test_v24_pipeline_invokes_only_the_v24_solver(self):
        from scripts.run_mmto_photometry_pipeline_v24 import (
            SOLVER_ENTRYPOINT, SOLVER_VERSION,
        )

        self.assertEqual(SOLVER_VERSION, "0.24.0")
        self.assertEqual(SOLVER_ENTRYPOINT, Path("v24/analyse_image.py"))

    def test_v24_launchers_report_0240_without_a_branch(self):
        for name in ("go24.sh", "go_v0.24.0.sh"):
            completed = subprocess.run(
                [str(ROOT / name), "--version"], cwd=Path("/tmp"),
                env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("0.24.0", completed.stdout)

    def test_v24_manifest_and_lock_are_complete(self):
        package = ROOT / "v24"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.24.0")
        self.assertEqual(manifest["based_on_version"], "0.23.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v23-runtime.json")
        names = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "v24"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        expected = {
            name.removeprefix("v24/") for name in names
            if name.startswith("v24/") and name != "v24/SOURCE_MANIFEST.json"
        }
        self.assertEqual(set(manifest["sha256"]), expected)
        self.assertEqual(
            manifest["sha256"],
            {name: _sha256(package / name) for name in sorted(expected)},
        )
        project = tomllib.loads((package / "pyproject.toml").read_text())
        lock = tomllib.loads((package / "uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.24.0")
        packages = {row["name"]: row["version"] for row in lock["package"]}
        self.assertEqual(packages[project["project"]["name"]], "0.24.0")

    def test_v24_runtime_source_does_not_import_v23(self):
        offenders: list[str] = []
        for path in sorted((ROOT / "v24").rglob("*.py")):
            if path.name.startswith("test_") or "docs" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if "from v23" in source or "import v23" in source:
                offenders.append(str(path.relative_to(ROOT)))
        source = (ROOT / "scripts/run_mmto_photometry_pipeline_v24.py").read_text()
        if "from v23" in source or "import v23" in source:
            offenders.append("scripts/run_mmto_photometry_pipeline_v24.py")
        self.assertEqual(offenders, [])

    def test_v24_owns_inherited_scientific_data(self):
        parent = ROOT / "v23" / "data"
        child = ROOT / "v24" / "data"
        relative = {path.relative_to(parent) for path in parent.rglob("*") if path.is_file()}
        self.assertTrue(relative.issubset({
            path.relative_to(child) for path in child.rglob("*") if path.is_file()
        }))
        for path in sorted(relative):
            self.assertFalse((child / path).is_symlink())
            self.assertEqual(_sha256(parent / path), _sha256(child / path))


if __name__ == "__main__":
    unittest.main()
