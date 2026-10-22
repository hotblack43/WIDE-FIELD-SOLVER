"""Read-only, auditable v22 differential-photometry input tests."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from v22.mmto_differential_data import (
    PlanetMeasurement,
    load_measurements,
    load_v21_control,
    require_matching_runs,
    write_input_audit,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "v22/data/stars_gaia_dr3_g75.csv"
CATALOGUE_SHA256 = hashlib.sha256(CATALOGUE.read_bytes()).hexdigest()
STAR_ID = "Gaia DR3 132667245587072"
SOURCE_SHA256 = "a" * 64


def _json(values: dict[str, object]) -> str:
    return json.dumps(values, sort_keys=True)


def _measurement(
    connection: sqlite3.Connection,
    run_id: str,
    product: str,
    row_number: int,
    values: dict[str, object],
    *,
    star_id: str | None = None,
    detection_id: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
        (run_id, product, row_number, star_id, detection_id, _json(values)),
    )


def _insert_products(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    rate: float,
    duplicate_join: bool = False,
) -> None:
    detection = {
        "width_px": 1000,
        "height_px": 800,
        "global_noise_adu": 2.5,
        "input_image": {"exposure": {"status": "available", "seconds": 20.0}},
    }
    connection.execute(
        "INSERT INTO products VALUES (?,?,?,?)",
        (run_id, "dots/detection.json", "d" * 64, json.dumps(detection).encode()),
    )
    star_photometry = {
        "catalogue_magnitude": 7.4750457,
        "airmass": 1.2,
        "saturation_known": "True",
        "source_class": "compact",
        "exposure_seconds": 20.0,
        "R_flux": rate * 20.0,
        "R_count_rate_adu_per_s": rate,
        "R_saturated": "False",
        "R_measurement_method": "aperture",
        "G_flux": rate * 22.0,
        "G_count_rate_adu_per_s": rate * 1.1,
        "G_saturated": "True",
        "G_measurement_method": "saturated_aperture_lower_bound",
        "B_flux": rate * 18.0,
        "B_count_rate_adu_per_s": rate * 0.9,
        "B_saturated": "False",
        "B_measurement_method": "unavailable",
    }
    source_star = {
        "detection_id": "d1",
        "star_id": STAR_ID,
        "x_px": 400.0,
        "y_px": 300.0,
        "source_class": "compact",
        "exposure_seconds": 20.0,
    }
    coordinate = {
        "detection_id": "d1",
        "star_id": STAR_ID,
        "x_px": 400.0,
        "y_px": 300.0,
        "usage": "fitted",
    }
    candidate_star = {
        "detection_id": "d1",
        "x_px": 400.0,
        "y_px": 300.0,
        "area_px": 19,
        "major_sigma_px": 1.6,
        "axis_ratio": 1.1,
        "peak_snr": 30.0,
        "source_class": "compact",
    }
    source_planet = {
        "detection_id": "d2",
        "x_px": 500.0,
        "y_px": 350.0,
        "source_class": "compact",
        "exposure_seconds": 20.0,
    }
    candidate_planet = {
        "detection_id": "d2",
        "x_px": 500.0,
        "y_px": 350.0,
        "area_px": 21,
        "major_sigma_px": 1.8,
        "axis_ratio": 1.2,
        "peak_snr": 25.0,
        "source_class": "compact",
    }
    planet = {
        "identity_type": "major_planet",
        "identity_name": "Jupiter",
        "identity_status": "planet_candidate",
        "candidate_rank": 1,
        "epoch_tdb": "2026-01-01T00:00:00 TDB",
        "detection_id": "d2",
        "x_px": 500.0,
        "y_px": 350.0,
        "source_class": "compact",
        "saturation_known": "True",
        "exposure_seconds": 20.0,
        "R_flux": 2000.0,
        "R_count_rate_adu_per_s": 100.0,
        "R_saturated": "False",
        "R_measurement_method": "aperture",
        "G_flux": 2200.0,
        "G_count_rate_adu_per_s": 110.0,
        "G_saturated": "False",
        "G_measurement_method": "aperture",
        "B_flux": 1800.0,
        "B_count_rate_adu_per_s": 90.0,
        "B_saturated": "False",
        "B_measurement_method": "aperture",
    }
    rows = (
        ("stellar_photometry.csv", 1, star_photometry, STAR_ID, "d1"),
        ("source_photometry.csv", 1, source_star, STAR_ID, "d1"),
        ("source_photometry.csv", 2, source_planet, None, "d2"),
        ("star_coordinates.csv", 1, coordinate, STAR_ID, "d1"),
        ("dots/star_candidates.csv", 1, candidate_star, None, "d1"),
        ("dots/star_candidates.csv", 2, candidate_planet, None, "d2"),
        ("identified_source_photometry.csv", 1, planet, None, "d2"),
    )
    for product, number, values, star_id, detection_id in rows:
        _measurement(
            connection,
            run_id,
            product,
            number,
            values,
            star_id=star_id,
            detection_id=detection_id,
        )
    if duplicate_join:
        _measurement(
            connection,
            run_id,
            "star_coordinates.csv",
            2,
            coordinate,
            star_id=STAR_ID,
            detection_id="d1",
        )


def _fixture(root: Path, *, duplicate_join: bool = False) -> tuple[Path, Path]:
    database = root / "stars.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE runs (
          run_id TEXT PRIMARY KEY, recorded_at_utc TEXT NOT NULL,
          source_path TEXT NOT NULL, source_sha256 TEXT,
          analysis_path TEXT NOT NULL, exit_code INTEGER NOT NULL,
          error TEXT, solver_version TEXT, catalogue_sha256 TEXT,
          solver_status TEXT, result_json TEXT, recorder_sha256 TEXT NOT NULL,
          source_manifest_json TEXT
        );
        CREATE TABLE products (
          run_id TEXT, product TEXT, sha256 TEXT, content BLOB,
          PRIMARY KEY (run_id, product)
        );
        CREATE TABLE measurements (
          run_id TEXT, product TEXT, row_number INTEGER, star_id TEXT,
          detection_id TEXT, values_json TEXT,
          PRIMARY KEY (run_id, product, row_number)
        );
        """
    )
    runs = (
        ("old", "2026-01-01T00:00:00+00:00", 0, "0.21.0", 80.0),
        ("new", "2026-01-02T00:00:00+00:00", 0, "0.21.0", 100.0),
        ("failed", "2026-01-03T00:00:00+00:00", 1, "0.21.0", None),
    )
    for run_id, recorded, exit_code, version, rate in runs:
        connection.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                recorded,
                f"/{run_id}.fits",
                SOURCE_SHA256,
                f"/{run_id}/analysis",
                exit_code,
                None,
                version,
                CATALOGUE_SHA256,
                "point_star_fit_converged" if exit_code == 0 else None,
                "{}",
                "r" * 64,
                "{}",
            ),
        )
        if rate is not None:
            _insert_products(
                connection,
                run_id,
                rate=rate,
                duplicate_join=duplicate_join and run_id == "new",
            )
    connection.commit()
    connection.close()

    manifest = root / "manifest.sqlite"
    connection = sqlite3.connect(manifest)
    connection.execute(
        """CREATE TABLE mmto_v21_observations (
        source_sha256 TEXT PRIMARY KEY, remote_url TEXT NOT NULL,
        discovery_utc TEXT NOT NULL, header_start_utc TEXT NOT NULL,
        header_midpoint_utc TEXT NOT NULL, exposure_seconds REAL NOT NULL,
        header_schema TEXT NOT NULL, provenance TEXT NOT NULL,
        instrument TEXT NOT NULL, recorded_utc TEXT NOT NULL)"""
    )
    connection.execute(
        "INSERT INTO mmto_v21_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            SOURCE_SHA256,
            "https://example.invalid/image",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T01:00:00+00:00",
            "2026-01-01T01:00:10+00:00",
            20.0,
            "DATE-OBS+EXPOSURE",
            "fixture",
            "MMTO",
            "2026-01-01T02:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()
    return database, manifest


def _control(root: Path, selected_run_ids: list[str]) -> Path:
    directory = root / "control"
    directory.mkdir()
    (directory / "calibration_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 5,
                "adopted_model": "adopted",
                "selected_run_ids": selected_run_ids,
            }
        )
    )
    with (directory / "corrected_stellar_photometry.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "run_id",
                "source_sha256",
                "catalogue_sha256",
                "star_id",
                "channel",
                "machine_magnitude",
                "corrected_magnitude",
                "status",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_id": selected_run_ids[0],
                "source_sha256": SOURCE_SHA256,
                "catalogue_sha256": CATALOGUE_SHA256,
                "star_id": STAR_ID,
                "channel": "R",
                "machine_magnitude": -5.0,
                "corrected_magnitude": -5.2,
                "status": "accepted",
            }
        )
    with (directory / "nightly_extinction_coefficients.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "night",
                "channel",
                "catalogue_sha256",
                "model",
                "status",
                "extinction_mag_per_airmass",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "night": "2025-12-31",
                "channel": "R",
                "catalogue_sha256": CATALOGUE_SHA256,
                "model": "rejected_alternative",
                "status": "accepted",
                "extinction_mag_per_airmass": 9.9,
            }
        )
        writer.writerow(
            {
                "night": "2025-12-31",
                "channel": "R",
                "catalogue_sha256": CATALOGUE_SHA256,
                "model": "adopted",
                "status": "accepted",
                "extinction_mag_per_airmass": 0.2,
            }
        )
    return directory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DifferentialDataTests(unittest.TestCase):
    def test_latest_success_is_selected_and_exact_ids_replay_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, manifest = _fixture(Path(temporary))
            latest = load_measurements(database, manifest)
            self.assertEqual([run.run_id for run in latest.runs], ["new"])
            self.assertEqual(latest.stellar[0].count_rate_adu_per_s, 100.0)
            replay = load_measurements(database, manifest, run_ids=frozenset({"old"}))
            self.assertEqual([run.run_id for run in replay.runs], ["old"])
            self.assertEqual(replay.stellar[0].count_rate_adu_per_s, 80.0)

    def test_only_unsaturated_ordinary_apertures_enter_stellar_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, manifest = _fixture(Path(temporary))
            loaded = load_measurements(database, manifest)
            self.assertEqual([row.channel for row in loaded.stellar], ["R"])
            reasons = {reason for row in loaded.audit for reason in row.exclusion_reasons}
            self.assertIn("channel_saturated", reasons)
            self.assertIn("not_ordinary_aperture", reasons)

    def test_missing_historical_background_remains_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, manifest = _fixture(Path(temporary))
            row = load_measurements(database, manifest).stellar[0]
            self.assertIsNone(row.aperture_background_adu)
            self.assertNotIn("aperture_background_adu", row.deployable_features())
            self.assertAlmostEqual(row.gaia_bp_minus_rp, 8.025092 - 6.7722306)

    def test_non_unique_detection_join_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, manifest = _fixture(Path(temporary), duplicate_join=True)
            with self.assertRaisesRegex(ValueError, "non-unique detection join"):
                load_measurements(database, manifest)

    def test_planets_are_separate_and_retain_all_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, manifest = _fixture(Path(temporary))
            loaded = load_measurements(database, manifest)
            self.assertEqual(len(loaded.planets), 3)
            self.assertTrue(all(isinstance(row, PlanetMeasurement) for row in loaded.planets))
            self.assertEqual({row.identity_name for row in loaded.planets}, {"Jupiter"})
            self.assertFalse(any(hasattr(row, "identity_name") for row in loaded.stellar))

    def test_control_keeps_only_the_recorded_adopted_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = load_v21_control(_control(root, ["new"]))
            self.assertEqual(control.selected_run_ids, frozenset({"new"}))
            self.assertEqual(control.adopted_model, "adopted")
            self.assertEqual(len(control.extinction_coefficients), 1)
            self.assertEqual(next(iter(control.extinction_coefficients.values())), 0.2)

    def test_control_must_describe_the_same_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, manifest = _fixture(root)
            current = load_measurements(database, manifest)
            stale = load_v21_control(_control(root, ["old"]))
            with self.assertRaisesRegex(ValueError, "control run mismatch"):
                require_matching_runs(stale, current)

    def test_inputs_are_read_only_and_audits_are_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database, manifest = _fixture(root)
            before = (_sha256(database), _sha256(manifest))
            first = load_measurements(database, manifest)
            second = load_measurements(database, manifest)
            self.assertEqual(before, (_sha256(database), _sha256(manifest)))
            self.assertEqual(first.database_sha256, second.database_sha256)
            self.assertEqual(first.manifest_sha256, second.manifest_sha256)
            write_input_audit(first, root / "audit-one")
            write_input_audit(second, root / "audit-two")
            for name in ("input_runs.csv", "measurement_audit.csv"):
                self.assertEqual(
                    _sha256(root / "audit-one" / name),
                    _sha256(root / "audit-two" / name),
                )


if __name__ == "__main__":
    unittest.main()
