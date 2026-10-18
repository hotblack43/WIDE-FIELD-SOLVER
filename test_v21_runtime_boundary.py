"""Regression boundary for the independent v21 runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent
V20_ROOT_FILES = {
    "go20.sh",
    "go_v0.20.0.sh",
    "go_mmto_photometry_v20.sh",
    "plot_mmto_variable_stars_v20.sh",
    "scripts/run_mmto_photometry_pipeline_v20.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V21RuntimeBoundaryTests(unittest.TestCase):
    def test_mmto_launcher_pins_the_canonical_results_directory(self):
        completed = subprocess.run(
            ["bash", "-x", str(ROOT / "go_mmto_photometry_v21.sh"), "--help"],
            cwd=Path("/tmp"),
            env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(f"--results-dir {ROOT / 'results'}", completed.stdout)

    def test_v21_launchers_report_0210(self):
        for name in ("go21.sh", "go_v0.21.0.sh"):
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
            self.assertIn("0.21.0", completed.stdout)
            self.assertNotIn("does not match the project environment", completed.stdout)

    def test_v21_manifest_is_complete_and_based_on_frozen_v20(self):
        package = ROOT / "v21"
        manifest = json.loads((package / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.21.0")
        self.assertEqual(manifest["based_on_version"], "0.20.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v20-runtime.json")
        actual = {
            path.relative_to(package).as_posix(): _sha256(path)
            for path in package.rglob("*")
            if path.is_file()
            and path.name != "SOURCE_MANIFEST.json"
            and ".venv" not in path.parts
            and "__pycache__" not in path.parts
        }
        self.assertEqual(manifest["sha256"], dict(sorted(actual.items())))

    def test_v21_inherited_scientific_data_match_frozen_parent(self):
        """Version substitutions must not alter inherited catalogue payloads."""
        parent_data = ROOT / "v20" / "data"
        child_data = ROOT / "v21" / "data"
        inherited = {
            path.relative_to(parent_data)
            for path in parent_data.rglob("*")
            if path.is_file() and path.name != "README.md"
        }
        self.assertEqual(
            inherited,
            {
                path.relative_to(child_data)
                for path in child_data.rglob("*")
                if path.is_file() and path.name != "README.md"
            },
        )
        for relative_path in sorted(inherited):
            self.assertEqual(
                _sha256(child_data / relative_path),
                _sha256(parent_data / relative_path),
                f"inherited scientific data changed: {relative_path}",
            )

    def test_v21_vsx_crossmatch_matches_recorded_provenance(self):
        data = ROOT / "v21" / "data"
        provenance = json.loads(
            (data / "vsx_crossmatch.provenance.json").read_text()
        )
        self.assertEqual(
            _sha256(data / "vsx_crossmatch.csv"),
            provenance["output_csv_sha256"],
        )

    def test_frozen_v20_snapshot_covers_and_matches_complete_runtime(self):
        snapshot_path = ROOT / "docs/v20-runtime.json"
        snapshot = json.loads(snapshot_path.read_text())
        self.assertEqual(snapshot["version"], "0.20.0")
        self.assertEqual(snapshot["snapshot_kind"], "v20-runtime-at-v21-boundary")
        recorded = snapshot["sha256"]
        expected = V20_ROOT_FILES | {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "v20").rglob("*")
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
