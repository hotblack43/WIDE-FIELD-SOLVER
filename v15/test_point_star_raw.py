import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from point_star_raw import decode_cr2, read_cr2_exif


class FakeRaw:
    def __init__(self, pattern):
        self.raw_image_visible = np.arange(24, dtype=np.uint16).reshape(4, 6) + 2000
        self.raw_pattern = np.asarray(pattern, dtype=np.uint8)
        self.color_desc = b'RGBG'
        self.black_level_per_channel = [101, 202, 303, 404]
        self.camera_white_level_per_channel = [11001, 12002, 13003, 14004]
        self.white_level = 16383
        self.shutter = 30.0
        self.iso_speed = 400.0
        self.camera_make = 'Canon'
        self.camera_model = 'EOS 5D Mark IV'
        self.lens = '8-15mm Fisheye'

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class CameraRawTests(unittest.TestCase):
    CASES = {
        'RGGB': [[0, 1], [3, 2]],
        'BGGR': [[2, 1], [3, 0]],
        'GRBG': [[1, 0], [2, 3]],
        'GBRG': [[1, 2], [0, 3]],
    }

    def test_supported_cfa_patterns_split_exact_native_samples(self):
        mosaic = np.arange(24, dtype=np.uint16).reshape(4, 6) + 2000
        for cfa, pattern in self.CASES.items():
            with self.subTest(cfa=cfa), patch('rawpy.imread', return_value=FakeRaw(pattern)):
                decoded = decode_cr2(Path('fixture.cr2'))
                expected = {}
                green_number = 0
                letters = np.asarray(list(cfa)).reshape(2, 2)
                for row in range(2):
                    for col in range(2):
                        letter = letters[row, col]
                        if letter == 'G':
                            green_number += 1
                            letter = f'G{green_number}'
                        expected[letter] = mosaic[row::2, col::2]
                self.assertEqual(tuple(decoded.planes), ('R', 'G1', 'G2', 'B'))
                for name, values in expected.items():
                    np.testing.assert_array_equal(decoded.planes[name], values)
                self.assertEqual(decoded.details['cfa_pattern'], cfa)

    def test_calibration_levels_follow_libraw_colour_indices(self):
        # Canon RGGB is commonly [[R,G],[G,B]] == [[0,1],[3,2]] in LibRaw.
        # The second green therefore uses index 3, not the blue index 2.
        with patch('rawpy.imread', return_value=FakeRaw(self.CASES['RGGB'])):
            decoded = decode_cr2(Path('fixture.cr2'))
        self.assertEqual(decoded.black_levels,
                         {'R': 101.0, 'G1': 202.0, 'G2': 404.0, 'B': 303.0})
        self.assertEqual(decoded.white_levels,
                         {'R': 11001.0, 'G1': 12002.0,
                          'G2': 14004.0, 'B': 13003.0})
        self.assertEqual(decoded.details['sensor_visible_shape'], [4, 6])
        self.assertEqual(decoded.details['exposure_seconds'], 30.0)
        self.assertEqual(decoded.details['iso'], 400.0)
        self.assertNotIn('timestamp', decoded.details)

    def test_rejects_non_bayer_or_odd_visible_arrays(self):
        raw = FakeRaw(self.CASES['RGGB'])
        raw.raw_image_visible = np.zeros((3, 6), dtype=np.uint16)
        with patch('rawpy.imread', return_value=raw):
            with self.assertRaisesRegex(ValueError, 'even dimensions'):
                decode_cr2(Path('fixture.cr2'))
        raw = FakeRaw([[0, 1], [2, 0]])
        with patch('rawpy.imread', return_value=raw):
            with self.assertRaisesRegex(ValueError, 'supported Bayer'):
                decode_cr2(Path('fixture.cr2'))

    def test_selected_exif_fields_do_not_leak_time_into_prefit_metadata(self):
        tags = {
            'EXIF DateTimeOriginal': '2025:06:25 04:06:01',
            'EXIF ExposureTime': '30',
            'EXIF ISOSpeedRatings': '400',
            'Image Make': 'Canon',
            'Image Model': 'Canon EOS 5D Mark IV',
            'EXIF LensModel': 'EF8-15mm f/4L FISHEYE USM',
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fixture.cr2'
            path.write_bytes(b'fixture')
            with patch('exifread.process_file', return_value=tags):
                selected = read_cr2_exif(
                    path, {'exposure_seconds', 'iso', 'camera_make',
                           'camera_model', 'lens'})
        self.assertEqual(selected['exposure_seconds'], 30.)
        self.assertEqual(selected['iso'], 400.)
        self.assertEqual(selected['camera_model'], 'Canon EOS 5D Mark IV')
        self.assertNotIn('datetime_original', selected)
        self.assertFalse(any('time' in name for name in selected))


if __name__ == '__main__':
    unittest.main()
