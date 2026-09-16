"""Point-source recovery tests with independently specified image positions."""
import unittest
import csv
import json
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image

from point_star_detection import detect_stars, write_products


class PointStarDetectionTests(unittest.TestCase):
    @staticmethod
    def framed_sources():
        rng = np.random.default_rng(20260915)
        yy, xx = np.mgrid[:180, :220]
        field = ((xx-110)/82)**2+((yy-86)/72)**2 <= 1
        image = np.full((180, 220), 2.)
        image[field] = 24+rng.normal(0, .35, field.sum())
        image += 100*np.exp(-((xx-90.3)**2+(yy-70.7)**2)/(2*1.2**2))
        image += 500*np.exp(-((xx-135.2)**2+(yy-105.4)**2)/(2*5.5**2))
        # Point-like graphics in the black frame, including a short baseline.
        for x in (35, 48, 61, 74, 87):
            image += 120*np.exp(-((xx-x)**2+(yy-166)**2)/(2*1.1**2))
        return np.clip(image, 0, 255)

    def test_subpixel_centres_on_changing_background(self):
        rng = np.random.default_rng(17)
        yy, xx = np.mgrid[:180, :220]
        image = 20 + .09*xx + .03*yy + rng.normal(0, .6, xx.shape)
        truth = np.array([[35.3, 42.7], [120.8, 65.2], [167.4, 130.6]])
        for x, y in truth:
            image += 90*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.2**2))
        stars, _ = detect_stars(image)
        xy = np.array([[s['x_px'], s['y_px']] for s in stars])
        self.assertEqual(len(xy), 3)
        for target in truth:
            self.assertLess(np.linalg.norm(xy-target, axis=1).min(), .15)

    def test_rejects_streak_and_single_pixel_but_retains_round_blob(self):
        rng = np.random.default_rng(19)
        yy, xx = np.mgrid[:180, :220]
        image = 20 + rng.normal(0, .5, xx.shape)
        image += 90*np.exp(-((xx-40.2)**2+(yy-40.4)**2)/(2*1.2**2))
        image += 90*np.exp(-((xx-110)**2/18**2+(yy-65)**2/.8**2)/2)
        image += 70*np.exp(-((xx-150)**2+(yy-130)**2)/(2*12**2))
        image[135, 40] += 150
        stars, _ = detect_stars(image)
        compact = [s for s in stars if s['source_class'] == 'compact']
        broad = [s for s in stars if s['source_class'] == 'broad_blob']
        self.assertEqual(len(compact), 1)
        self.assertEqual(len(broad), 1)
        self.assertLess(np.hypot(compact[0]['x_px']-40.2, compact[0]['y_px']-40.4), .15)
        self.assertLess(np.hypot(broad[0]['x_px']-150, broad[0]['y_px']-130), .3)

    def test_retains_large_saturated_blob_once(self):
        rng = np.random.default_rng(91)
        yy, xx = np.mgrid[:180, :220]
        image = np.clip(25 + 900*np.exp(-((xx-100.7)**2+(yy-85.3)**2)/(2*6**2)), 0, 255)
        image = np.clip(image+rng.normal(0, .2, image.shape), 0, 255)
        stars, _ = detect_stars(image)
        self.assertEqual(len(stars), 1)
        self.assertEqual(stars[0]['source_class'], 'broad_blob')
        self.assertTrue(stars[0]['saturated'])
        self.assertLess(np.hypot(stars[0]['x_px']-100.7, stars[0]['y_px']-85.3), .5)

    def test_flat_image_has_no_detections(self):
        stars, _ = detect_stars(np.full((100, 120), 30.))
        self.assertEqual(stars, [])

    def test_frame_sources_are_audited_before_detection_ids_are_assigned(self):
        stars, audit = detect_stars(self.framed_sources())
        xy = np.array([[s['x_px'], s['y_px']] for s in stars])
        self.assertTrue(np.any(np.linalg.norm(xy-[90.3, 70.7], axis=1) < .3))
        broad = [s for s in stars if s['source_class'] == 'broad_blob']
        self.assertTrue(any(s['saturated'] for s in broad))
        self.assertFalse(np.any(xy[:, 1] > 155))
        outside = [r for r in audit['rejected'] if r['reason'] == 'outside_sky_footprint']
        self.assertGreaterEqual(len(outside), 5)
        self.assertEqual([s['detection_id'] for s in stars], list(range(1, len(stars)+1)))

    def test_write_products_saves_mask_and_matching_audit_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root/'input.png'
            Image.fromarray(self.framed_sources().astype('uint8')).save(image)
            summary = write_products(image, root/'dots')
            with np.load(root/'dots/sky_footprint.npz') as saved:
                mask = saved['valid_mask']
            with (root/'dots/rejected_candidates.csv').open() as handle:
                rejected = list(csv.DictReader(handle))
            disk_summary = json.loads((root/'dots/detection.json').read_text())
            self.assertEqual(mask.dtype, np.bool_)
            self.assertEqual(mask.shape, (180, 220))
            self.assertTrue((root/'dots/sky_footprint.png').is_file())
            self.assertEqual(summary['frame_sources_rejected'],
                             sum(r['reason'] == 'outside_sky_footprint' for r in rejected))
            self.assertEqual(disk_summary['footprint_status'], 'framed_footprint')
            self.assertIsNotNone(disk_summary['sky_footprint']['threshold_adu'])

    def test_native_gain_changes_flux_not_centroid_or_candidate_count(self):
        scene = self.framed_sources()
        base, _ = detect_stars(scene, saturated_mask=scene >= 250)
        for gain in (16, 64, 257):  # representative 12-, 14- and 16-bit encodings
            with self.subTest(gain=gain):
                gained, _ = detect_stars(scene*gain, saturated_mask=scene >= 250)
                self.assertEqual(len(gained), len(base))
                np.testing.assert_allclose(
                    [[row['x_px'], row['y_px']] for row in gained],
                    [[row['x_px'], row['y_px']] for row in base], atol=.02)
                np.testing.assert_allclose(
                    [row['flux_above_background'] for row in gained],
                    np.array([row['flux_above_background'] for row in base])*gain, rtol=2e-5)

    def test_write_products_accepts_four_plane_fits_and_records_native_provenance(self):
        mono = self.framed_sources().astype(np.uint16)*16
        planes = np.stack([mono, mono*2, mono*4, mono*3])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'stack.fits'
            fits.PrimaryHDU(planes).writeto(source)
            summary = write_products(source, root/'dots', saturation_level=4095)
            provenance = json.loads((root/'dots/input_image.json').read_text())
        self.assertGreater(summary['candidates'], 0)
        self.assertEqual(provenance['plane_names'], ['R', 'G1', 'G2', 'B'])
        self.assertEqual(provenance['channel_derivation']['G'], '(G1 + G2) / 2')
        self.assertTrue(provenance['native_depth_preserved'])

    def test_nonfinite_fits_pixels_are_masked_without_poisoning_detection(self):
        pixels = self.framed_sources().astype(np.float32)
        pixels[:4, :7] = np.nan
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'invalid.fits'
            fits.PrimaryHDU(pixels).writeto(source)
            summary = write_products(source, root/'dots')
            with np.load(root/'dots/sky_footprint.npz') as saved:
                mask = saved['valid_mask']
        self.assertGreater(summary['candidates'], 0)
        self.assertEqual(summary['input_image']['invalid_pixel_count'], 28)
        self.assertFalse(mask[:4, :7].any())


if __name__ == '__main__':
    unittest.main()
