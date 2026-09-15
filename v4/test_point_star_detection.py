"""Point-source recovery tests with independently specified image positions."""
import unittest

import numpy as np

from point_star_detection import detect_stars


class PointStarDetectionTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
