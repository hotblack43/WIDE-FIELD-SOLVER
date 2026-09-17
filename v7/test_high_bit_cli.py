"""The v7 command line exposes explicit high-bit/FITS interpretation controls."""
import unittest
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits

from analyse_image import parser


class HighBitCliTests(unittest.TestCase):
    def test_parses_fits_hdu_channel_order_and_saturation_level(self):
        args = parser().parse_args([
            'stack.fits', '--output', 'out', '--fits-hdu', 'SCI',
            '--channel-order', 'RG1G2B', '--saturation-level', 'R=4095,G1=4095,G2=4095,B=4095'])
        self.assertEqual(args.fits_hdu, 'SCI')
        self.assertEqual(args.channel_order, 'RG1G2B')
        self.assertEqual(args.saturation_level, 'R=4095,G1=4095,G2=4095,B=4095')

    def test_go7_runtime_help_advertises_native_fits_controls(self):
        script = Path(__file__).with_name('run.sh')
        completed = subprocess.run([script, '--help'], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0)
        self.assertIn('--fits-hdu', completed.stdout)
        self.assertIn('--channel-order', completed.stdout)
        self.assertIn('--saturation-level', completed.stdout)

    def test_ambiguous_fits_fails_before_analysis_directory_is_created(self):
        from point_star_barghini import run
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'ambiguous.fits'
            fits.HDUList([fits.PrimaryHDU(),
                          fits.ImageHDU(np.zeros((20, 20)), name='SCI'),
                          fits.ImageHDU(np.ones((20, 20)), name='CAL')]).writeto(source)
            catalogue = root/'catalog.csv'
            catalogue.write_text('star_id,ra_deg,dec_deg,mag\n')
            output = root/'analysis'
            with self.assertRaisesRegex(ValueError, 'multiple plausible'):
                run(source, output, catalogue)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
