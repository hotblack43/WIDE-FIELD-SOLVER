from __future__ import annotations

from dataclasses import asdict, fields, replace
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PROJECT))


def fixture_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript((FIXTURES / "runs.sql").read_text())
    connection.commit()
    connection.close()


def rotation_z(angle: float) -> list[list[float]]:
    cosine, sine = math.cos(angle), math.sin(angle)
    return [[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]]


def saved_camera(*, parity: str = "normal", refraction: bool = False):
    from find_planet_openorb.types import CameraReceipt

    return CameraReceipt(
        run_id="run-a", source_sha256="sha-a", source_path="/archive/a.fits", solver_version="0.23.0",
        camera={
            "model": "Barghini_2019_equations_5_6_11",
            "parameters": {
                "a0": 0.0007984783986654522, "x_o": 703.3022479285006,
                "y_o": 704.1394035202628, "x_z": 711.4210275535153,
                "y_z": 703.5262294044645, "v": 0.002041608809375814,
                "s": 0.007170980557856538, "d": 0.004991891641377306,
            },
            "reference_rotation": rotation_z(0.37), "shape": [1411, 1422],
            "detector_parity": parity, "monotonic_on_detector": True,
            "integrated_refraction": {
                "status": "accepted" if refraction else "rejected",
                "zenith_camera_unit_vector": [0.2, -0.1, 0.9746794344808963],
                "refraction_a_arcsec": 45.0 if refraction else 0.0,
                "refraction_b_arcsec": 0.1 if refraction else 0.0,
                "authoritative_camera_state": True,
            },
        },
    )


class ControlledSelectionTests(unittest.TestCase):
    def test_exact_audit_hash_and_mars_only_selection(self) -> None:
        from find_planet_openorb.extract_controlled import ControlledExtractionError, select_answer_key_rows

        audit = FIXTURES / "controlled_audit.csv"
        with self.assertRaisesRegex(ControlledExtractionError, "SHA-256"):
            select_answer_key_rows(audit, "0" * 64)
        selected, audited = select_answer_key_rows(audit, fixture_hash(audit))
        self.assertEqual([row.source_sha256 for row in selected], ["sha-a", "sha-c"])
        self.assertEqual(len(audited), 5)
        by_run = {row["run_id"]: row for row in audited}
        self.assertEqual(by_run["run-s"]["answer_key_selection_reason"], "different_answer_key_object")
        self.assertEqual(by_run["run-a-copy"]["answer_key_selection_reason"], "duplicate_source_sha256")
        self.assertEqual(by_run["run-b"]["answer_key_selection_reason"], "metadata_association_unavailable")

    def test_both_saturation_schemas_and_atomic_complete_audit(self) -> None:
        from find_planet_openorb.extract_controlled import select_answer_key_rows, write_answer_key_audit

        source = FIXTURES / "controlled_audit.csv"
        with source.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["saturation_known"] = "True"
            row["channel_saturated"] = row.pop("saturated")
        with tempfile.TemporaryDirectory() as temporary:
            audit = Path(temporary) / "audit.csv"
            with audit.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            selected, audited = select_answer_key_rows(audit, fixture_hash(audit))
            output = Path(temporary) / "answer-key.csv"
            write_answer_key_audit(output, audited)
            self.assertFalse(output.with_name(f".{output.name}.tmp").exists())
            with output.open(newline="") as handle:
                written = list(csv.DictReader(handle))
        self.assertEqual([row.saturated for row in selected], [False, False])
        self.assertEqual(len(written), len(rows))

    def test_selected_and_anonymous_types_have_no_identity_answer_fields(self) -> None:
        from find_planet_openorb.types import AnonymousDirection, SelectedCentroid

        names = " ".join(field.name.lower() for cls in (SelectedCentroid, AnonymousDirection) for field in fields(cls))
        for forbidden in ("planet", "mars", "predicted", "horizons", "known_range", "known_elements"):
            self.assertNotIn(forbidden, names)


class ExactReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        from find_planet_openorb.extract_controlled import select_answer_key_rows

        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "runs.sqlite"
        fixture_database(self.database)
        audit = FIXTURES / "controlled_audit.csv"
        self.selected, _ = select_answer_key_rows(audit, fixture_hash(audit))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_run_id_success_and_source_hash_are_required(self) -> None:
        from find_planet_openorb.extract_controlled import load_exact_receipts

        receipts = load_exact_receipts(self.database, self.selected)
        self.assertEqual(set(receipts), {"run-a", "run-c"})
        self.assertEqual(receipts["run-c"].solver_version, "0.21.0")

    def test_missing_failed_duplicate_mismatch_and_malformed_are_rejected(self) -> None:
        from find_planet_openorb.extract_controlled import ControlledExtractionError, load_exact_receipts

        from find_planet_openorb.types import SelectedCentroid
        connection = sqlite3.connect(self.database)
        camera = json.dumps({"camera": {"model": "Barghini_2019_equations_5_6_11"}})
        for values in (
            ("failed", "sha-a", 1, camera), ("mismatch", "other", 0, camera),
            ("duplicate", "sha-a", 0, camera), ("duplicate", "sha-a", 0, camera),
            ("malformed", "sha-a", 0, "{}"),
        ):
            connection.execute("INSERT INTO runs VALUES (?, '/archive/a.fits', ?, ?, '0.23.0', ?)", values)
        connection.commit(); connection.close()
        base = self.selected[0]
        cases = {"missing": "exactly one", "failed": "failed", "mismatch": "source SHA", "duplicate": "exactly one", "malformed": "camera"}
        for run_id, message in cases.items():
            row = SelectedCentroid(**(asdict(base) | {"run_id": run_id, "source_sha256": "sha-a"}))
            with self.subTest(run_id=run_id), self.assertRaisesRegex(ControlledExtractionError, message):
                load_exact_receipts(self.database, [row])


class CameraTests(unittest.TestCase):
    def test_detector_round_trip_parity_and_integrated_refraction_once(self) -> None:
        from find_planet_openorb.barghini import camera_to_icrs_unit, icrs_unit_to_camera

        point = np.array([921.25, 488.75])
        for camera in (saved_camera(), saved_camera(parity="mirrored"), saved_camera(refraction=True)):
            unit = camera_to_icrs_unit(camera, *point)
            np.testing.assert_allclose(np.linalg.norm(unit), 1.0, atol=1e-12)
            np.testing.assert_allclose(icrs_unit_to_camera(camera, unit), point, atol=1e-6)
        normal = camera_to_icrs_unit(saved_camera(), *point)
        mirrored = camera_to_icrs_unit(saved_camera(parity="mirrored"), *point)
        rotation = np.asarray(saved_camera().camera["reference_rotation"])
        np.testing.assert_allclose((normal @ rotation)[[0, 2]], (mirrored @ rotation)[[0, 2]], atol=1e-12)
        self.assertAlmostEqual((normal @ rotation)[1], -(mirrored @ rotation)[1], places=12)

    def test_unused_corners_beyond_pi_do_not_reject_valid_centroid(self) -> None:
        from find_planet_openorb.barghini import camera_to_icrs_unit, icrs_unit_to_camera

        receipt = saved_camera(parity="mirrored")
        camera = dict(receipt.camera)
        camera["parameters"] = {
            "a0": 0.000204341536069043, "x_o": 703.3870008841685, "y_o": 704.1050078630846,
            "x_z": 711.018585075199, "y_z": 704.8535055092319, "v": 0.002040293638509593,
            "s": 0.007262815473162861, "d": 0.004991891641377516,
        }
        receipt = replace(receipt, camera=camera)
        point = np.array([140.2352314653957, 875.6935295904382])
        unit = camera_to_icrs_unit(receipt, *point)
        np.testing.assert_allclose(icrs_unit_to_camera(receipt, unit), point, atol=1e-6)

    def test_real_near_domain_edge_derefracts_without_prediction(self) -> None:
        from find_planet_openorb.barghini import camera_to_icrs_unit

        receipt = saved_camera(parity="mirrored")
        camera = dict(receipt.camera)
        camera["parameters"] = {
            "a0": 0.0002702816649397473, "x_o": 703.325395364717, "y_o": 704.2905635022753,
            "x_z": 710.7602973372617, "y_z": 704.7036574769148, "v": 0.0020405253305903984,
            "s": 0.007112586540401267, "d": 0.004991891641377516,
        }
        camera["reference_rotation"] = [[0.6692437719548714,0.3602160984371432,0.6498900954210175],[-0.7424093736290238,0.3602728760054991,0.5648289801014881],[-0.030677282268429782,-0.8604927758217662,0.5085381864827604]]
        camera["integrated_refraction"] = {"status":"adopted","zenith_camera_unit_vector":[0.13923288495673072,0.07065693185215924,0.9877356942663685],"refraction_a_arcsec":148.98571498782158,"refraction_b_arcsec":-0.164703733946742,"authoritative_camera_state":True}
        unit = camera_to_icrs_unit(replace(receipt, camera=camera), 110.65609889374196, 865.5617499816681)
        self.assertTrue(np.isfinite(unit).all())

    def test_anonymous_rows_ignore_any_predicted_fixture_attributes(self) -> None:
        from types import SimpleNamespace
        from find_planet_openorb.barghini import anonymous_direction_rows
        from find_planet_openorb.types import SelectedCentroid

        selected = SelectedCentroid("run-a", "sha-a", "/archive/a.fits", "2026-09-01", "2026-09-02T03:00:00Z", "10", 921.25, 488.75, 2.0, "compact", False)
        first = SimpleNamespace(**asdict(selected), predicted_x_px=-1e9)
        second = SimpleNamespace(**asdict(selected), predicted_x_px=17.0)
        receipts = {"run-a": saved_camera()}
        self.assertEqual(anonymous_direction_rows([first], receipts), anonymous_direction_rows([second], receipts))


if __name__ == "__main__":
    unittest.main()
