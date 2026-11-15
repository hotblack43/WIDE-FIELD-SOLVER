from contextlib import redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import sqlite3

from v24.allsky_download_v24.cli import (
    build_assign_existing_parser,
    build_parser,
    run,
    run_assign_existing,
)
from allsky_download.http import DownloadedFile, TransferError
from v24.allsky_download_v24.manifest import Manifest
from allsky_download.model import Candidate, Site


UTC = timezone.utc


class _FixtureAdapter:
    def __init__(self, base, *, first_at=None, second_at=None):
        self.base = base
        self.site = Site("fixture", "camera-a", "Fixture", "UTC", 1.0, 2.0, 3.0)
        self.first_at = first_at or datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        self.second_at = second_at or datetime(2026, 1, 1, 0, 11, tzinfo=UTC)

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
                self.first_at,
                "20260101_0000 UTC",
                self.base + "/first.raw",
                "first.raw",
                4,
                {},
            ),
            Candidate(
                "fixture",
                "camera-a",
                self.second_at,
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
        self.assertFalse(args.moon_down)
        self.assertIsNone(args.calibration_registry)

    def test_calibration_options_are_all_or_nothing(self):
        option_sets = (
            ("--calibration-registry", "registry.jsonl"),
            ("--installation-assignments", "assignments.jsonl"),
            ("--camera-orientation", "native"),
            (
                "--calibration-registry", "registry.jsonl",
                "--installation-assignments", "assignments.jsonl",
            ),
        )
        for options in option_sets:
            with self.subTest(options=options), self.assertRaises(SystemExit):
                self.parse("--dry-run", *options)

    def test_configured_download_assigns_before_reporting_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            assignments = Path(tmp) / "assignments.jsonl"
            args = self.parse(
                "--max-files", "1", "--output", str(output),
                "--calibration-registry", str(Path(tmp) / "registry.jsonl"),
                "--installation-assignments", str(assignments),
                "--camera-orientation", "native",
            )
            active = {"installation_id": "installation-a"}
            assigned = {"installation_id": "installation-a"}
            stream = io.StringIO()
            with mock.patch(
                "v24.visible_sky_registry.active_installation", return_value=active
            ), mock.patch(
                "v24.visible_sky_registry.assign_source", return_value=assigned
            ) as assign, redirect_stdout(stream):
                self.assertEqual(run(args, registry=self.registry), 0)
            self.assertIn("DOWNLOAD\t", stream.getvalue())
            assign.assert_called_once()
            with sqlite3.connect(output / "manifest.sqlite") as connection:
                row = connection.execute(
                    """
                    SELECT download_status, validation_status,
                           installation_assignment_status, installation_id
                    FROM downloads
                    """
                ).fetchone()
            self.assertEqual(
                row, ("downloaded", "verified", "assigned", "installation-a")
            )

    def test_assignment_failure_preserves_verified_file_and_reports_unassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            args = self.parse(
                "--max-files", "1", "--output", str(output),
                "--calibration-registry", str(Path(tmp) / "registry.jsonl"),
                "--installation-assignments", str(Path(tmp) / "assignments.jsonl"),
                "--camera-orientation", "native",
            )
            stream = io.StringIO()
            with mock.patch(
                "v24.visible_sky_registry.active_installation",
                return_value={"installation_id": "installation-a"},
            ), mock.patch(
                "v24.visible_sky_registry.assign_source",
                side_effect=ValueError("detector mismatch"),
            ), self.assertLogs("allsky_download.cli", level="ERROR"), redirect_stdout(stream):
                self.assertEqual(run(args, registry=self.registry), 2)
            self.assertIn("UNASSIGNED\t", stream.getvalue())
            downloaded = (
                output / "fixture" / "camera-a" / "2025-12-31" / "first.raw"
            )
            self.assertEqual(downloaded.read_bytes(), b"raw1")
            with sqlite3.connect(output / "manifest.sqlite") as connection:
                row = connection.execute(
                    """
                    SELECT download_status, validation_status,
                           installation_assignment_status,
                           installation_assignment_error
                    FROM downloads
                    """
                ).fetchone()
                jobs = connection.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()[0]
            self.assertEqual(row[:3], ("downloaded", "verified", "unassigned"))
            self.assertIn("detector mismatch", row[3])
            self.assertEqual(jobs, 0)

    def test_interrupted_assignment_leaves_verified_download_explicitly_unassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            args = self.parse(
                "--max-files", "1", "--output", str(output),
                "--calibration-registry", str(Path(tmp) / "registry.jsonl"),
                "--installation-assignments", str(Path(tmp) / "assignments.jsonl"),
                "--camera-orientation", "native",
            )
            with mock.patch(
                "v24.visible_sky_registry.active_installation",
                return_value={"installation_id": "installation-a"},
            ), mock.patch(
                "v24.visible_sky_registry.assign_source",
                side_effect=KeyboardInterrupt,
            ):
                self.assertEqual(run(args, registry=self.registry), 130)
            with sqlite3.connect(output / "manifest.sqlite") as connection:
                row = connection.execute(
                    """
                    SELECT download_status, validation_status,
                           installation_assignment_status,
                           installation_assignment_error
                    FROM downloads
                    """
                ).fetchone()
            self.assertEqual(row, (
                "downloaded", "verified", "unassigned", "assignment_pending"
            ))

    def test_assign_existing_is_bounded_and_preview_only_without_apply(self):
        parser = build_assign_existing_parser()
        required = [
            "--manifest", "/tmp/manifest.sqlite",
            "--archive-root", "/tmp/archive",
            "--source", "fixture",
            "--camera", "camera-a",
            "--limit", "1",
            "--calibration-registry", "/tmp/registry.jsonl",
            "--installation-assignments", "/tmp/assignments.jsonl",
            "--camera-orientation", "native",
        ]
        args = parser.parse_args(required)
        self.assertEqual(args.limit, 1)
        self.assertFalse(args.apply)
        for omitted in ("--source", "--camera", "--limit"):
            reduced = required[:]
            index = reduced.index(omitted)
            del reduced[index:index + 2]
            with self.subTest(omitted=omitted), self.assertRaises(SystemExit):
                parser.parse_args(reduced)

    def test_assign_existing_previews_then_applies_only_selected_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            root.mkdir()
            manifest_path = root / "manifest.sqlite"
            candidates = []
            with Manifest(manifest_path) as manifest:
                for index in range(2):
                    candidate = Candidate(
                        "fixture", "camera-a",
                        datetime(2026, 1, 1, 0, index, tzinfo=UTC),
                        f"2026-01-01T00:0{index}:00Z",
                        f"https://example.test/{index}.fits", f"{index}.fits",
                        4, {},
                    )
                    path = root / f"{index}.fits"
                    path.write_bytes(f"raw{index}".encode())
                    import hashlib
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    manifest.record_attempt(candidate)
                    manifest.record_success(
                        candidate, DownloadedFile(path, 4, digest), root
                    )
                    candidates.append((candidate, digest))
            argv = [
                "--manifest", str(manifest_path),
                "--archive-root", str(root.resolve()),
                "--source", "fixture", "--camera", "camera-a",
                "--limit", "1",
                "--calibration-registry", str(Path(tmp) / "registry.jsonl"),
                "--installation-assignments", str(Path(tmp) / "assignments.jsonl"),
                "--camera-orientation", "native",
            ]
            preview = io.StringIO()
            with mock.patch(
                "v24.visible_sky_registry.active_installation",
                return_value={"installation_id": "installation-a"},
            ), mock.patch("v24.visible_sky_registry.assign_source") as assign, redirect_stdout(preview):
                status = run_assign_existing(
                    build_assign_existing_parser().parse_args(argv)
                )
            self.assertEqual(status, 0)
            self.assertIn(candidates[0][1], preview.getvalue())
            self.assertNotIn(candidates[1][1], preview.getvalue())
            assign.assert_not_called()

            with mock.patch(
                "v24.visible_sky_registry.active_installation",
                return_value={"installation_id": "installation-a"},
            ), mock.patch(
                "v24.visible_sky_registry.assign_source",
                return_value={"installation_id": "installation-a"},
            ) as assign, redirect_stdout(io.StringIO()):
                status = run_assign_existing(
                    build_assign_existing_parser().parse_args([*argv, "--apply"])
                )
            self.assertEqual(status, 0)
            assign.assert_called_once()
            with sqlite3.connect(manifest_path) as connection:
                statuses = connection.execute(
                    """
                    SELECT installation_assignment_status FROM downloads
                    ORDER BY observed_utc
                    """
                ).fetchall()
            self.assertEqual(statuses, [("assigned",), (None,)])

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

    def test_night_is_mutually_exclusive_with_civil_periods(self):
        for extra in (
            ["--date", "2026-01-01"],
            ["--start", "2026-01-01", "--end", "2026-01-02"],
        ):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                build_parser().parse_args(
                    ["--site", "fixture", "--night", "2026-01-01", *extra]
                )

    def test_invalid_limits_and_incomplete_range_are_rejected(self):
        for argv in (
            ["--site", "fixture", "--start", "2026-01-01"],
            ["--site", "fixture", "--date", "2026-01-01", "--max-files", "0"],
            ["--site", "fixture", "--date", "2026-01-01", "--timeout", "0"],
            ["--site", "fixture", "--date", "2026-01-01", "--timeout", "nan"],
            ["--site", "fixture", "--date", "2026-01-01", "--timeout", "inf"],
            ["--site", "fixture", "--date", "2026-01-01", "--retries", "-1"],
            ["--site", "fixture", "--date", "2026-01-01", "--sun-below", "-91"],
            ["--site", "fixture", "--date", "2026-01-01", "--sun-below", "91"],
            ["--site", "fixture", "--date", "2026-01-01", "--sun-below", "nan"],
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

    def test_solar_filter_removes_daytime_candidate_before_selection(self):
        adapter = _FixtureAdapter(
            self.base,
            first_at=datetime(2026, 3, 20, 0, 0, tzinfo=UTC),
            second_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        )
        adapter.site = Site("fixture", "camera-a", "Equator", "UTC", 0.0, 0.0, 0.0)
        args = build_parser().parse_args(
            [
                "--site", "fixture",
                "--date", "2026-03-20",
                "--sun-below", "0",
                "--dry-run",
            ]
        )
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = run(args, registry=_FixtureRegistry(adapter))
        rendered = stream.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("first.raw", rendered)
        self.assertNotIn("second.raw", rendered)

    def test_moon_down_removes_moon_up_candidate_before_selection(self):
        adapter = _FixtureAdapter(
            self.base,
            first_at=datetime(2026, 3, 20, 0, 0, tzinfo=UTC),
            second_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        )
        adapter.site = Site("fixture", "camera-a", "Equator", "UTC", 0.0, 0.0, 0.0)
        args = build_parser().parse_args(
            [
                "--site", "fixture",
                "--date", "2026-03-20",
                "--moon-down",
                "--dry-run",
            ]
        )
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = run(args, registry=_FixtureRegistry(adapter))
        rendered = stream.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("first.raw", rendered)
        self.assertNotIn("second.raw", rendered)

    def test_solar_filter_refuses_missing_site_coordinates_before_listing(self):
        class CoordinateLessAdapter:
            def __init__(self):
                self.listed = False
                self.site = Site(
                    "fixture", "camera-a", "Unknown", "UTC", None, None, None
                )

            def sites(self, camera_id):
                return (self.site,)

            def list_candidates(self, client, site, date_range):
                self.listed = True
                return ()

        adapter = CoordinateLessAdapter()
        args = build_parser().parse_args(
            [
                "--site", "fixture",
                "--date", "2026-03-20",
                "--sun-below", "0",
                "--dry-run",
            ]
        )
        with self.assertLogs("allsky_download.cli", level="ERROR") as logs:
            status = run(args, registry=_FixtureRegistry(adapter))
        self.assertEqual(status, 2)
        self.assertFalse(adapter.listed)
        self.assertIn("latitude and longitude", "\n".join(logs.output))

    def test_moon_filter_refuses_missing_site_coordinates_before_listing(self):
        class CoordinateLessAdapter:
            def __init__(self):
                self.listed = False
                self.site = Site(
                    "fixture", "camera-a", "Unknown", "UTC", None, None, None
                )

            def sites(self, camera_id):
                return (self.site,)

            def list_candidates(self, client, site, date_range):
                self.listed = True
                return ()

        adapter = CoordinateLessAdapter()
        args = build_parser().parse_args(
            [
                "--site", "fixture",
                "--date", "2026-03-20",
                "--moon-down",
                "--dry-run",
            ]
        )
        with self.assertLogs("allsky_download.cli", level="ERROR") as logs:
            status = run(args, registry=_FixtureRegistry(adapter))
        self.assertEqual(status, 2)
        self.assertFalse(adapter.listed)
        self.assertIn("latitude and longitude", "\n".join(logs.output))

    def test_max_files_downloads_one_and_verified_rerun_skips_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            args = self.parse("--max-files", "1", "--output", str(output))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run(args, registry=self.registry), 0)
                self.assertEqual(run(args, registry=self.registry), 0)
            self.assertEqual(
                (
                    output
                    / "fixture"
                    / "camera-a"
                    / "2025-12-31"
                    / "first.raw"
                ).read_bytes(),
                b"raw1",
            )
            self.assertTrue((output / "manifest.sqlite").is_file())
        self.assertEqual(self.counts, {"listing": 2, "first": 1, "second": 0})

    def test_backfill_missing_gets_oldest_unrecorded_slot_after_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "samples"
            latest = self.parse(
                "--max-files", "1", "--latest", "--output", str(output)
            )
            backfill = self.parse(
                "--max-files", "1", "--backfill-missing", "--output", str(output)
            )
            dry_backfill = self.parse(
                "--max-files", "1", "--backfill-missing", "--dry-run",
                "--output", str(output)
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run(latest, registry=self.registry), 0)
                self.assertEqual(run(backfill, registry=self.registry), 0)
            preview = io.StringIO()
            with redirect_stdout(preview):
                self.assertEqual(run(dry_backfill, registry=self.registry), 0)
            self.assertIn("SUMMARY\tselected=0\teligible=0", preview.getvalue())
            self.assertTrue((
                output / "fixture" / "camera-a" / "2025-12-31" / "first.raw"
            ).is_file())
            self.assertTrue((
                output / "fixture" / "camera-a" / "2025-12-31" / "second.raw"
            ).is_file())
        self.assertEqual(self.counts, {"listing": 3, "first": 1, "second": 1})

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

    def test_processing_enqueue_refuses_a_non_mmto_source_before_listing(self):
        args = self.parse("--enqueue-processing", "--dry-run")
        with self.assertLogs("allsky_download.cli", level="ERROR") as logs:
            status = run(args, registry=self.registry)
        self.assertEqual(status, 2)
        self.assertEqual(self.counts["listing"], 0)
        self.assertIn("only enabled for mmto", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
