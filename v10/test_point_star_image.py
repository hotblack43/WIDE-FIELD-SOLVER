"""Native-depth image loading must not collapse scientific samples to uint8."""
import tempfile
import bz2
import hashlib
import unittest
from pathlib import Path

import numpy as np
import png
from astropy.io import fits
from PIL import Image
import tifffile

from point_star_image import ImageLayoutError, load_recorded_image, load_scientific_image


class ScientificImageTests(unittest.TestCase):
    def test_sixteen_bit_png_samples_above_255_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mono16.png'
            pixels = np.array([[0, 1, 255, 256, 4095, 16383, 65535]], dtype=np.uint16)
            Image.fromarray(pixels).save(path)
            image = load_scientific_image(path)
        np.testing.assert_array_equal(image.planes['L'], pixels)
        self.assertEqual(image.luminance[0, 3], 256)
        self.assertEqual(image.luminance[0, 5], 16383)
        self.assertEqual(image.display_rgb.dtype, np.uint8)

    def test_existing_uint8_rgb_remains_the_display_and_science_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rgb.png'
            pixels = np.array([[[3, 7, 11], [251, 149, 53]]], dtype=np.uint8)
            Image.fromarray(pixels, 'RGB').save(path)
            image = load_scientific_image(path)
        np.testing.assert_array_equal(image.rgb, pixels.astype(float))
        np.testing.assert_array_equal(image.display_rgb, pixels)
        self.assertEqual(list(image.planes), ['R', 'G', 'B'])

    def test_sixteen_bit_rgb_png_retains_each_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rgb16.png'
            pixels = np.array([[[256, 4095, 16383], [65535, 1024, 32768]]], dtype=np.uint16)
            with path.open('wb') as handle:
                png.Writer(2, 1, greyscale=False, bitdepth=16).write(
                    handle, [pixels.reshape(-1).tolist()])
            image = load_scientific_image(path)
        for index, channel in enumerate('RGB'):
            np.testing.assert_array_equal(image.planes[channel], pixels[..., index])
        np.testing.assert_array_equal(image.rgb, pixels.astype(float))

    def test_sixteen_bit_rgb_tiff_retains_each_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rgb16.tiff'
            pixels = np.array([[[256, 4095, 16383], [65535, 1024, 32768]]], dtype=np.uint16)
            tifffile.imwrite(path, pixels, photometric='rgb')
            image = load_scientific_image(path)
        for index, channel in enumerate('RGB'):
            np.testing.assert_array_equal(image.planes[channel], pixels[..., index])

    def test_display_array_is_not_a_scientific_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mono16.png'
            pixels = np.arange(400, dtype=np.uint16).reshape(20, 20)*100
            Image.fromarray(pixels).save(path)
            image = load_scientific_image(path)
        before = image.luminance.copy()
        image.display_rgb[:] = 0
        np.testing.assert_array_equal(image.luminance, before)

    def test_fits_accepts_plane_first_and_plane_last_rgb(self):
        planes = np.arange(3*18*20, dtype=np.uint16).reshape(3, 18, 20)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, values in [('first.fits', planes),
                                 ('last.fits', np.moveaxis(planes, 0, -1))]:
                path = root/name
                fits.PrimaryHDU(values).writeto(path)
                image = load_scientific_image(path)
                for index, channel in enumerate('RGB'):
                    np.testing.assert_array_equal(image.planes[channel], planes[index])

    def test_bz2_fits_matches_uncompressed_science_and_provenance(self):
        pixels = (np.arange(3*18*20, dtype=np.uint16).reshape(3, 18, 20)*60)
        pixels[0, 0, 0] = 65535
        with tempfile.TemporaryDirectory() as folder:
            plain = Path(folder)/'plain.fits'
            hdu = fits.PrimaryHDU(pixels)
            hdu.header['EXPOSURE'] = 20.0
            hdu.writeto(plain)
            expected = load_scientific_image(plain)
            packed = bz2.compress(plain.read_bytes())
            for name in ('image.fits.bz2', 'image.fit.bz2', 'image.FTS.BZ2'):
                with self.subTest(name=name):
                    compressed = Path(folder)/name
                    compressed.write_bytes(packed)
                    actual = load_scientific_image(compressed)
                    for channel in 'RGB':
                        np.testing.assert_array_equal(actual.planes[channel], expected.planes[channel])
                        np.testing.assert_array_equal(actual.plane_saturated_masks[channel],
                                                      expected.plane_saturated_masks[channel])
                    for field in ('rgb', 'luminance', 'valid_mask', 'display_rgb'):
                        np.testing.assert_array_equal(getattr(actual, field), getattr(expected, field))
                    for field in ('fits_hdus', 'exposure', 'channel_layout'):
                        self.assertEqual(actual.provenance()[field], expected.provenance()[field])
                    self.assertEqual(actual.provenance()['source_compression'], 'bz2')
                    self.assertIn(actual.provenance()['format'], ('fits', 'fit', 'fts'))
                    self.assertEqual(actual.provenance()['source_sha256'], hashlib.sha256(packed).hexdigest())
                    self.assertEqual(compressed.read_bytes(), packed)

    def test_fits_exposure_seconds_are_recorded_with_header_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'exposure.fits'
            hdu = fits.PrimaryHDU(np.zeros((3, 18, 20), dtype=np.int16))
            hdu.header['EXPOSURE'] = 20.0
            hdu.writeto(path)
            exposure = load_scientific_image(path).provenance()['exposure']
        self.assertEqual(exposure['status'], 'available')
        self.assertEqual(exposure['seconds'], 20.0)
        self.assertEqual(exposure['source'], 'fits:PRIMARY:EXPOSURE')

    def test_exif_exposure_seconds_are_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'exposure.jpg'
            exif = Image.Exif()
            exif[33434] = (1, 8)
            Image.fromarray(np.zeros((18, 20, 3), dtype=np.uint8)).save(path, exif=exif)
            exposure = load_scientific_image(path).provenance()['exposure']
        self.assertEqual(exposure['status'], 'available')
        self.assertAlmostEqual(exposure['seconds'], .125)
        self.assertEqual(exposure['source'], 'exif:ExposureTime')

    def test_four_plane_fits_retains_both_greens_and_derives_their_mean(self):
        planes = np.stack([
            np.full((18, 20), 100, dtype=np.uint16),
            np.full((18, 20), 200, dtype=np.uint16),
            np.full((18, 20), 400, dtype=np.uint16),
            np.full((18, 20), 800, dtype=np.uint16)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rggb.fits'
            fits.PrimaryHDU(planes).writeto(path)
            image = load_scientific_image(path)
        self.assertEqual(list(image.planes), ['R', 'G1', 'G2', 'B'])
        np.testing.assert_array_equal(image.planes['G1'], planes[1])
        np.testing.assert_array_equal(image.planes['G2'], planes[2])
        np.testing.assert_array_equal(image.rgb[..., 1], np.full((18, 20), 300.))

    def test_named_fits_extensions_form_rgb_without_guessing_an_hdu(self):
        values = {name: np.full((18, 20), value, dtype=np.uint16)
                  for name, value in [('RED', 10), ('GREEN', 20), ('BLUE', 30)]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'extensions.fits'
            fits.HDUList([fits.PrimaryHDU()] +
                         [fits.ImageHDU(data, name=name) for name, data in values.items()]).writeto(path)
            image = load_scientific_image(path)
        for name, value in values.items():
            np.testing.assert_array_equal(image.planes[name[0]], value)

    def test_short_named_fits_extensions_form_r_g1_g2_b(self):
        names = ('R', 'G1', 'G2', 'B')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'short-names.fits'
            fits.HDUList([fits.PrimaryHDU()] + [
                fits.ImageHDU(np.full((18, 20), index+1, dtype=np.uint16), name=name)
                for index, name in enumerate(names)]).writeto(path)
            image = load_scientific_image(path)
        self.assertEqual(list(image.planes), list(names))
        np.testing.assert_array_equal(image.rgb[..., 1], np.full((18, 20), 2.5))

    def test_ambiguous_fits_hdus_require_explicit_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'ambiguous.fits'
            fits.HDUList([fits.PrimaryHDU(),
                          fits.ImageHDU(np.zeros((18, 20)), name='SCI'),
                          fits.ImageHDU(np.ones((18, 20)), name='CAL')]).writeto(path)
            with self.assertRaisesRegex(ImageLayoutError, 'SCI.*CAL'):
                load_scientific_image(path)
            image = load_scientific_image(path, fits_hdu='SCI')
        np.testing.assert_array_equal(image.planes['L'], np.zeros((18, 20)))

    def test_fits_nonfinite_samples_are_invalid_not_black_sky(self):
        pixels = np.ones((18, 20), dtype=float)
        pixels[2, 3] = np.nan
        pixels[4, 5] = np.inf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'invalid.fits'
            fits.PrimaryHDU(pixels).writeto(path)
            image = load_scientific_image(path)
        self.assertFalse(image.valid_mask[2, 3])
        self.assertFalse(image.valid_mask[4, 5])
        self.assertEqual(image.provenance()['invalid_pixel_count'], 2)
        self.assertTrue(np.isnan(image.luminance[2, 3]))

    def test_fits_bscale_bzero_are_applied_and_original_scaling_is_recorded(self):
        raw = np.array([[0, 1], [2, 3]], dtype=np.int16)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scaled.fits'
            hdu = fits.PrimaryHDU(raw)
            hdu.header['BSCALE'] = 2
            hdu.header['BZERO'] = 100
            hdu.writeto(path)
            image = load_scientific_image(path)
        np.testing.assert_array_equal(image.planes['L'], [[100, 102], [104, 106]])
        selected = image.provenance()['fits_hdus'][0]
        self.assertEqual(selected['bscale'], 2)
        self.assertEqual(selected['bzero'], 100)

    def test_saturation_authority_is_explicit_then_header_then_standard_then_dtype(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            explicit = root/'explicit.fits'
            fits.PrimaryHDU(np.array([[0, 3000], [4095, 12]], dtype=np.uint16)).writeto(explicit)
            image = load_scientific_image(explicit, saturation_level=3000)
            self.assertEqual(image.provenance()['saturation']['L']['source'], 'explicit')
            self.assertTrue(image.saturated_mask[0, 1])

            header = root/'header.fits'
            hdu = fits.PrimaryHDU(np.array([[0, 2000], [3500, 12]], dtype=np.uint16))
            hdu.header['SATURATE'] = 3500
            hdu.writeto(header)
            image = load_scientific_image(header)
            self.assertEqual(image.provenance()['saturation']['L']['source'], 'fits_SATURATE')
            self.assertTrue(image.saturated_mask[1, 0])

            standard = root/'standard.fits'
            fits.PrimaryHDU(np.array([[0, 4095], [1000, 12]], dtype=np.uint16)).writeto(standard)
            image = load_scientific_image(standard)
            self.assertEqual(image.provenance()['saturation']['L']['level'], 4095)
            self.assertEqual(image.provenance()['saturation']['L']['source'],
                             'observed_standard_clipping_ceiling')
            self.assertEqual(image.provenance()['effective_bit_depth']['L'], 12)
            self.assertEqual(image.provenance()['black_level']['status'], 'not_applied')

            assumed = root/'assumed.fits'
            fits.PrimaryHDU(np.array([[0, 3001], [1000, 12]], dtype=np.uint16)).writeto(assumed)
            image = load_scientific_image(assumed)
            self.assertEqual(image.provenance()['saturation']['L']['source'],
                             'datatype_ceiling_assumption')

    def test_floating_fits_has_unknown_saturation_without_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'float.fits'
            fits.PrimaryHDU(np.ones((18, 20), dtype=np.float32)).writeto(path)
            image = load_scientific_image(path)
        self.assertFalse(image.provenance()['saturation_known'])
        self.assertFalse(image.saturated_mask.any())

    def test_recorded_policy_reloads_explicit_hdu_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'two.fits'
            fits.HDUList([fits.PrimaryHDU(),
                          fits.ImageHDU(np.ones((18, 20)), name='SCI'),
                          fits.ImageHDU(np.zeros((18, 20)), name='CAL')]).writeto(path)
            first = load_scientific_image(path, fits_hdu='SCI', saturation_level=12)
            (root/'input_image.json').write_text(__import__('json').dumps(first.provenance()))
            second = load_recorded_image(path, root)
            np.testing.assert_array_equal(second.planes['L'], np.ones((18, 20)))
            with fits.open(path, mode='update') as hdus:
                hdus['SCI'].data[0, 0] = 9
            with self.assertRaisesRegex(ValueError, 'checksum'):
                load_recorded_image(path, root)


if __name__ == '__main__':
    unittest.main()
