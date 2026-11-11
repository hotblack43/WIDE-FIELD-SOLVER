"""Strict installation-mask loading and layer-combination tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from point_star_visible_sky import VisibleSkyMask, VisibleSkyMaskError


class VisibleSkyMaskTests(unittest.TestCase):
    def _calibration(self, root: Path, pixels: np.ndarray | None = None):
        pixels = (
            np.array([[0, 255, 255], [0, 255, 255]], dtype=np.uint8)
            if pixels is None else np.asarray(pixels, dtype=np.uint8)
        )
        mask_path = root / "installation.png"
        Image.fromarray(pixels, mode="L").save(mask_path)
        manifest = {
            "schema": "wide-field-solver-visible-sky-mask-v1",
            "status": "approved",
            "mask_id": "mmto-visible-sky-2026a-v1",
            "installation_id": "mmto-skycam-2026a",
            "instrument": "ZWO ASI294MC Pro (21599760)",
            "detector_shape": [2, 3],
            "plane_layout": "plane_first",
            "orientation": "detector_native_top_left_xy_right_y_down",
            "coordinate_convention": "array[y, x]; origin top-left",
            "mask_file": mask_path.name,
            "mask_sha256": hashlib.sha256(mask_path.read_bytes()).hexdigest(),
            "mask_values": {"0": "excluded", "255": "visible_sky"},
            "safety_margin_pixels": 5,
            "approval": {
                "approved_by": "Peter",
                "approved_date": "2026-11-11",
                "reviewed_draft_sha256": "d" * 64,
            },
        }
        manifest_path = root / "installation.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, manifest

    def _load(self, manifest_path: Path, **overrides):
        arguments = {
            "installation_id": "mmto-skycam-2026a",
            "instrument": "ZWO ASI294MC Pro (21599760)",
            "detector_shape": (2, 3),
            "plane_layout": "plane_first",
            "orientation": "detector_native_top_left_xy_right_y_down",
        }
        arguments.update(overrides)
        return VisibleSkyMask.load(manifest_path, **arguments)

    def test_valid_mask_loads_without_resampling(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, _manifest = self._calibration(Path(temporary))

            calibration = self._load(manifest_path)

            np.testing.assert_array_equal(
                calibration.visible_mask,
                np.array([[False, True, True], [False, True, True]]),
            )
            self.assertFalse(calibration.visible_mask.flags.writeable)
            self.assertEqual(calibration.mask_id, "mmto-visible-sky-2026a-v1")

    def test_nonbinary_mask_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, _manifest = self._calibration(
                Path(temporary), np.array([[0, 128, 255], [0, 255, 255]])
            )
            with self.assertRaisesRegex(VisibleSkyMaskError, "binary"):
                self._load(manifest_path)

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, manifest = self._calibration(root)
            manifest["mask_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(VisibleSkyMaskError, "checksum"):
                self._load(manifest_path)

    def test_runtime_identity_mismatches_are_rejected(self):
        cases = {
            "installation": {"installation_id": "another-installation"},
            "instrument": {"instrument": "another-camera"},
            "shape": {"detector_shape": (3, 2)},
            "plane layout": {"plane_layout": "named_extensions"},
            "orientation": {"orientation": "rotated_180"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, _manifest = self._calibration(Path(temporary))
            for reason, overrides in cases.items():
                with self.subTest(reason), self.assertRaisesRegex(
                    VisibleSkyMaskError, reason
                ):
                    self._load(manifest_path, **overrides)

    def test_file_shape_must_match_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, manifest = self._calibration(root)
            manifest["detector_shape"] = [3, 2]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(VisibleSkyMaskError, "shape"):
                self._load(manifest_path, detector_shape=(3, 2))

    def test_layer_combination_is_boolean_immutable_and_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, _manifest = self._calibration(Path(temporary))
            calibration = self._load(manifest_path)
            dynamic = np.array([[True, True, False], [True, True, True]])
            finite = np.array([[True, True, True], [True, False, True]])

            layers = calibration.combine(dynamic, finite)

            np.testing.assert_array_equal(
                layers.combined_mask,
                np.array([[False, True, False], [False, False, True]]),
            )
            self.assertEqual(
                layers.pixel_counts,
                {"total": 6, "static_visible": 4, "dynamic": 5, "finite": 5,
                 "combined": 2},
            )
            for array in (
                layers.static_mask, layers.dynamic_mask,
                layers.finite_mask, layers.combined_mask,
            ):
                self.assertFalse(array.flags.writeable)

    def test_not_configured_uses_all_static_pixels_without_changing_other_layers(self):
        calibration = VisibleSkyMask.not_configured((2, 3))
        dynamic = np.array([[True, False, True], [True, True, True]])
        finite = np.array([[True, True, True], [False, True, True]])

        layers = calibration.combine(dynamic, finite)

        self.assertEqual(calibration.status, "not_configured")
        np.testing.assert_array_equal(layers.combined_mask, dynamic & finite)


if __name__ == "__main__":
    unittest.main()
