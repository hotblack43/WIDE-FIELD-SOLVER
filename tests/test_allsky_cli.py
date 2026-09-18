from contextlib import redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import tempfile
import threading
import unittest

from allsky_download.cli import build_parser, run
from allsky_download.http import TransferError
from allsky_download.model import Candidate, Site


UTC = timezone.utc


class _FixtureAdapter:
    def __init__(self, base):
        self.base = base
        self.site = Site("fixture", "camera-a", "Fixture", "UTC", 1.0, 2.0, 3.0)

    def sites(self, camera_id):
        if camera_id is None or camera_id == self.site.camera_id:
            return (self.site,)
        raise ValueError(f"unknown fixture camera: {camera_id}")

    def list_candidates(self, client, site, date_range):
        client.get_text(self.base + "/listing")
        return (
            Candidate(
                "fixture",
                "camera-a",
                datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                "20260101_0000 UTC",
                self.base + "/first.raw",
                "first.raw",
                4,
                {},
            ),
            Candidate(
                "fixture",
                "camera-a",
                datetime(2026, 1, 1, 0, 11, tzinfo=UTC),
                "20260101_0011 UTC",
                self.base + "/second.raw",
                "second.raw",
                None,
                {},
            ),
        )


class _FixtureRegistry:
    def __init__(self, adapter):
        self.adapter = adapter

    def resolve_source_id(self, name):
        if name != "fixture":
            raise ValueError(name)
        return name

    def get_adapter(self, source_id):
        return self.adapter


class CliTests(unittest.TestCase):
    def setUp(self):
        self.counts = {"listing": 0, "first": 0, "second": 0}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/listing":
                    outer.counts["listing"] += 1
                    body = b"fixture listing"
                    status = 200
                elif self.path == "/first.raw":
                    outer.counts["first"] += 1
                    body = b"raw1"
                    status = 200
                elif self.path == "/second.raw":
                    outer.counts["second"] += 1
                    body = b"raw-two"
                    status = 200
                else:
                    body = b"missing"
                    status = 404
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.registry = _FixtureRegistry(_FixtureAdapter(self.base))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def parse(self, *extra):
        return build_parser().parse_args(
            ["--site", "fixture", "--date", "2026-01-01", *extra]
        )

    def test_defaults_are_safe(self):
        args = self.parse("--dry-run")
        self.assertEqual(args.cadence, "10m")
        self.assertEqual(args.max_files, 20)
        self.assertFalse(args.latest)

    def test_date_and_range_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "--site",
                    "fixture",
                    "--date",
                    "2026-01-01",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-02",
                ]
            )

    def test_invalid_limits_and_incomplete_range_are_rejected(self):
        for argv in (
            ["--site", "fixture", "--start", "2026-01-01"],
            ["--site", "fixture", "--date", "2026-01-01", "--max-files", "0"],
            ["--site", "fixture", "--date", "2026-01-01", "--timeout", "0"],
            ["--site", "fixture", "--date", "2026-01-01", "--timeout", "nan"],
            ["--site", "fixture", "--date", "2026-01-01", "--timeout", "inf"],
            ["--site", "fixture", "--date", "2026-01-01", "--retries", "-1"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                build_parser().parse_args(argv)

    def test_dry_run_lists_without_requesting_raw_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            stream = io.StringIO()
            with redirect_stdout(stream):
                status = run(
                    self.parse("--dry-run", "--output", str(output)),
                    registry=self.registry,
                )
            rendered = stream.getvalue()
            self.assertEqual(status, 0)
            self.assertIn("SELECT\t2026-01-01T00:00:00Z\tfixture\tcamera-a", rendered)
            self.assertIn(self.base + "/first.raw", rendered)
            self.assertIn("known_bytes=4", rendered)
            self.assertIn("unknown_sizes=1", rendered)
            self.assertFalse(output.exists())
        self.assertEqual(self.counts, {"listing": 1, "first": 0, "second": 0})

    def test_max_files_downloads_one_and_verified_rerun_skips_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            args = self.parse("--max-files", "1", "--output", str(output))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run(args, registry=self.registry), 0)
                self.assertEqual(run(args, registry=self.registry), 0)
            self.assertEqual(
                (output / "fixture" / "camera-a" / "first.raw").read_bytes(),
                b"raw1",
            )
            self.assertTrue((output / "manifest.sqlite").is_file())
        self.assertEqual(self.counts, {"listing": 2, "first": 1, "second": 0})

    def test_listing_transfer_error_returns_operational_failure(self):
        class FailingClient:
            def get_text(self, url):
                raise TransferError("temporary listing failure")

        with redirect_stdout(io.StringIO()):
            status = run(
                self.parse("--dry-run"),
                registry=self.registry,
                client=FailingClient(),
            )
        self.assertEqual(status, 2)


if __name__ == "__main__":
    unittest.main()
