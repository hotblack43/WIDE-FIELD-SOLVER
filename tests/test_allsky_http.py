from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from allsky_download.http import HttpClient, PermanentHttpError
from allsky_download.model import Candidate


def make_candidate(url, size):
    return Candidate(
        "test",
        "camera",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "2026-01-01T00:00:00Z",
        url,
        "raw.fit",
        size,
        {},
    )


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"raw-scientific-bytes\x00\xff"
        self.counts = {"listing": 0, "raw": 0, "missing": 0}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/listing":
                    outer.counts["listing"] += 1
                    body = b"<a href='raw.fit'>raw.fit</a>"
                    self.send_response(200)
                elif self.path == "/raw.fit":
                    outer.counts["raw"] += 1
                    if outer.counts["raw"] == 1:
                        body = b""
                        self.send_response(503)
                    else:
                        body = outer.payload
                        self.send_response(200)
                else:
                    outer.counts["missing"] += 1
                    body = b"missing"
                    self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_listing_and_retrying_atomic_download_preserve_bytes(self):
        client = HttpClient(timeout=3, retries=1, delay=0)
        self.assertIn("raw.fit", client.get_text(self.base + "/listing"))
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "raw.fit"
            downloaded = client.download_atomic(
                make_candidate(self.base + "/raw.fit", len(self.payload)), destination
            )
            self.assertEqual(destination.read_bytes(), self.payload)
            self.assertEqual(downloaded.size_bytes, len(self.payload))
            self.assertEqual(downloaded.sha256, hashlib.sha256(self.payload).hexdigest())
            self.assertEqual(list(Path(tmp).glob("*.part-*")), [])
        self.assertEqual(self.counts, {"listing": 1, "raw": 2, "missing": 0})

    def test_permanent_404_is_not_retried(self):
        client = HttpClient(timeout=3, retries=4, delay=0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PermanentHttpError):
                client.download_atomic(
                    make_candidate(self.base + "/missing.fit", None),
                    Path(tmp) / "missing.fit",
                )
        self.assertEqual(self.counts["missing"], 1)

    def test_advertised_size_mismatch_removes_partial_and_destination(self):
        client = HttpClient(timeout=3, retries=1, delay=0)
        self.counts["raw"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "raw.fit"
            with self.assertRaises(ValueError):
                client.download_atomic(
                    make_candidate(self.base + "/raw.fit", len(self.payload) + 1),
                    destination,
                )
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(tmp).glob("*.part-*")), [])


if __name__ == "__main__":
    unittest.main()
