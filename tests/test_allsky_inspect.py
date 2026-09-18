from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from astropy.io import fits
import numpy as np

from allsky_download.inspect import (
    array_statistics,
    inspect_camera_raw,
    inspect_fits,
    inspect_hdf5,
)


class InspectionTests(unittest.TestCase):
    def test_array_statistics_report_actual_range_and_occupied_bits(self):
        record = array_statistics(np.array([0, 1, 255, 4095], dtype=np.uint16), 4095)
        self.assertEqual(record["dtype"], "uint16")
        self.assertEqual(record["minimum"], 0)
        self.assertEqual(record["maximum"], 4095)
        self.assertEqual(record["occupied_bits"], 12)
        self.assertEqual(record["distinct_values"], 4)
        self.assertEqual(record["saturation_fraction"], 0.25)

    def test_fits_inspection_visits_every_image_hdu(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.fits"
            fits.HDUList(
                [
                    fits.PrimaryHDU(np.array([[0, 1024]], dtype=np.uint16)),
                    fits.ImageHDU(np.array([[2, 3]], dtype=np.int16), name="AUX"),
                ]
            ).writeto(path)
            record = inspect_fits(path)
        self.assertEqual(record["format"], "fits")
        self.assertEqual([item["name"] for item in record["hdus"]], ["PRIMARY", "AUX"])
        self.assertEqual(record["hdus"][0]["bitpix"], 16)
        self.assertEqual(record["hdus"][0]["statistics"]["maximum"], 1024)

    def test_fits_camera_bit_depth_not_datamax_defines_saturation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "camera.fits"
            primary = fits.PrimaryHDU(np.array([[0, 1024, 32767]], dtype=np.int16))
            primary.header["BITCAMPX"] = 15
            primary.header["DATAMAX"] = 1024
            primary.writeto(path)
            statistics = inspect_fits(path)["hdus"][0]["statistics"]
        self.assertEqual(statistics["saturation_level"], 32767)
        self.assertAlmostEqual(statistics["saturation_fraction"], 1 / 3)

    @unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py is an isolated inspection dependency")
    def test_hdf5_inspection_recurses_through_groups_and_datasets(self):
        import h5py

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.h5"
            with h5py.File(path, "w") as handle:
                group = handle.create_group("images")
                data = group.create_dataset("raw", data=np.array([[0, 300]], dtype=np.uint16))
                data.attrs["bayer_pattern"] = "RGGB"
            record = inspect_hdf5(path)
        by_path = {item["path"]: item for item in record["objects"]}
        self.assertEqual(by_path["/images"]["kind"], "group")
        self.assertEqual(by_path["/images/raw"]["statistics"]["maximum"], 300)
        self.assertEqual(by_path["/images/raw"]["attributes"]["bayer_pattern"], "RGGB")

    def test_camera_raw_reads_sensor_array_without_postprocessing(self):
        class FakeRaw:
            raw_image_visible = np.array([[64, 1000], [2048, 4095]], dtype=np.uint16)
            raw_pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
            color_desc = b"RGBG"
            black_level_per_channel = [64, 65, 66, 67]
            white_level = 4095
            camera_white_level_per_channel = [4000, 4000, 4000, 4000]
            sizes = SimpleNamespace(raw_width=2, raw_height=2, width=2, height=2)
            other = SimpleNamespace(
                iso_speed=800,
                shutter_speed=30.0,
                aperture=2.8,
                focal_length=8.0,
                timestamp=datetime(2025, 6, 25, 4, 6, 1, tzinfo=timezone.utc),
                shot_order=0,
                artist=None,
            )

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def postprocess(self):
                raise AssertionError("embedded/rendered processing must not be used")

        record = inspect_camera_raw(Path("sample.cr2"), decoder_factory=lambda _: FakeRaw())
        self.assertEqual(record["bayer_pattern"], "RGGB")
        self.assertEqual(record["sensor"]["statistics"]["maximum"], 4095)
        self.assertEqual(record["metadata"]["iso"], 800)
        self.assertEqual(record["metadata"]["exposure_seconds"], 30.0)
        self.assertEqual(record["metadata"]["timestamp_utc"], "2025-06-25T04:06:01Z")


if __name__ == "__main__":
    unittest.main()
