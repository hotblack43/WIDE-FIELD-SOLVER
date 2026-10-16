"""Regression boundary for the independent v20 runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent
V19_ROOT_FILES = {
    "go19.sh",
    "go_v0.19.0.sh",
    "go_mmto_photometry_v19.sh",
    "plot_mmto_variable_stars_v19.sh",
    "scripts/run_mmto_photometry_pipeline_v19.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V20RuntimeBoundaryTests(unittest.TestCase):
    def test_mmto_launcher_pins_the_canonical_results_directory(self):
        completed = subprocess.run(
            ["bash", "-x", str(ROOT / "go_mmto_photometry_v20.sh"), "--help"],
            cwd=Path("/tmp"),
            env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(f"--results-dir {ROOT / 'results'}", completed.stdout)

    def test_v20_launchers_report_0200(self):
        for name in ("go20.sh", "go_v0.20.0.sh"):
            launcher = ROOT / name
            completed = subprocess.run(
                [str(launcher), "--version"],
                cwd=ROOT,
                env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("0.20.0", completed.stdout)
            self.assertNotIn("does not match the project environment", completed.stdout)

    def test_v20_manifest_is_complete_and_based_on_frozen_v19(self):
        package = ROOT / "v20"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.20.0")
        self.assertEqual(manifest["based_on_version"], "0.19.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v19-runtime.json")
        actual = {
            path.relative_to(package).as_posix(): _sha256(path)
            for path in package.rglob("*")
            if path.is_file()
            and path.name != "SOURCE_MANIFEST.json"
            and ".venv" not in path.parts
            and "__pycache__" not in path.parts
        }
        self.assertEqual(manifest["sha256"], dict(sorted(actual.items())))

    def test_frozen_v19_snapshot_covers_and_matches_complete_runtime(self):
        snapshot_path = ROOT / "docs/v19-runtime.json"
        snapshot = json.loads(snapshot_path.read_text())
        self.assertEqual(snapshot["version"], "0.19.0")
        self.assertEqual(snapshot["snapshot_kind"], "v19-runtime-at-v20-boundary")
        recorded = snapshot["sha256"]
        expected = V19_ROOT_FILES | {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "v19").rglob("*")
            if path.is_file()
            and ".venv" not in path.parts
            and "__pycache__" not in path.parts
        }
        self.assertEqual(set(recorded), expected)
        self.assertEqual(
            recorded,
            {name: _sha256(ROOT / name) for name in sorted(expected)},
        )


if __name__ == "__main__":
    unittest.main()
