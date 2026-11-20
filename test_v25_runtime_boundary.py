"""Regression boundary for the final v24 and independent v25 runtimes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
V24_ROOT_FILES = {
    "calibrate_mmto_extinction_v24.sh",
    "go24.sh",
    "go_v0.24.0.sh",
    "go_mmto_photometry_v24.sh",
    "plot_mmto_variable_stars_v24.sh",
    "run_v24_photometry_benchmark.sh",
    "scripts/calibrate_nightly_extinction_v24.py",
    "scripts/map_mmto_sidereal_transmission_v24.py",
    "scripts/run_mmto_photometry_pipeline_v24.py",
    "scripts/run_v24_photometry_benchmark.py",
    "scripts/validate_mmto_site_time_v24.py",
}
V25_ROOT_FILES = {
    "calibrate_mmto_extinction_v25.sh",
    "go25.sh",
    "go_v0.25.0.sh",
    "go_mmto_photometry_v25.sh",
    "go_visible_sky_v25.sh",
    "plot_mmto_variable_stars_v25.sh",
    "quickstart.sh",
    "run_v25_aperture_radius_benchmark.sh",
    "run_v25_photometry_benchmark.sh",
    "scripts/calibrate_nightly_extinction_v25.py",
    "scripts/map_mmto_sidereal_transmission_v25.py",
    "scripts/run_v25_aperture_radius_benchmark.py",
    "scripts/run_mmto_photometry_pipeline_v25.py",
    "scripts/run_v25_photometry_benchmark.py",
    "scripts/validate_mmto_site_time_v25.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_v24_runtime() -> set[str]:
    names = subprocess.run(
        [
            "git", "ls-files", "--cached", "--others", "--exclude-standard",
            "v24",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return V24_ROOT_FILES | set(names)


class V25RuntimeBoundaryTests(unittest.TestCase):
    def test_v24_snapshot_covers_final_runtime_and_acceptance_evidence(self):
        snapshot_path = ROOT / "docs/v24-runtime.json"
        self.assertTrue(snapshot_path.is_file(), "missing final v24 snapshot")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["version"], "0.24.0")
        self.assertEqual(snapshot["snapshot_kind"], "v24-runtime-at-v25-boundary")
        expected = _repository_v24_runtime()
        self.assertIn(
            "v24/examples/mmto/cold_start_candidate_mask.png", expected
        )
        self.assertIn(
            "v24/examples/mmto/cold_start_regression_acceptance.json", expected
        )
        self.assertEqual(set(snapshot["sha256"]), expected)
        self.assertEqual(
            snapshot["sha256"],
            {name: _sha256(ROOT / name) for name in sorted(expected)},
        )
        for name in snapshot["sha256"]:
            parts = Path(name).parts
            self.assertNotIn("__pycache__", parts)
            self.assertNotIn("results", parts)
            self.assertFalse(name.startswith("raw_allsky_samples/"))

    def test_v25_runtime_and_launchers_are_independent(self):
        for name in sorted(V25_ROOT_FILES | {"v25/pyproject.toml", "v25/uv.lock"}):
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file(), f"missing v25 runtime: {name}")
        project = tomllib.loads((ROOT / "v25/pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "v25/uv.lock").read_text())
        self.assertEqual(project["project"]["version"], "0.25.0")
        packages = {row["name"]: row["version"] for row in lock["package"]}
        self.assertEqual(packages[project["project"]["name"]], "0.25.0")
        for name in ("go25.sh", "go_v0.25.0.sh"):
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
            self.assertIn("0.25.0", completed.stdout)

    def test_v25_pipeline_invokes_only_v25_runtime(self):
        from scripts.run_mmto_photometry_pipeline_v25 import (
            SOLVER_ENTRYPOINT,
            SOLVER_VERSION,
        )

        self.assertEqual(SOLVER_VERSION, "0.25.0")
        self.assertEqual(SOLVER_ENTRYPOINT, Path("v25/analyse_image.py"))
        offenders = []
        for path in sorted((ROOT / "v25").rglob("*.py")):
            if path.name.startswith("test_") or "docs" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if "from v24" in source or "import v24" in source:
                offenders.append(str(path.relative_to(ROOT)))
        source = (ROOT / "scripts/run_mmto_photometry_pipeline_v25.py").read_text()
        if "from v24" in source or "import v24" in source:
            offenders.append("scripts/run_mmto_photometry_pipeline_v25.py")
        self.assertEqual(offenders, [])

    def test_v25_stage_launchers_use_only_the_v25_project(self):
        calibrate = (ROOT / "calibrate_mmto_extinction_v25.sh").read_text()
        planets = (ROOT / "v25/plot_ALL_planets_impl_v25.sh").read_text()
        aperture = (ROOT / "run_v25_aperture_radius_benchmark.sh").read_text()
        self.assertIn('--project "$ROOT/v25"', calibrate)
        self.assertNotIn('--project "$ROOT_DIR"', planets)
        self.assertEqual(planets.count('--project "$V25_DIR"'), 3)
        self.assertIn('--project "$repo/v25"', aperture)

    def test_v25_manifest_covers_complete_package(self):
        package = ROOT / "v25"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        names = subprocess.run(
            [
                "git", "ls-files", "--cached", "--others",
                "--exclude-standard", "v25",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        expected = {
            name.removeprefix("v25/")
            for name in names
            if name.startswith("v25/") and name != "v25/SOURCE_MANIFEST.json"
        }
        self.assertIn("data/sky_masks/mmto_installation_2026a.png", expected)
        self.assertIn("examples/mmto/cold_start_candidate_mask.png", expected)
        self.assertIn("examples/visible_sky_operator.example.toml", expected)
        self.assertEqual(set(manifest["sha256"]), expected)
        self.assertEqual(
            manifest["sha256"],
            {name: _sha256(package / name) for name in sorted(expected)},
        )

    def test_v25_owns_unchanged_v24_scientific_data_at_the_boundary(self):
        parent = ROOT / "v24/data"
        child = ROOT / "v25/data"
        relative = {path.relative_to(parent) for path in parent.rglob("*") if path.is_file()}
        self.assertTrue(relative.issubset({
            path.relative_to(child) for path in child.rglob("*") if path.is_file()
        }))
        for path in sorted(relative):
            self.assertFalse((child / path).is_symlink())
            self.assertEqual(_sha256(parent / path), _sha256(child / path))


if __name__ == "__main__":
    unittest.main()
