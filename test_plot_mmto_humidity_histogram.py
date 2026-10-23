"""MMTO humidity summaries keep valid telemetry separate from missing data."""
from __future__ import annotations

import bz2
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest

from astropy.io import fits


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "plot_mmto_humidity_histogram.py"


def load_module():
    name = "_test_plot_mmto_humidity_histogram"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_compressed_fits(path: Path, humidity=...):
    header = fits.Header()
    header["DATE-OBS"] = "2026-10-21T23:40:32"
    if humidity is not ...:
        header["HUMIDITY"] = humidity
    payload = io.BytesIO()
    fits.PrimaryHDU(header=header).writeto(payload)
    path.write_bytes(bz2.compress(payload.getvalue()))


class MmtoHumidityHistogramTests(unittest.TestCase):
    def test_collect_classifies_unavailable_telemetry_without_rejecting_it(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [
                ("valid.fits.bz2", 42.5, "valid", 42.5),
                ("zero.fits.bz2", 0.0, "zero_placeholder", None),
                ("missing.fits.bz2", ..., "missing", None),
                ("invalid.fits.bz2", 105.0, "invalid", None),
            ]
            for name, humidity, _status, _value in cases:
                write_compressed_fits(root / name, humidity)

            records = module.collect_humidity_records(sorted(root.glob("*.bz2")))
            by_name = {Path(row["path"]).name: row for row in records}

            for name, _humidity, status, value in cases:
                self.assertEqual(by_name[name]["status"], status)
                self.assertEqual(by_name[name]["humidity_percent"], value)

    def test_main_writes_histogram_csv_and_summary(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            write_compressed_fits(archive / "a.fits.bz2", 20.0)
            write_compressed_fits(archive / "b.fits.bz2", 40.0)
            output = root / "humidity.png"
            csv_path = root / "humidity.csv"
            summary_path = root / "summary.json"

            return_code = module.main([
                "--archive", str(archive),
                "--output", str(output),
                "--csv", str(csv_path),
                "--summary", str(summary_path),
            ])

            self.assertEqual(return_code, 0)
            self.assertGreater(output.stat().st_size, 0)
            self.assertIn("humidity_percent", csv_path.read_text())
            self.assertIn('"valid": 2', summary_path.read_text())


if __name__ == "__main__":
    unittest.main()
