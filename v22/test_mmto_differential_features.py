"""Leakage-resistant feature and split regressions for v22."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType
import tempfile
import unittest

from v22.mmto_differential_data import (
    MeasurementSet,
    RunRecord,
    StellarMeasurement,
    V21Control,
)
from v22.mmto_differential_features import (
    SplitAssignment,
    assign_splits,
    build_feature_table,
    inject_signals,
    write_feature_audit,
)


def _run(index: int, night: str) -> RunRecord:
    return RunRecord(
        run_id=f"run-{index}",
        recorded_at_utc=f"{night}T08:00:00+00:00",
        source_path=f"/{index}.fits",
        source_sha256=f"{index:064x}",
        analysis_path=f"/{index}/analysis",
        solver_version="0.21.0",
        catalogue_sha256="c" * 64,
        observed_utc=f"{night}T08:00:00+00:00",
        night=night,
        width_px=1000,
        height_px=800,
        global_noise_adu=2.0,
        exposure_seconds=20.0,
    )


def _star(
    run: RunRecord,
    star_id: str,
    machine_magnitude: float,
    *,
    x: float,
    y: float,
    channel: str = "R",
    colour: float | None = 1.0,
) -> StellarMeasurement:
    rate = 10 ** (-machine_magnitude / 2.5)
    return StellarMeasurement(
        run_id=run.run_id,
        source_sha256=run.source_sha256,
        observed_utc=run.observed_utc,
        night=run.night,
        catalogue_sha256=run.catalogue_sha256,
        star_id=star_id,
        detection_id=f"{star_id}-{run.run_id}",
        channel=channel,
        catalogue_magnitude=5.0,
        count_rate_adu_per_s=rate,
        machine_magnitude=machine_magnitude,
        airmass=1.2,
        x_px=x,
        y_px=y,
        image_width_px=run.width_px,
        image_height_px=run.height_px,
        source_class="compact",
        exposure_seconds=20.0,
        flux_adu=rate * 20.0,
        saturation_known=True,
        saturated=False,
        measurement_method="ordinary_aperture",
        area_px=20.0,
        major_sigma_px=1.5,
        axis_ratio=1.1,
        peak_snr=30.0,
        aperture_radius_px=3.75,
        aperture_background_adu=None,
        global_noise_adu=2.0,
        gaia_bp_magnitude=(6.0 if colour is not None else None),
        gaia_rp_magnitude=(6.0 - colour if colour is not None else None),
        gaia_bp_minus_rp=colour,
    )


def _data(runs: list[RunRecord], stars: list[StellarMeasurement]) -> MeasurementSet:
    return MeasurementSet(
        runs=tuple(runs),
        stellar=tuple(stars),
        planets=(),
        audit=(),
        database_path="/fixture/stars.sqlite",
        manifest_path="/fixture/manifest.sqlite",
        database_sha256="d" * 64,
        manifest_sha256="m" * 64,
        input_solver_version="0.21.0",
    )


def _control(runs: list[RunRecord]) -> V21Control:
    return V21Control(
        selected_run_ids=frozenset(run.run_id for run in runs),
        adopted_model="fixture",
        corrected_magnitudes=MappingProxyType({}),
        extinction_coefficients=MappingProxyType({}),
        manifest_sha256="1" * 64,
        corrected_photometry_sha256="2" * 64,
        coefficients_sha256="3" * 64,
    )


def _context_fixture(target_delta: float = 9.0):
    runs = [_run(0, "2026-01-01"), _run(1, "2026-01-02")]
    stars = [
        _star(runs[0], "target", 10.0, x=500.0, y=400.0),
        _star(runs[0], "comparison-a", 5.0, x=480.0, y=400.0),
        _star(runs[0], "comparison-b", 6.0, x=520.0, y=400.0),
        _star(runs[1], "target", 10.0 + target_delta, x=500.0, y=400.0),
        _star(runs[1], "comparison-a", 5.2, x=480.0, y=400.0),
        _star(runs[1], "comparison-b", 6.2, x=520.0, y=400.0),
    ]
    assignments = []
    for row in stars:
        assignments.append(
            SplitAssignment(
                run_id=row.run_id,
                catalogue_sha256=row.catalogue_sha256,
                star_id=row.star_id,
                channel=row.channel,
                night=row.night,
                night_role="train" if row.night == "2026-01-01" else "validation",
                star_role="validation" if row.star_id == "target" else "train",
                spatial_block="4:3",
            )
        )
    config = {
        "comparison_radii_px": [128, 256, 512],
        "minimum_local_comparisons": 1,
        "minimum_exposure_comparisons": 1,
    }
    data = _data(runs, stars)
    return build_feature_table(data, _control(runs), assignments, config)


class DifferentialFeatureTests(unittest.TestCase):
    def test_splits_are_deterministic_independent_and_sixty_twenty_twenty(self):
        runs = [_run(index, f"2026-01-{index + 1:02d}") for index in range(10)]
        stars = [
            _star(run, f"star-{star}", 5.0 + star / 10, x=50.0 * star, y=100.0)
            for run in runs
            for star in range(10)
        ]
        data = _data(runs, stars)
        first = assign_splits(data, seed=2201)
        self.assertEqual(first, assign_splits(data, seed=2201))
        night_roles = {run.night: set() for run in runs}
        star_roles = {f"star-{star}": set() for star in range(10)}
        for row in first:
            night_roles[row.night].add(row.night_role)
            star_roles[row.star_id].add(row.star_role)
        self.assertTrue(all(len(roles) == 1 for roles in night_roles.values()))
        self.assertTrue(all(len(roles) == 1 for roles in star_roles.values()))
        self.assertEqual(
            sorted(next(iter(roles)) for roles in night_roles.values()).count("train"), 6
        )
        self.assertEqual(
            sorted(next(iter(roles)) for roles in night_roles.values()).count("validation"),
            2,
        )
        self.assertEqual(
            sorted(next(iter(roles)) for roles in night_roles.values()).count("test"), 2
        )
        self.assertEqual(
            sorted(next(iter(roles)) for roles in star_roles.values()).count("train"), 6
        )

    def test_held_star_identities_never_enter_an_earlier_role(self):
        runs = [_run(index, f"2026-02-{index + 1:02d}") for index in range(6)]
        stars = [
            _star(run, f"star-{star}", 5.0, x=100.0 + star, y=200.0)
            for run in runs
            for star in range(6)
        ]
        assignments = assign_splits(_data(runs, stars))
        for row in assignments:
            if row.star_role == "validation":
                self.assertNotEqual(row.role, "train")
            if row.star_role == "test":
                self.assertEqual(row.role, "test")

    def test_target_is_not_its_own_weather_station(self):
        ordinary = _context_fixture(target_delta=9.0)
        extreme = _context_fixture(target_delta=99.0)
        target = next(
            row
            for row in ordinary.rows
            if row.star_id == "target" and row.night == "2026-01-02"
        )
        changed = next(
            row
            for row in extreme.rows
            if row.star_id == "target" and row.night == "2026-01-02"
        )
        self.assertAlmostEqual(target.local_median_256_px, 0.2)
        self.assertEqual(target.local_median_256_px, changed.local_median_256_px)
        self.assertAlmostEqual(target.target_delta_magnitude, 9.0)

    def test_deployable_features_exclude_current_brightness_and_stellar_colour(self):
        table = _context_fixture()
        forbidden = {
            "machine_magnitude",
            "count_rate_adu_per_s",
            "catalogue_magnitude",
            "gaia_bp_minus_rp",
        }
        self.assertTrue(forbidden.isdisjoint(table.deployable_feature_names))
        self.assertIn("gaia_bp_minus_rp", table.diagnostic_feature_names)
        self.assertIn("machine_magnitude", table.diagnostic_feature_names)
        self.assertNotIn("aperture_background_adu", table.deployable_feature_names)

    def test_comparison_residuals_use_train_night_baselines_only(self):
        table = _context_fixture()
        target = next(
            row
            for row in table.rows
            if row.star_id == "target" and row.night == "2026-01-02"
        )
        self.assertAlmostEqual(target.exposure_median_magnitude, 0.2)
        self.assertAlmostEqual(target.local_mad_128_px, 0.0)
        self.assertEqual(target.local_count_128_px, 2)

    def test_signal_injection_is_after_feature_construction_and_reproducible(self):
        table = _context_fixture()
        first = inject_signals(table, seed=2202)
        second = inject_signals(table, seed=2202)
        self.assertEqual(first, second)
        self.assertTrue(first.rows)
        for injected in first.rows:
            original = table.rows[injected.row_index]
            self.assertEqual(injected.features, original.deployable_features)
            self.assertAlmostEqual(
                injected.injected_target_magnitude,
                original.target_delta_magnitude + injected.signal_magnitude,
            )

    def test_feature_audit_outputs_are_stable(self):
        table = _context_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_feature_audit(table, root / "one")
            write_feature_audit(table, root / "two")
            for name in ("fold_assignments.csv", "feature_manifest.json"):
                first = hashlib.sha256((root / "one" / name).read_bytes()).hexdigest()
                second = hashlib.sha256((root / "two" / name).read_bytes()).hexdigest()
                self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
