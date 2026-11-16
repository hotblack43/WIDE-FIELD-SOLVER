"""Checks for faithful, fast lossless PNG output."""
import struct
import tempfile
from pathlib import Path
import unittest

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np
from PIL import Image


def first_idat_header(path):
    payload = Path(path).read_bytes()
    offset = 8
    while offset < len(payload):
        length = struct.unpack('>I', payload[offset:offset+4])[0]
        kind = payload[offset+4:offset+8]
        data = payload[offset+8:offset+8+length]
        if kind == b'IDAT':
            return data[:2]
        offset += 12+length
    raise AssertionError('PNG has no IDAT chunk')


class PlottingTests(unittest.TestCase):
    def test_save_png_uses_fast_lossless_compression(self):
        try:
            from point_star_plotting import save_png
        except ImportError:
            self.fail('point_star_plotting.save_png is missing')

        figure = Figure(figsize=(2, 1), dpi=40)
        canvas = FigureCanvasAgg(figure)
        axis = figure.subplots()
        axis.imshow(np.arange(60, dtype=np.uint8).reshape(5, 4, 3))
        axis.axis('off')
        figure.subplots_adjust(0, 0, 1, 1)
        canvas.draw()
        expected = np.asarray(canvas.buffer_rgba()).copy()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'plot.png'
            uncompressed = Path(directory)/'uncompressed.png'
            save_png(figure, target)
            figure.savefig(uncompressed, pil_kwargs={'compress_level': 0})
            with Image.open(target) as saved:
                actual = np.asarray(saved.convert('RGBA'))

            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(first_idat_header(target), b'\x78\x01')
            self.assertLess(target.stat().st_size, uncompressed.stat().st_size/4)


if __name__ == '__main__':
    unittest.main()
