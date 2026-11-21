"""Detection-stage integration for the static installation mask."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from astropy.io import fits
import numpy as np
from PIL import Image

from point_star_detection import detect_stars, write_products
from point_star_barghini import _assert_candidates_within_usable_sky


class VisibleSkyMaskDetectionTests(unittest.TestCase):
    @staticmethod
    def _scene(*, masked_sources: bool = True):
        rng = np.random.default_rng(2401)
        yy, xx = np.mgrid[:180, :220]
        image = 30.0 + rng.normal(0.0, 0.35, xx.shape)
        image += 130.0 * np.exp(-((xx - 60.2) ** 2 + (yy - 90.4) ** 2) / (2 * 1.3 ** 2))
        if masked_sources:
            image += 180.0 * np.exp(-((xx - 150.3) ** 2 + (yy - 50.1) ** 2) / (2 * 1.3 ** 2))
            image += 900.0 * np.exp(-((xx - 165.2) ** 2 + (yy - 125.4) ** 2) / (2 * 6.0 ** 2))
        return np.clip(image, 0, 255)

    @staticmethod
    def _static_mask():
        mask = np.ones((180, 220), dtype=bool)
        mask[:, 110:] = False
        return mask

    def test_masked_compact_broad_and_saturated_sources_do_not_change_sky_detection(self):
        clean, clean_audit = detect_stars(
            self._scene(masked_sources=False),
            static_visible_mask=self._static_mask(),
        )
        contaminated, contaminated_audit = detect_stars(
            self._scene(masked_sources=True),
            static_visible_mask=self._static_mask(),
        )

        self.assertEqual(len(clean), 1)
        self.assertEqual(len(contaminated), 1)
        np.testing.assert_allclose(
            [clean[0]["x_px"], clean[0]["y_px"]],
            [contaminated[0]["x_px"], contaminated[0]["y_px"]],
            atol=1e-10,
        )
        self.assertAlmostEqual(clean_audit["global_noise"], contaminated_audit["global_noise"])
        self.assertTrue(all(row["x_px"] < 110 for row in contaminated))

    def test_source_support_straddling_static_boundary_is_not_eligible(self):
        rng = np.random.default_rng(2402)
        yy, xx = np.mgrid[:180, :220]
        image = 30.0 + rng.normal(0.0, 0.3, xx.shape)
        image += 120.0 * np.exp(-((xx - 75.2) ** 2 + (yy - 90.1) ** 2) / (2 * 1.2 ** 2))
        image += 160.0 * np.exp(-((xx - 108.5) ** 2 + (yy - 90.2) ** 2) / (2 * 2.0 ** 2))

        stars, audit = detect_stars(image, static_visible_mask=self._static_mask())

        self.assertEqual(len(stars), 1)
        self.assertLess(abs(stars[0]["x_px"] - 75.2), 0.2)
        self.assertTrue(any(
            row["reason"] == "source_support_intersects_visible_sky_mask"
            for row in audit["rejected"]
        ))

    def test_all_true_static_mask_preserves_unconfigured_numerical_path(self):
        image = self._scene(masked_sources=False)
        unconfigured, unconfigured_audit = detect_stars(image)
        configured, configured_audit = detect_stars(
            image, static_visible_mask=np.ones(image.shape, dtype=bool)
        )

        self.assertEqual(unconfigured, configured)
        self.assertEqual(unconfigured_audit["global_noise"], configured_audit["global_noise"])
        np.testing.assert_array_equal(
            unconfigured_audit["valid_mask"], configured_audit["valid_mask"]
        )

    def test_products_save_static_dynamic_finite_and_combined_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mmto.fits"
            pixels = self._scene(masked_sources=True).astype(np.int16)
            hdu = fits.PrimaryHDU(np.stack([pixels, pixels, pixels]))
            hdu.header["INSTRUME"] = "ZWO ASI294MC Pro (21599760)"
            hdu.writeto(source)
            static = self._static_mask()
            mask_path = root / "mask.png"
            Image.fromarray(np.where(static, 255, 0).astype(np.uint8), mode="L").save(mask_path)
            manifest = {
                "schema": "wide-field-solver-visible-sky-mask-v1",
                "status": "approved",
                "mask_id": "test-mask",
                "installation_id": "test-installation",
                "instrument": "ZWO ASI294MC Pro (21599760)",
                "detector_shape": [180, 220],
                "plane_layout": "plane_first",
                "orientation": "detector_native_top_left_xy_right_y_down",
                "coordinate_convention": "array[y, x]; origin top-left",
                "mask_file": "mask.png",
                "mask_sha256": hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                "mask_values": {"0": "excluded", "255": "visible_sky"},
                "safety_margin_pixels": 5,
                "approval": {"approved_by": "Peter"},
            }
            manifest_path = root / "mask.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            summary = write_products(
                source,
                root / "dots",
                visible_sky_mask_manifest=manifest_path,
                camera_installation_id="test-installation",
            )

            with np.load(root / "dots" / "sky_footprint.npz") as saved:
                self.assertEqual(
                    set(saved.files),
                    {"valid_mask", "static_mask", "dynamic_mask", "finite_mask"},
                )
                np.testing.assert_array_equal(saved["static_mask"], static)
                np.testing.assert_array_equal(
                    saved["valid_mask"],
                    saved["static_mask"] & saved["dynamic_mask"] & saved["finite_mask"],
                )
            self.assertEqual(summary["visible_sky_mask_status"], "approved")
            self.assertEqual(summary["visible_sky_mask_id"], "test-mask")
            self.assertEqual(summary["mask_pixel_counts"]["static_visible"], int(static.sum()))

    def test_association_refuses_candidate_outside_saved_combined_mask(self):
        with tempfile.TemporaryDirectory() as temporary:
            mask_path = Path(temporary) / "sky_footprint.npz"
            usable = np.ones((20, 30), dtype=bool)
            usable[10, 15] = False
            np.savez_compressed(mask_path, valid_mask=usable)

            _assert_candidates_within_usable_sky([[8.2, 7.7]], mask_path)
            with self.assertRaisesRegex(RuntimeError, "outside the saved usable-sky mask"):
                _assert_candidates_within_usable_sky([[15.0, 10.0]], mask_path)


if __name__ == "__main__":
    unittest.main()
