import bz2
import io
import tempfile
import unittest
import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from datetime import date
from pathlib import Path

import numpy as np
from astropy.io import fits

import download_mmt as m


class ArchiveTests(unittest.TestCase):
    def test_listing_real_trailing_slashes_and_equivalent_extensions(self):
        html = '<a href="x.fits.bz2/">x</a><a href="y.FIT.BZ2">y</a>'
        html += '<a href="z.fts.bz2">z</a><a href="a.jpg/">a</a>'
        html += '<a href="../escape.fits.bz2">bad</a>'
        links = m.fits_links(html, 'https://example.org/archive/2026-01-16/')
        self.assertEqual([x['filename'] for x in links], ['x.fits.bz2', 'y.FIT.BZ2', 'z.fts.bz2'])
        self.assertTrue(links[0]['source_url'].endswith('/x.fits.bz2'))

    def header(self):
        return fits.Header({'DATE-OBS': '2026-01-15T23:59:38.472000',
                            'DATE': '2026-01-16T07:00:00.602500',
                            'EXPOSURE': 20., 'SITELAT': '+31:41:12:00',
                            'SITELONG': '-110:53:03:00', 'STACKNB': 1})

    def test_local_time_is_not_misread_as_utc(self):
        result = m.exposure_metadata(self.header(), '2026_01_16__00_00_00.fits.bz2')
        self.assertEqual(result['utc_start'], '2026-01-16T06:59:38.472000Z')
        self.assertEqual(result['utc_end'], '2026-01-16T06:59:58.472000Z')

    def test_changed_clock_fails_closed(self):
        h = self.header()
        h['DATE'] = '2026-01-16T00:00:00.602500'
        with self.assertRaises(ValueError):
            m.exposure_metadata(h, '2026_01_16__00_00_00.fits.bz2')

    def test_nonfinite_and_stacked_exposure_rejected(self):
        for key, value in [('EXPOSURE', 'nan'), ('STACKNB', 2)]:
            h = self.header()
            h[key] = value
            with self.assertRaises(ValueError):
                m.exposure_metadata(h, '2026_01_16__00_00_00.fits.bz2')

    def test_original_bytes_preserved_and_truncation_rejected(self):
        buf = io.BytesIO()
        fits.PrimaryHDU(np.arange(6000, dtype=np.int16).reshape(3, 40, 50),
                        header=self.header()).writeto(buf)
        raw = buf.getvalue()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'image.fits.bz2'
            p.write_bytes(bz2.compress(raw))
            info, decoded = m.validate_file(p)
            self.assertEqual(decoded, raw)
            self.assertEqual(info['shapes'], [[3, 40, 50]])
            p.write_bytes(bz2.compress(raw)[:-10])
            with self.assertRaises((ValueError, EOFError, OSError)):
                m.validate_file(p)
            p.write_bytes(bz2.compress(raw[:-2880]))
            with self.assertRaises((ValueError, TypeError, OSError)):
                m.validate_file(p)

    def test_exposure_crossing_dawn_excluded(self):
        self.assertTrue(m.wholly_inside(10, 20, 9, 21))
        self.assertFalse(m.wholly_inside(10, 22, 9, 21))
        self.assertFalse(m.wholly_inside(9, 20, 9, 21))

    def test_full_interval_bound_catches_between_sample_crossing(self):
        self.assertGreater(m.interval_upper_bound(np.array([-0.1, -0.1]), 60), 0)

    def test_nearby_nights_under_conservative_horizon(self):
        a = m.Astronomy()
        self.assertFalse(a.night(date(2026, 1, 15))['qualifies'])
        n = a.night(date(2026, 1, 16))
        self.assertTrue(n['qualifies'])
        self.assertLess(n['moon_upper_limb_bound_relative_horizon_deg'], -7)
        self.assertEqual(m.archive_dates(n['dark_start_utc'], n['dark_end_utc']),
                         [date(2026, 1, 16)])


class NetworkTests(unittest.TestCase):
    def test_real_http_retry_resume_corruption_and_lossless_decompression(self):
        header = ArchiveTests().header()
        header['DATE-OBS'] = '2026-01-16T19:20:01'
        header['DATE'] = '2026-01-17T02:20:23'
        buf = io.BytesIO()
        fits.PrimaryHDU(np.arange(6000, dtype=np.int16).reshape(3, 40, 50), header=header).writeto(buf)
        raw = buf.getvalue()
        compressed = bz2.compress(raw)
        name = '2026_01_16__19_20_23.fits.bz2'
        counts = {'file': 0}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/archive/':
                    body = b'<a href="2026-01-16/">night</a>'
                elif self.path == '/archive/2026-01-16/':
                    body = f'<a href="{name}/">image</a>'.encode()
                else:
                    counts['file'] += 1
                    if counts['file'] == 1:
                        self.send_response(503)
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    body = compressed
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                args = SimpleNamespace(output=Path(d), timeout=3, retries=1, delay=.01,
                    start_date=date(2026, 1, 16), end_date=date(2026, 1, 16), near=date(2026, 1, 16),
                    base_url=f'http://127.0.0.1:{server.server_port}/archive/', max_probes=0,
                    refresh_headers=False, max_download_mib=0, min_free_mib=0,
                    decompress=True, workers=2, cadence_minutes=0)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.run(args), 0)
                original = Path(d) / 'originals' / '2026-01-16' / name
                self.assertEqual(original.read_bytes(), compressed)
                self.assertEqual(original.with_suffix('').read_bytes(), raw)
                self.assertEqual(counts['file'], 3)  # transient + header + full download
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.run(args), 0)
                self.assertEqual(counts['file'], 3)  # locally revalidated, no image GET
                original.write_bytes(compressed[:-10])
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.run(args), 0)
                self.assertEqual(counts['file'], 4)
                self.assertEqual(original.read_bytes(), compressed)
                report = json.loads((Path(d) / 'report.json').read_text())
                self.assertEqual(report['verified_downloads'], 1)
                self.assertFalse(report['coverage']['uninterrupted'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
