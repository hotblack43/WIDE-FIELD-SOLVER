"""Image-only sky-footprint tests with no catalogue or metadata inputs."""
import unittest

import numpy as np

from point_star_footprint import infer_sky_footprint


def framed_field(shape, centre, radii):
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    ellipse = ((xx-centre[0])/radii[0])**2 + ((yy-centre[1])/radii[1])**2 <= 1
    image = np.full(shape, 2., dtype=float)
    image[ellipse] = 28. + .015*xx[ellipse] + .01*yy[ellipse]
    # Dark astronomical structure must not punch holes in the accepted field.
    cloud = ellipse & ((xx-centre[0]+22)**2 + (yy-centre[1]-8)**2 < 17**2)
    image[cloud] = 7.
    return image


def full_frame_star_field(shape):
    rng = np.random.default_rng(731)
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    image = 8. + .006*xx + .004*yy + rng.normal(0, .15, shape)
    for x, y in ((12, 15), (70, 40), (160, 125), (205, 165)):
        image += 80*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.1**2))
    return image


class SkyFootprintTests(unittest.TestCase):
    def test_round_field_excludes_black_frame_and_disconnected_frame_marks(self):
        image = framed_field((240, 300), (142, 116), (112, 96))
        image[222:228, 30:120] = 220.
        mask, audit = infer_sky_footprint(image)
        self.assertEqual(audit['status'], 'framed_footprint')
        self.assertTrue(mask[116, 142])
        self.assertTrue(mask[124, 120])
        self.assertFalse(mask[225, 60])
        self.assertGreater(mask.mean(), .40)
        self.assertLess(mask.mean(), .55)
        self.assertEqual(len(audit['code_sha256']), 64)

    def test_dark_full_frame_image_falls_back_to_all_pixels(self):
        mask, audit = infer_sky_footprint(full_frame_star_field((180, 220)))
        self.assertEqual(audit['status'], 'full_image')
        self.assertTrue(mask.all())

    def test_off_centre_cropped_field_does_not_require_image_centre(self):
        image = framed_field((220, 260), (82, 112), (105, 94))
        mask, audit = infer_sky_footprint(image)
        self.assertEqual(audit['status'], 'framed_footprint')
        self.assertTrue(mask[112, 82])
        self.assertTrue(mask[112, 180])
        self.assertFalse(mask[15, 240])


if __name__ == '__main__':
    unittest.main()
