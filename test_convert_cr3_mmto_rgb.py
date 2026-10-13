import importlib.util
import bz2
from pathlib import Path
import subprocess
import tempfile
import unittest

from astropy.io import fits
import numpy as np


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "convert_cr3_mmto_rgb.py"


def load_converter():
    spec = importlib.util.spec_from_file_location("convert_cr3_mmto_rgb", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MMTOColourConversionTests(unittest.TestCase):
    def test_common_linear_scale_produces_signed_three_plane_cube(self):
        converter = load_converter()
        rgb = np.array(
            [[[0, 16384, 65535], [32768, 49152, 8192]]], dtype=np.uint16
        )

        cube = converter.mmto_cube(rgb, pedestal=1870)

        self.assertEqual(cube.shape, (3, 1, 2))
        self.assertEqual(cube.dtype, np.dtype("int16"))
        self.assertEqual(int(cube[0, 0, 0]), 1870)
        self.assertEqual(int(cube[2, 0, 0]), 32767)
        scale = (32767 - 1870) / 65535
        self.assertEqual(int(cube[1, 0, 0]), round(1870 + 16384 * scale))
        self.assertEqual(int(cube[0, 0, 1]), round(1870 + 32768 * scale))

    def test_reads_sixteen_bit_binary_ppm_without_quantising(self):
        converter = load_converter()
        pixels = np.array(
            [[[0, 1, 65535], [256, 32768, 4095]]], dtype=">u2"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "linear.ppm"
            path.write_bytes(b"P6\n# LibRaw output\n2 1\n65535\n" + pixels.tobytes())

            decoded = converter.read_ppm16(path)

        self.assertEqual(decoded.dtype, np.dtype("uint16"))
        np.testing.assert_array_equal(decoded, pixels.astype(np.uint16))

    def test_writes_mmto_like_primary_rgb_fits_with_provenance(self):
        converter = load_converter()
        rgb = np.array(
            [[[0, 1000, 2000], [65535, 32000, 16000]]], dtype=np.uint16
        )
        metadata = {
            "make": "Canon",
            "model": "Canon EOS R6m2",
            "exposure": 30.0,
            "iso": 100,
            "f_number": 2.8,
            "focal_length": 15.0,
            "date_original": "2026:10:12 21:48:58",
            "subsec_original": "49",
            "offset_original": "+02:00",
            "date_obs": "2026-10-12T19:48:58.490000",
            "lens_info": "15 15 0 0",
            "focus_mode": 3,
            "focus_range": 1,
            "hyperfocal_distance": 2.67476625363634,
            "circle_of_confusion": 0.0300426785884178,
            "colour_temperature": 5200,
            "camera_temperature": 22,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "frame.CR3"
            source.write_bytes(b"raw source identity")
            target = Path(directory) / "frame_RGB.fits"

            converter.write_mmto_fits(source, target, rgb, metadata)

            with fits.open(target, checksum=True, memmap=False) as hdus:
                data = hdus[0].data
                header = hdus[0].header
                self.assertEqual(data.shape, (3, 1, 2))
                self.assertEqual(data.dtype, np.dtype(">i2"))
                self.assertEqual(header["BITPIX"], 16)
                self.assertNotIn("BZERO", header)
                self.assertEqual(header["CHANNELS"], "R,G,B")
                self.assertEqual(header["ORIGIN"], "KNALDGAS")
                self.assertEqual(header["INSTRUME"], "Canon EOS R6m2")
                self.assertEqual(header["EXPOSURE"], 30.0)
                self.assertEqual(header["EXPTIME"], 30.0)
                self.assertEqual(header["ISOSPEED"], 100)
                self.assertEqual(header["APERTURE"], 2.8)
                self.assertEqual(header["FOCALLEN"], 15.0)
                self.assertEqual(header["LENSINFO"], "15 15 0 0")
                self.assertEqual(header["FOCUSMOD"], 3)
                self.assertEqual(header["FOCUSRNG"], 1)
                self.assertAlmostEqual(header["HYPERFOC"], 2.67476625363634)
                self.assertAlmostEqual(header["CIRCCONF"], 0.0300426785884178)
                self.assertEqual(header["COLORTMP"], 5200)
                self.assertEqual(header["CAMTEMP"], 22)
                self.assertEqual(header["SUBSEC"], "49")
                self.assertEqual(header["DATE-OBS"], "2026-10-12T19:48:58.490000")
                self.assertEqual(header["BITCAMPX"], 15)
                self.assertEqual(header["PEDESTAL"], 1870)
                self.assertEqual(header["COLSPACE"], "LINEAR_SRGB")
                self.assertEqual(header["TRANSFER"], "LINEAR")
                self.assertTrue(header["PHOTLINE"])
                self.assertEqual(header["SRCFILE"], source.name)
                self.assertEqual(len(header["SRCSHA"]), 64)
                self.assertEqual(hdus[0].verify_checksum(), 1)
                self.assertEqual(hdus[0].verify_datasum(), 1)

    def test_normalises_exif_metadata_and_utc_observation_time(self):
        converter = load_converter()
        record = {
            "Make": "Canon",
            "Model": "Canon EOS R6m2",
            "ExposureTime": 30,
            "ISO": 100,
            "FNumber": 2.8,
            "FocalLength": 15,
            "DateTimeOriginal": "2026:10:12 21:48:58",
            "SubSecTimeOriginal": 49,
            "OffsetTimeOriginal": "+02:00",
            "LensInfo": "15 15 0 0",
            "LensModel": "RF15mm F2.8 FISHEYE STM",
            "FocusMode": 3,
            "FocusRange": 1,
            "HyperfocalDistance": 2.67476625363634,
            "CircleOfConfusion": 0.0300426785884178,
            "AFAreaMode": 0,
            "WhiteBalance": 0,
            "ColorTemperature": 5200,
            "CameraTemperature": 22,
            "ExposureMode": 1,
            "ExposureProgram": 1,
            "MeteringMode": 3,
            "ImageStabilization": 257,
            "LongExposureNoiseReduction": 0,
            "HighISONoiseReduction": 0,
            "Orientation": 1,
        }

        metadata = converter.normalise_metadata(record)

        self.assertEqual(metadata["make"], "Canon")
        self.assertEqual(metadata["model"], "Canon EOS R6m2")
        self.assertEqual(metadata["exposure"], 30.0)
        self.assertEqual(metadata["iso"], 100)
        self.assertEqual(metadata["date_obs"], "2026-10-12T19:48:58.490000")
        self.assertEqual(metadata["lens_model"], "RF15mm F2.8 FISHEYE STM")
        self.assertEqual(metadata["focus_mode"], 3)
        self.assertEqual(metadata["focus_range"], 1)
        self.assertAlmostEqual(metadata["hyperfocal_distance"], 2.67476625363634)
        self.assertEqual(metadata["colour_temperature"], 5200)
        self.assertEqual(metadata["camera_temperature"], 22)

    def test_bzip2_product_is_verified_and_uncompressed_input_is_removed(self):
        converter = load_converter()
        rgb = np.array([[[0, 1000, 65535]]], dtype=np.uint16)
        metadata = {"model": "Canon EOS R6m2", "exposure": 30.0}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "frame.CR3"
            source.write_bytes(b"raw source identity")
            plain = root / "frame_RGB.fits"
            target = root / "frame_RGB.fits.bz2"
            converter.write_mmto_fits(source, plain, rgb, metadata)

            converter.compress_verified_fits(plain, target)

            self.assertFalse(plain.exists())
            self.assertTrue(target.is_file())
            with bz2.open(target, "rb") as compressed:
                with fits.open(compressed, checksum=True, memmap=False) as hdus:
                    self.assertEqual(hdus[0].data.shape, (3, 1, 1))
                    self.assertEqual(hdus[0].verify_checksum(), 1)
                    self.assertEqual(hdus[0].verify_datasum(), 1)

    def test_discovers_nested_canon_raws_and_mirrors_their_directories(self):
        converter = load_converter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "raw"
            output = Path(directory) / "rgb"
            (root / "Ra" / "ISO400").mkdir(parents=True)
            first = root / "R6m2" / "night.CR3"
            first.parent.mkdir()
            first.write_bytes(b"one")
            second = root / "Ra" / "ISO400" / "fast.cr2"
            second.write_bytes(b"two")
            (root / "ignore.JPG").write_bytes(b"not raw")

            found = converter.discover_raw_files(root)
            targets = [converter.output_path(path, root, output) for path in found]

        self.assertEqual(found, [first, second])
        self.assertEqual(
            targets,
            [
                output / "R6m2" / "night_RGB.fits.bz2",
                output / "Ra" / "ISO400" / "fast_RGB.fits.bz2",
            ],
        )

    def test_cli_has_no_nonlinear_transfer_switch(self):
        completed = subprocess.run(
            ["uv", "run", "--frozen", "python", str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("linear RGB", completed.stdout)
        self.assertNotIn("--transfer", completed.stdout)

    def test_minimum_exposure_filter_keeps_one_second_and_longer(self):
        converter = load_converter()
        records = [
            (Path("quarter.CR3"), {"exposure": 0.25}),
            (Path("one.CR3"), {"exposure": 1.0}),
            (Path("thirty.CR3"), {"exposure": 30.0}),
            (Path("unknown.CR3"), {"exposure": None}),
        ]

        selected, excluded = converter.filter_by_exposure(records, minimum=1.0)

        self.assertEqual(
            selected,
            [(Path("one.CR3"), {"exposure": 1.0}),
             (Path("thirty.CR3"), {"exposure": 30.0})],
        )
        self.assertEqual(
            excluded,
            [(Path("quarter.CR3"), {"exposure": 0.25}),
             (Path("unknown.CR3"), {"exposure": None})],
        )


if __name__ == "__main__":
    unittest.main()
