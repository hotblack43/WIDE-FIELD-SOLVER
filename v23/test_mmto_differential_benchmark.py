"""End-to-end benchmark product regressions on a deterministic fixture."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch

from v23.mmto_differential_benchmark import run_benchmark
from v23.mmto_differential_features import FeatureRow, FeatureTable
from v23.test_mmto_planet_relative_photometry import _context


def _fixture_table() -> FeatureTable:
    base = _context(comparison_count=40)
    rows = []
    roles = ("train", "train", "train", "train", "validation", "validation", "test", "test")
    nuisance_by_night = (-0.6, -0.2, 0.2, 0.6, -0.5, 0.5, -0.4, 0.4)
    for channel in "RGB":
        for night_index, (role, nuisance) in enumerate(zip(roles, nuisance_by_night, strict=True)):
            for star_index in range(10):
                rows.append(
                    FeatureRow(
                        run_id=f"run-{night_index}",
                        source_sha256=f"{night_index:064x}",
                        observed_utc=f"2026-01-{night_index + 1:02d}T00:00:00+00:00",
                        night=f"2026-01-{night_index + 1:02d}",
                        catalogue_sha256="c" * 64,
                        star_id=f"star-{star_index}",
                        channel=channel,
                        role=role,
                        night_role=role,
                        star_role=role,
                        spatial_block="1:1",
                        target_delta_magnitude=nuisance,
                        metric_target_magnitude=nuisance,
                        raw_control_magnitude=nuisance,
                        v21_control_magnitude=0.8 * nuisance,
                        deployable_features=(0.0,),
                        diagnostic_features=(-5.0, 5.0, 1.0, nuisance, 0.0, 1.5, float("nan")),
                        exposure_median_magnitude=nuisance,
                        exposure_mad_magnitude=0.01,
                        exposure_count=40,
                        local_median_128_px=nuisance,
                        local_mad_128_px=0.01,
                        local_count_128_px=12,
                        local_median_256_px=nuisance,
                        local_mad_256_px=0.01,
                        local_count_256_px=20,
                        local_median_512_px=nuisance,
                        local_mad_512_px=0.01,
                        local_count_512_px=30,
                    )
                )
    return FeatureTable(
        rows=tuple(rows),
        assignments=(),
        deployable_feature_names=("x_normalized",),
        diagnostic_feature_names=(
            "machine_magnitude",
            "catalogue_magnitude",
            "gaia_bp_minus_rp",
            "airmass",
            "radius_normalized",
            "major_sigma_px",
            "aperture_background_adu",
        ),
        comparison_residuals=base.comparison_residuals,
        star_baselines=MappingProxyType({}),
        v21_baselines=MappingProxyType({}),
        data=base.data,
        control=base.control,
        config=MappingProxyType(
            {"minimum_local_comparisons": 12, "minimum_exposure_comparisons": 30}
        ),
    )


def _config(path: Path, *, impossible: bool = False) -> Path:
    path.write_text(
        json.dumps(
            {
                "comparison_radii_px": [128, 256, 512],
                "minimum_local_comparisons": 12,
                "minimum_exposure_comparisons": 30,
                "improvement_fraction": 1.1 if impossible else 0.05,
                "maximum_planet_stratum_degradation_fraction": 0.02,
                "maximum_signal_attenuation_fraction": 0.05,
                "bootstrap_resamples": 20,
                "random_forest_trees": 5,
                "random_forest_min_samples_leaf": [2],
                "gradient_boosting_iterations": 5,
                "gradient_boosting_leaf_counts": [3],
                "mlp_hidden_layers": [[4]],
                "mlp_alpha": [0.001],
                "mlp_max_iterations": 20,
                "maximum_tuning_rows_per_channel": 100,
                "maximum_training_rows_per_channel": 100,
            },
            sort_keys=True,
        )
    )
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DifferentialBenchmarkTests(unittest.TestCase):
    def test_launcher_help_pins_the_v23_environment(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [str(root / "run_v23_photometry_benchmark.sh"), "--help"],
            cwd=Path("/tmp"),
            env=dict(os.environ, VIRTUAL_ENV="/wrong/environment"),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("--v21-control", completed.stdout)
        self.assertNotIn("wrong/environment", completed.stdout)

    def _run(self, root: Path, name: str, *, impossible: bool = False):
        table = _fixture_table()
        config = _config(root / f"{name}.json", impossible=impossible)
        with (
            patch("v23.mmto_differential_benchmark.load_v21_control", return_value=table.control),
            patch("v23.mmto_differential_benchmark.load_measurements", return_value=table.data),
            patch("v23.mmto_differential_benchmark.assign_splits", return_value=()),
            patch("v23.mmto_differential_benchmark.build_feature_table", return_value=table),
        ):
            return run_benchmark(
                Path("/read-only/stars.sqlite"),
                Path("/read-only/manifest.sqlite"),
                Path("/read-only/v21-control"),
                root / name,
                config,
            )

    def test_known_nuisance_selects_local_and_writes_stable_products(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._run(root, "one")
            second = self._run(root, "two")
            self.assertTrue(first.correction_available)
            self.assertEqual(first.selected_method, "local_ensemble")
            self.assertEqual(first, second)
            for filename in (
                "benchmark_summary.json",
                "planet_relative_photometry.csv",
                "validation_metrics.json",
            ):
                self.assertEqual(_sha(root / "one" / filename), _sha(root / "two" / filename))
            for filename in (
                "residual_diagnostics.pdf",
                "model_comparison.pdf",
                "signal_recovery.pdf",
                "planet_relative_lightcurves.pdf",
            ):
                self.assertGreater((root / "one" / filename).stat().st_size, 1000)

    def test_failed_gate_retains_planets_without_v23_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = self._run(root, "failed", impossible=True)
            self.assertFalse(summary.correction_available)
            text = (root / "failed" / "planet_relative_photometry.csv").read_text()
            self.assertIn("model_unavailable", text)
            self.assertIn("raw_machine_magnitude", text)

    def test_nonempty_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "occupied"
            output.mkdir()
            (output / "keep.txt").write_text("keep")
            with self.assertRaises(FileExistsError):
                self._run(root, "occupied")
            self.assertEqual((output / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
