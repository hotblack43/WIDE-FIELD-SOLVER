"""Authoritative MMTO FITS-header observation-time tests."""
from __future__ import annotations

import bz2
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest

import numpy as np
from astropy.io import fits


UTC = timezone.utc


def _old_header() -> fits.Header:
    return fits.Header(
        {
            "INSTRUME": "ZWO ASI294MC Pro",
            "SITELAT": "31:41:12:0",
            "SITELONG": "-110:53:03:0",
            "STACKNB": 1,
            "DATE-OBS": "2026-09-19T02:19:40.204800",
            "UT": "02:19:40.20",
            "EXPTIME": 20.0,
            "DATE": "2026-09-19T09:20:07.884500",
        }
    )


def _new_header() -> fits.Header:
    return fits.Header(
        {
            "INSTRUME": "ZWO ASI294MC Pro",
            "SITELAT": "31:41:12:0",
            "SITELONG": "-110:53:03:0",
            "STACKNB": 1,
            "DATE-OBS": "2026-10-16T05:19:44.386298",
            "DATE-BEG": "2026-10-16T12:19:44.386298",
            "DATE-END": "2026-10-16T12:20:04.386298",
            "EXPTIME": 20.0,
        }
    )


def _write(path: Path, header: fits.Header, *, compressed: bool = False) -> None:
    stream = io.BytesIO()
    fits.PrimaryHDU(np.zeros((4, 4), dtype=np.uint16), header).writeto(stream)
    payload = stream.getvalue()
    path.write_bytes(bz2.compress(payload) if compressed else payload)


class MMTOTimeTests(unittest.TestCase):
    def test_old_header_accepts_observed_camera_serial_suffix(self):
        from v23.mmto_time import read_mmto_observation

        header = _old_header()
        header["INSTRUME"] = "ZWO ASI294MC Pro (21599760)"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "serial.fits"
            _write(path, header)
            value = read_mmto_observation(path)

        self.assertEqual(value.instrument, "ZWO ASI294MC Pro (21599760)")

    def test_old_header_uses_arizona_local_start_and_exposure_midpoint(self):
        from v23.mmto_time import read_mmto_observation

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "misleading_2099_01_01__00_00_00.fits"
            _write(path, _old_header())
            value = read_mmto_observation(path)

        self.assertEqual(
            value.start_utc,
            datetime(2026, 9, 19, 9, 19, 40, 204800, tzinfo=UTC),
        )
        self.assertEqual(
            value.midpoint_utc,
            datetime(2026, 9, 19, 9, 19, 50, 204800, tzinfo=UTC),
        )
        self.assertEqual(value.exposure_seconds, 20.0)
        self.assertEqual(value.schema, "mmto_skywatch_local_date_obs")
        self.assertNotIn("filename", value.provenance.lower())

    def test_new_header_uses_utc_date_beg_and_checks_local_clock(self):
        from v23.mmto_time import read_mmto_observation

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.fits"
            _write(path, _new_header())
            value = read_mmto_observation(path)

        self.assertEqual(
            value.start_utc,
            datetime(2026, 10, 16, 12, 19, 44, 386298, tzinfo=UTC),
        )
        self.assertEqual(
            value.midpoint_utc,
            datetime(2026, 10, 16, 12, 19, 54, 386298, tzinfo=UTC),
        )
        self.assertEqual(value.schema, "mmto_skywatch_utc_date_beg")

    def test_bz2_and_filename_independence(self):
        from v23.mmto_time import read_mmto_observation

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "2026_09_19__02_20_01.fits.bz2"
            second = root / "totally-wrong-name.fits.bz2"
            _write(first, _old_header(), compressed=True)
            second.write_bytes(first.read_bytes())

            one = read_mmto_observation(first)
            two = read_mmto_observation(second)

        self.assertEqual(one, two)

    def test_old_header_rejects_conflicting_ut_and_creation_clock(self):
        from v23.mmto_time import read_mmto_observation

        cases = []
        ut = _old_header()
        ut["UT"] = "03:19:40.20"
        cases.append((ut, "UT"))
        created = _old_header()
        created["DATE"] = "2026-09-19T02:20:07.884500"
        cases.append((created, "DATE"))
        with tempfile.TemporaryDirectory() as directory:
            for index, (header, message) in enumerate(cases):
                with self.subTest(message=message):
                    path = Path(directory) / f"old-{index}.fits"
                    _write(path, header)
                    with self.assertRaisesRegex(ValueError, message):
                        read_mmto_observation(path)

    def test_new_header_rejects_conflicting_local_start_and_end(self):
        from v23.mmto_time import read_mmto_observation

        cases = []
        local = _new_header()
        local["DATE-OBS"] = "2026-10-16T04:19:44.386298"
        cases.append((local, "DATE-OBS"))
        end = _new_header()
        end["DATE-END"] = "2026-10-16T12:20:14.386298"
        cases.append((end, "DATE-END"))
        with tempfile.TemporaryDirectory() as directory:
            for index, (header, message) in enumerate(cases):
                with self.subTest(message=message):
                    path = Path(directory) / f"new-{index}.fits"
                    _write(path, header)
                    with self.assertRaisesRegex(ValueError, message):
                        read_mmto_observation(path)

    def test_missing_exposure_is_rejected_without_filename_fallback(self):
        from v23.mmto_time import read_mmto_observation

        header = _old_header()
        del header["EXPTIME"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026_09_19__02_20_01.fits"
            _write(path, header)
            with self.assertRaisesRegex(ValueError, "exposure"):
                read_mmto_observation(path)


if __name__ == "__main__":
    unittest.main()
