from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.barghini import (
    anonymous_direction_rows,
    camera_to_icrs_unit,
    icrs_unit_to_camera,
)
from find_planet.types import CameraReceipt, SelectedCentroid


def rotation_z(angle: float) -> list[list[float]]:
    c = math.cos(angle)
    s = math.sin(angle)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def saved_camera(*, parity: str = "normal", refraction: bool = False) -> CameraReceipt:
    integrated = {
        "status": "accepted" if refraction else "rejected",
        "zenith_camera_unit_vector": [0.2, -0.1, 0.9746794344808963],
        "refraction_a_arcsec": 45.0 if refraction else 0.0,
        "refraction_b_arcsec": 0.1 if refraction else 0.0,
        "authoritative_camera_state": True,
    }
    return CameraReceipt(
        run_id="run-a",
        source_sha256="sha-a",
        source_path="/archive/a.fits",
        solver_version="0.23.0",
        camera={
            "model": "Barghini_2019_equations_5_6_11",
            "parameters": {
                "a0": 0.0007984783986654522,
                "x_o": 703.3022479285006,
                "y_o": 704.1394035202628,
                "x_z": 711.4210275535153,
                "y_z": 703.5262294044645,
                "v": 0.002041608809375814,
                "s": 0.007170980557856538,
                "d": 0.004991891641377306,
            },
            "reference_rotation": rotation_z(0.37),
            "shape": [1411, 1422],
            "detector_parity": parity,
            "integrated_refraction": integrated,
            "monotonic_on_detector": True,
        },
    )


class BarghiniRoundTripTests(unittest.TestCase):
    def test_round_trip_centre_cardinal_and_near_edge_pixels(self):
        camera = saved_camera()
        points = np.array(
            [
                [703.3022479285006, 704.1394035202628],
                [1003.0, 704.0],
                [403.0, 704.0],
                [703.0, 1004.0],
                [703.0, 404.0],
                [5.0, 5.0],
                [1416.0, 5.0],
                [5.0, 1405.0],
                [1416.0, 1405.0],
            ]
        )

        units = np.array([camera_to_icrs_unit(camera, *point) for point in points])
        recovered = np.array([icrs_unit_to_camera(camera, unit) for unit in units])

        np.testing.assert_allclose(np.linalg.norm(units, axis=1), 1.0, atol=1e-12)
        np.testing.assert_allclose(recovered, points, atol=1e-6)

    def test_round_trip_applies_saved_integrated_refraction_exactly_once(self):
        camera = saved_camera(refraction=True)
        point = np.array([921.25, 488.75])

        unit = camera_to_icrs_unit(camera, *point)
        recovered = icrs_unit_to_camera(camera, unit)

        np.testing.assert_allclose(recovered, point, atol=1e-6)

    def test_real_camera_with_unused_corner_beyond_pi_accepts_in_field_centroid(self):
        receipt = saved_camera(parity="mirrored")
        camera = dict(receipt.camera)
        camera["parameters"] = {
            "a0": 0.000204341536069043,
            "x_o": 703.3870008841685,
            "y_o": 704.1050078630846,
            "x_z": 711.018585075199,
            "y_z": 704.8535055092319,
            "v": 0.002040293638509593,
            "s": 0.007262815473162861,
            "d": 0.004991891641377516,
        }
        receipt = replace(receipt, camera=camera)
        point = np.array([140.2352314653957, 875.6935295904382])
        unit = camera_to_icrs_unit(receipt, *point)
        recovered = icrs_unit_to_camera(receipt, unit)
        np.testing.assert_allclose(np.linalg.norm(unit), 1.0, atol=1e-12)
        np.testing.assert_allclose(recovered, point, atol=1e-6)

    def test_saved_derefractor_accepts_real_near_domain_edge_centroid(self):
        receipt = saved_camera(parity="mirrored")
        camera = dict(receipt.camera)
        camera["parameters"] = {
            "a0": 0.0002702816649397473, "x_o": 703.325395364717,
            "y_o": 704.2905635022753, "x_z": 710.7602973372617,
            "y_z": 704.7036574769148, "v": 0.0020405253305903984,
            "s": 0.007112586540401267, "d": 0.004991891641377516,
        }
        camera["reference_rotation"] = [
            [0.6692437719548714, 0.3602160984371432, 0.6498900954210175],
            [-0.7424093736290238, 0.3602728760054991, 0.5648289801014881],
            [-0.030677282268429782, -0.8604927758217662, 0.5085381864827604],
        ]
        camera["integrated_refraction"] = {
            "status": "adopted",
            "zenith_camera_unit_vector": [0.13923288495673072, 0.07065693185215924, 0.9877356942663685],
            "refraction_a_arcsec": 148.98571498782158,
            "refraction_b_arcsec": -0.164703733946742,
            "authoritative_camera_state": True,
        }
        receipt = replace(receipt, camera=camera)
        unit = camera_to_icrs_unit(receipt, 110.65609889374196, 865.5617499816681)
        self.assertTrue(np.isfinite(unit).all())
        np.testing.assert_allclose(np.linalg.norm(unit), 1.0, atol=1e-12)

    def test_mirrored_parity_reflects_camera_y_axis(self):
        normal = saved_camera(parity="normal")
        mirrored = saved_camera(parity="mirrored")
        point = np.array([990.0, 610.0])

        normal_unit = camera_to_icrs_unit(normal, *point)
        mirrored_unit = camera_to_icrs_unit(mirrored, *point)
        rotation = np.asarray(normal.camera["reference_rotation"])
        normal_camera = normal_unit @ rotation
        mirrored_camera = mirrored_unit @ rotation

        np.testing.assert_allclose(mirrored_camera[[0, 2]], normal_camera[[0, 2]], atol=1e-12)
        self.assertAlmostEqual(mirrored_camera[1], -normal_camera[1], places=12)

    def test_invalid_or_nonmonotonic_camera_is_rejected(self):
        valid = saved_camera()
        malformed = replace(valid, camera={**valid.camera, "reference_rotation": [[1, 0], [0, 1]]})
        nonmonotonic_parameters = dict(valid.camera["parameters"])
        nonmonotonic_parameters["v"] = -0.1
        nonmonotonic = replace(
            valid,
            camera={**valid.camera, "parameters": nonmonotonic_parameters},
        )
        declared_bad = replace(valid, camera={**valid.camera, "monotonic_on_detector": False})

        for camera in (malformed, nonmonotonic, declared_bad):
            with self.subTest(camera=camera.camera):
                with self.assertRaises(ValueError):
                    camera_to_icrs_unit(camera, 700.0, 700.0)


class AnonymousDirectionTests(unittest.TestCase):
    def test_predicted_fixture_fields_cannot_change_measured_direction(self):
        selected = SelectedCentroid(
            run_id="run-a",
            source_sha256="sha-a",
            source_path="/archive/a.fits",
            night="2026-09-01",
            observation_time_utc="2026-09-02T03:00:00Z",
            detection_id="10",
            x_px=921.25,
            y_px=488.75,
            stellar_fit_rms_arcmin=2.0,
            source_class="compact",
            saturated=False,
        )
        first = SimpleNamespace(**selected.__dict__, predicted_x_px=-1e9, predicted_y_px=1e9)
        second = SimpleNamespace(**selected.__dict__, predicted_x_px=17.0, predicted_y_px=23.0)
        receipts = {"run-a": saved_camera()}

        first_row = anonymous_direction_rows([first], receipts)[0]
        second_row = anonymous_direction_rows([second], receipts)[0]

        self.assertEqual(first_row, second_row)
        self.assertEqual(first_row.integrated_refraction_status, "rejected")
        self.assertEqual(first_row.object_id, "Object A")


if __name__ == "__main__":
    unittest.main()
