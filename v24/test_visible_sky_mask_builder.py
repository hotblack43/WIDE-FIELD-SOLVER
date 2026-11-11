"""Behaviour tests for the review-only visible-sky mask proposal builder."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from astropy.io import fits
import numpy as np
from PIL import Image

from scripts.build_visible_sky_mask import (
    accumulate_temporal_evidence,
    finalize_approved_mask,
    load_native_luminance,
    propose_visible_sky,
    robust_normalize,
    select_representative_sources,
    write_proposal,
)


class VisibleSkyMaskBuilderTests(unittest.TestCase):
    def test_finalizer_applies_five_pixel_inward_safety_margin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = root / "draft.png"
            output = root / "approved.png"
            pixels = np.zeros((31, 31), dtype=np.uint8)
            pixels[5:26, 5:26] = 255
            Image.fromarray(pixels, mode="L").save(draft)

            record = finalize_approved_mask(draft, output, safety_margin_pixels=5)

            approved = np.asarray(Image.open(output))
            self.assertEqual(int((approved == 255).sum()), 11 * 11)
            self.assertEqual(record["safety_margin_pixels"], 5)
            self.assertEqual(record["draft_visible_pixels"], 21 * 21)
            self.assertEqual(record["approved_visible_pixels"], 11 * 11)

    def test_direct_entrypoint_can_load_the_v24_runtime(self):
        script = Path(__file__).parent / "scripts" / "build_visible_sky_mask.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=Path("/tmp"),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("review-only temporal evidence", completed.stdout)

    def test_selection_is_deterministic_and_spans_night_phases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for date in ("2026-09-01", "2026-09-02", "2026-09-03"):
                night = root / date
                night.mkdir()
                for hour in (1, 3, 5, 7, 9):
                    path = night / f"2026_09_01__{hour:02d}_00_00.fits.bz2"
                    path.touch()
                    paths.append(path)

            selected = select_representative_sources(reversed(paths))

            self.assertEqual(
                [path.name for path in selected],
                [
                    "2026_09_01__03_00_00.fits.bz2",
                    "2026_09_01__05_00_00.fits.bz2",
                    "2026_09_01__07_00_00.fits.bz2",
                ],
            )

    def test_native_fits_loader_preserves_luminance_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "2026-09-01" / "native.fits"
            path.parent.mkdir()
            values = np.arange(80, dtype=np.uint16).reshape(8, 10)
            fits.PrimaryHDU(values).writeto(path)

            luminance, record, display = load_native_luminance(path)

            np.testing.assert_array_equal(luminance, values.astype(float))
            self.assertEqual(record["spatial_shape"], [8, 10])
            self.assertEqual(record["decoded_dtype"], {"L": "uint16"})
            self.assertEqual(display.shape, (8, 10, 3))

    def test_robust_normalization_ignores_one_extreme_pixel(self):
        values = np.tile(np.linspace(100.0, 200.0, 100), (40, 1))
        values[0, 0] = 1_000_000.0

        normalized, record = robust_normalize(values)

        self.assertEqual(normalized.dtype, np.float32)
        self.assertGreater(float(normalized[:, 50].mean()), 0.45)
        self.assertLess(float(normalized[:, 50].mean()), 0.55)
        self.assertEqual(record["method"], "finite_1_99_percentile_linear_clip")

    def test_temporal_evidence_separates_fixed_foreground_from_moving_sources(self):
        yy, xx = np.indices((64, 64))
        optical = (xx - 31.5) ** 2 + (yy - 31.5) ** 2 <= 29.0 ** 2
        fixed_foreground = (yy < 23) & (xx < 28)
        frames = []
        for index in range(9):
            frame = np.zeros((64, 64), dtype=float)
            frame[optical] = 20.0 + index
            frame[fixed_foreground] = 1.0
            frame[30 + index % 3, 18 + 4 * index] = 200.0
            frames.append(frame)

        evidence = accumulate_temporal_evidence(frames)

        self.assertEqual(evidence.temporal_median.shape, (64, 64))
        self.assertEqual(evidence.edge_persistence.shape, (64, 64))
        self.assertEqual(evidence.source_density.shape, (64, 64))
        self.assertGreater(evidence.optical_consensus[32, 32], 0.8)
        self.assertGreater(evidence.source_density[32, 32], evidence.source_density[5, 5])

    def test_proposal_is_binary_and_excludes_connected_foreground(self):
        yy, xx = np.indices((96, 96))
        optical = (xx - 47.5) ** 2 + (yy - 47.5) ** 2 <= 44.0 ** 2
        foreground = (yy < 33) & (xx < 50)
        frames = []
        for index in range(12):
            frame = np.zeros((96, 96), dtype=float)
            frame[optical] = 40.0 + 10.0 * np.sin(index)
            frame[foreground] = 1.0
            frame[50 + index % 4, 20 + 5 * index] = 250.0
            frames.append(frame)
        evidence = accumulate_temporal_evidence(frames)

        mask, audit = propose_visible_sky(evidence)

        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask[48, 48])
        self.assertFalse(mask[10, 10])
        self.assertFalse(mask[25, 25])
        self.assertFalse(mask[0, 48])
        self.assertGreater(audit["visible_fraction"], 0.25)
        self.assertLess(audit["visible_fraction"], 0.8)

    def test_proposal_excludes_a_fixed_dark_spoke_against_local_sky(self):
        yy, xx = np.indices((128, 128))
        optical = (xx - 63.5) ** 2 + (yy - 63.5) ** 2 <= 59.0 ** 2
        spoke = (xx >= 78) & (np.abs((yy - 77) - 0.55 * (xx - 78)) <= 3.0)
        frames = []
        for index in range(12):
            frame = np.zeros((128, 128), dtype=float)
            frame[optical] = 35.0 + index
            frame[spoke] = 20.0
            frame[45 + index % 5, 25 + 6 * index] = 220.0
            frames.append(frame)

        mask, _audit = propose_visible_sky(accumulate_temporal_evidence(frames))

        self.assertTrue(mask[64, 64])
        self.assertFalse(mask[87, 96])

    def test_first_radial_obstruction_excludes_brighter_pixels_behind_it(self):
        yy, xx = np.indices((128, 128))
        optical = (xx - 63.5) ** 2 + (yy - 63.5) ** 2 <= 59.0 ** 2
        obstruction = (xx >= 86) & (xx <= 92) & (np.abs(yy - 64) <= 3)
        frames = []
        for index in range(9):
            frame = np.zeros((128, 128), dtype=float)
            frame[optical] = 40.0 + index
            frame[obstruction] = 20.0
            frames.append(frame)

        mask, _audit = propose_visible_sky(accumulate_temporal_evidence(frames))

        self.assertFalse(mask[64, 108])

    def test_writer_emits_review_only_binary_artifacts_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "2026-09-01" / "test.fits"
            source.parent.mkdir()
            fits.PrimaryHDU(np.ones((32, 40), dtype=np.uint16)).writeto(source)
            frames = [np.pad(np.full((24, 32), 20.0), 4) for _ in range(3)]
            evidence = accumulate_temporal_evidence(frames)
            mask, audit = propose_visible_sky(evidence)
            reference = np.repeat(
                np.uint8(np.clip(evidence.temporal_median * 255.0, 0, 255))[..., None],
                3,
                axis=2,
            )
            output = root / "review"

            write_proposal(
                output,
                mask=mask,
                evidence=evidence,
                reference_rgb=reference,
                source_records=[{
                    "path": str(source),
                    "source_sha256": "a" * 64,
                    "spatial_shape": [32, 40],
                    "observation_date": "2026-09-01",
                }],
                audit=audit,
            )

            draft = np.asarray(Image.open(output / "mmto_installation_2026a.draft.png"))
            self.assertEqual(set(np.unique(draft)), {0, 255})
            selection = json.loads((output / "selection.json").read_text())
            self.assertEqual(selection["status"], "draft_not_approved")
            self.assertEqual(selection["coordinate_convention"], "array[y, x]; origin top-left")
            self.assertNotIn("approval", selection)
            self.assertTrue((output / "temporal_reference.png").is_file())
            self.assertTrue((output / "boundary_review.png").is_file())
            self.assertTrue((output / "boundary_review_inverted.png").is_file())
            with self.assertRaises(FileExistsError):
                write_proposal(
                    output,
                    mask=mask,
                    evidence=evidence,
                    reference_rgb=reference,
                    source_records=[],
                    audit=audit,
                )


if __name__ == "__main__":
    unittest.main()
