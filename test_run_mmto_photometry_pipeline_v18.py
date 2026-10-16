"""Bounded MMTO acquisition and analysis behavior for v18."""
from __future__ import annotations

from datetime import date
import hashlib
import importlib
import io
import inspect
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from allsky_download.cadence import site_night_range
from allsky_download.http import DownloadedFile
from allsky_download.model import Candidate
from allsky_download.registry import SourceRegistry


ROOT = Path(__file__).resolve().parent
PIPELINE = importlib.import_module("scripts.run_mmto_photometry_pipeline_v18")


class MmtoV18PipelinePresenceTests(unittest.TestCase):
    def test_versioned_pipeline_and_launcher_exist(self):
        self.assertTrue(
            (ROOT / "scripts/run_mmto_photometry_pipeline_v18.py").is_file()
        )
        self.assertTrue((ROOT / "go_mmto_photometry_v18.sh").is_file())


class MmtoV18AcquisitionPolicyTests(unittest.TestCase):
    def test_one_range_scan_selects_two_newest_analysis_incomplete_nights(self):
        self.assertTrue(hasattr(PIPELINE, "build_acquisition_plan"))
        self.assertIn(
            "results_database",
            inspect.signature(PIPELINE.build_acquisition_plan).parameters,
        )
        site = SourceRegistry.from_json(ROOT / "sources.json").get_adapter(
            "mmto"
        ).sites("mmto-skycam")[0]
        candidates = tuple(
            Candidate(
                "mmto",
                "mmto-skycam",
                __import__("datetime").datetime.fromisoformat(observed),
                observed,
                f"https://mmto/{name}",
                f"{name}.fits.bz2",
                None,
                {},
            )
            for name, observed in (
                ("old", "2026-07-01T05:00:00+00:00"),
                ("cadence-chaff", "2026-07-01T05:05:00+00:00"),
                ("done", "2026-07-02T05:00:00+00:00"),
                ("new", "2026-07-03T05:00:00+00:00"),
                ("newest", "2026-07-04T05:00:00+00:00"),
                ("daylight", "2026-07-02T19:00:00+00:00"),
            )
        )

        class Listing:
            def __init__(self):
                self.ranges = []

            def list_candidates(self, _client, _site, date_range):
                self.ranges.append(date_range)
                return candidates

        listing = Listing()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                        observed_utc TEXT, observed_raw TEXT, remote_filename TEXT,
                        local_path TEXT, advertised_bytes INTEGER,
                        observed_bytes INTEGER, sha256 TEXT,
                        download_status TEXT, validation_status TEXT,
                        attempted_utc TEXT, error TEXT, inspector_kind TEXT,
                        inspection_id TEXT
                    )
                    """
                )
                database.executemany(
                    "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        (
                            "https://mmto/done", "mmto", "mmto-skycam",
                            "2026-07-02T05:00:00Z", "recorded", "done.fits.bz2",
                            "mmto/mmto-skycam/2026-07-01/done.fits.bz2",
                            None, 1, "done-digest", "downloaded", "verified",
                            "2026-07-02T05:01:00Z", None, None, None,
                        ),
                        (
                            "https://mmto/new", "mmto", "mmto-skycam",
                            "2026-07-03T05:00:00Z", "recorded", "new.fits.bz2",
                            "mmto/mmto-skycam/2026-07-02/new.fits.bz2",
                            None, 1, "new-digest", "downloaded", "verified",
                            "2026-07-03T05:01:00Z", None, None, None,
                        ),
                    ),
                )
            results = archive / "stars.sqlite"
            with sqlite3.connect(results) as database:
                database.execute(
                    "CREATE TABLE runs (source_sha256 TEXT, solver_version TEXT, "
                    "exit_code INTEGER, source_manifest_json TEXT)"
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    (
                        ("done-digest", "0.16.0", 0, '{"version":"0.16.0"}'),
                        ("new-digest", "0.17.0", 0, '{"version":"0.17.0"}'),
                    ),
                )

            plan = PIPELINE.build_acquisition_plan(
                archive,
                date(2026, 6, 30),
                date(2026, 7, 3),
                results_database=results,
                adapter=listing,
                client=object(),
                site=site,
            )

        self.assertEqual(len(listing.ranges), 1)
        self.assertEqual(
            listing.ranges[0].start_utc,
            site_night_range(site, date(2026, 6, 30)).start_utc,
        )
        self.assertEqual(
            listing.ranges[0].end_utc,
            site_night_range(site, date(2026, 7, 3)).end_utc,
        )
        self.assertEqual(plan.nights_scanned, 4)
        self.assertEqual(plan.files_selected, 4)
        self.assertEqual(
            [candidate.filename for candidate in plan.missing],
            ["newest.fits.bz2"],
        )
        self.assertEqual(plan.backlog_files_missing, 2)
        self.assertEqual(plan.backlog_files_incomplete, 3)
        self.assertEqual(
            plan.selected_nights,
            (date(2026, 7, 3), date(2026, 7, 2)),
        )

    def test_observing_nights_are_inclusive_and_newest_first(self):
        self.assertTrue(hasattr(PIPELINE, "observing_nights"))
        self.assertEqual(
            PIPELINE.observing_nights(date(2026, 6, 30), date(2026, 7, 2)),
            (date(2026, 7, 2), date(2026, 7, 1), date(2026, 6, 30)),
        )

    def test_sync_downloads_missing_file_once_and_reuses_verified_manifest(self):
        self.assertIn("adapter", inspect.signature(PIPELINE.sync_downloads).parameters)
        site = SourceRegistry.from_json(ROOT / "sources.json").get_adapter(
            "mmto"
        ).sites("mmto-skycam")[0]
        candidate = Candidate(
            "mmto", "mmto-skycam",
            __import__("datetime").datetime.fromisoformat(
                "2026-07-01T05:00:00+00:00"
            ),
            "2026-07-01T05:00:00Z", "https://mmto/frame",
            "frame.fits.bz2", None, {},
        )

        class Adapter:
            def list_candidates(self, _client, _site, _date_range):
                return (candidate,)

        class Client:
            def download_atomic(self, _candidate, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"native-fits")
                return DownloadedFile(
                    destination,
                    len(b"native-fits"),
                    hashlib.sha256(b"native-fits").hexdigest(),
                )

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)
            dry = PIPELINE.sync_downloads(
                archive,
                date(2026, 6, 30),
                date(2026, 6, 30),
                results_database=archive / "stars.sqlite",
                dry_run=True,
                adapter=Adapter(),
                client=Client(),
                site=site,
            )
            first = PIPELINE.sync_downloads(
                archive,
                date(2026, 6, 30),
                date(2026, 6, 30),
                results_database=archive / "stars.sqlite",
                dry_run=False,
                adapter=Adapter(),
                client=Client(),
                site=site,
            )
            second = PIPELINE.sync_downloads(
                archive,
                date(2026, 6, 30),
                date(2026, 6, 30),
                results_database=archive / "stars.sqlite",
                dry_run=False,
                adapter=Adapter(),
                client=Client(),
                site=site,
            )
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                row = database.execute(
                    "SELECT download_status, validation_status FROM downloads"
                ).fetchone()

        self.assertEqual(
            (dry.files_selected, dry.files_missing, dry.files_downloaded),
            (1, 1, 0),
        )
        self.assertEqual(getattr(dry, "backlog_files_missing", None), 1)
        self.assertEqual(
            getattr(dry, "selected_nights", None),
            (date(2026, 6, 30),),
        )
        self.assertEqual(
            (first.files_selected, first.files_missing, first.files_downloaded),
            (1, 1, 1),
        )
        self.assertEqual(
            (second.files_selected, second.files_missing, second.files_downloaded),
            (1, 0, 0),
        )
        self.assertEqual(row, ("downloaded", "verified"))

    def test_launcher_help_states_fixed_boundary_and_two_night_download_cap(self):
        answer = subprocess.run(
            [str(ROOT / "go_mmto_photometry_v18.sh"), "--help"],
            cwd="/tmp",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(answer.returncode, 0, answer.stdout)
        help_text = " ".join(answer.stdout.lower().split())
        self.assertIn("2026-06-30", help_text)
        self.assertIn("at most two", help_text)


class MmtoV18AnalysisPolicyTests(unittest.TestCase):
    def test_plan_skips_successful_v16_or_v18_but_retries_failed_receipts(self):
        self.assertTrue(hasattr(PIPELINE, "build_processing_plan"))
        self.assertIn(
            "selected_nights",
            inspect.signature(PIPELINE.build_processing_plan).parameters,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            rows = []
            for index, (name, night) in enumerate(
                (
                    ("ancient", "2026-06-29"),
                    ("unselected", "2026-06-30"),
                    ("v16", "2026-06-30"),
                    ("failed-v18", "2026-07-01"),
                    ("successful-v18", "2026-07-01"),
                    ("new", "2026-07-02"),
                ),
                1,
            ):
                rows.append(
                    (
                        f"https://mmto/{name}",
                        "mmto",
                        "mmto-skycam",
                        f"{night}T03:00:00Z",
                        f"mmto/mmto-skycam/{night}/{name}.fits.bz2",
                        index,
                        hashlib.sha256(name.encode()).hexdigest(),
                        "downloaded",
                        "verified",
                    )
                )
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                        observed_utc TEXT, local_path TEXT, observed_bytes INTEGER,
                        sha256 TEXT, download_status TEXT, validation_status TEXT
                    )
                    """
                )
                database.executemany(
                    "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)", rows
                )
            results = root / "stars.sqlite"
            with sqlite3.connect(results) as database:
                database.execute(
                    "CREATE TABLE runs (source_sha256 TEXT, solver_version TEXT, "
                    "exit_code INTEGER, source_manifest_json TEXT)"
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    (
                        (rows[2][6], "0.16.0", 0, '{"version":"0.16.0"}'),
                        (rows[3][6], "0.18.0", 1, '{"version":"0.18.0"}'),
                        (rows[4][6], "0.18.0", 0, '{"version":"0.18.0"}'),
                    ),
                )

            plan = PIPELINE.build_processing_plan(
                archive,
                results,
                start_night=date(2026, 6, 30),
                end_night=date(2026, 7, 2),
                selected_nights=(date(2026, 7, 2), date(2026, 7, 1)),
            )

        self.assertEqual(plan.eligible_images, 5)
        self.assertEqual(plan.successful_receipts, 2)
        self.assertEqual(
            [image.local_path.name for image in plan.pending],
            ["new.fits.bz2", "failed-v18.fits.bz2"],
        )

    def test_solver_command_uses_only_v18_and_the_selected_results_directory(self):
        self.assertTrue(hasattr(PIPELINE, "solver_command"))
        self.assertEqual(
            PIPELINE.solver_command(
                Path("/repo"), Path("/archive/night/image.fits.bz2"), Path("/results")
            ),
            [
                "/repo/go18.sh",
                "/archive/night/image.fits.bz2",
                "--results-dir",
                "/results",
            ],
        )


class MmtoV18PipelineIntegrationTests(unittest.TestCase):
    def test_dry_run_scans_the_complete_boundary_without_writing_products(self):
        self.assertIn("--repo-root", PIPELINE._build_parser()._option_string_actions)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            archive.mkdir()
            results.mkdir()
            payload = b"verified-image"
            digest = hashlib.sha256(payload).hexdigest()
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                        observed_utc TEXT, local_path TEXT, observed_bytes INTEGER,
                        sha256 TEXT, download_status TEXT, validation_status TEXT
                    )
                    """
                )
                database.execute(
                    "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        "https://mmto/frame", "mmto", "mmto-skycam",
                        "2026-07-01T03:00:00Z",
                        "mmto/mmto-skycam/2026-06-30/frame.fits.bz2",
                        len(payload), digest, "downloaded", "verified",
                    ),
                )

            output = io.StringIO()
            acquisition = PIPELINE.AcquisitionSummary(
                2,
                1,
                1,
                0,
                5,
                (date(2026, 7, 1), date(2026, 6, 30)),
            )
            with mock.patch.object(
                PIPELINE, "sync_downloads", return_value=acquisition
            ):
                with redirect_stdout(output):
                    return_code = PIPELINE.main(
                        [
                            "--repo-root", str(root),
                            "--archive", str(archive),
                            "--results-dir", str(results),
                            "--start-night", "2026-06-30",
                            "--end-night", "2026-07-01",
                            "--dry-run",
                        ]
                    )

            self.assertEqual(return_code, 0)
            report = output.getvalue()
            self.assertIn(
                "MMTO_ACQUISITION start=2026-06-30 end=2026-07-01 "
                "nights=2 backlog_incomplete=0 backlog_missing=5 "
                "selected_nights=2026-07-01,2026-06-30 "
                "scheduled_missing=1 downloaded=0 mode=dry-run",
                report,
            )
            self.assertIn(
                "MMTO_ANALYSIS eligible=1 successful_v16_or_v18=0 "
                "selected_nights=2026-07-01,2026-06-30 pending_selected=1",
                report,
            )
            self.assertNotIn("SELECT", report)
            self.assertFalse((results / "photometry-runs").exists())

    def test_real_run_downloads_then_processes_pending_image_once_with_v18(self):
        self.assertIn("--lock-file", PIPELINE._build_parser()._option_string_actions)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            output = root / "pipeline-output"
            archive.mkdir()
            results.mkdir()
            source_relative = Path(
                "mmto/mmto-skycam/2026-06-30/frame.fits.bz2"
            )
            source = archive / source_relative
            source.parent.mkdir(parents=True)
            source.write_bytes(b"verified-image")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with sqlite3.connect(archive / "manifest.sqlite") as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY, source_id TEXT, camera_id TEXT,
                        observed_utc TEXT, local_path TEXT, observed_bytes INTEGER,
                        sha256 TEXT, download_status TEXT, validation_status TEXT
                    )
                    """
                )
                database.execute(
                    "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        "https://mmto/frame", "mmto", "mmto-skycam",
                        "2026-07-01T03:00:00Z", source_relative.as_posix(),
                        source.stat().st_size, digest, "downloaded", "verified",
                    ),
                )
            solver = root / "go18.sh"
            solver.write_text(
                "#!/usr/bin/env python3\n"
                "import hashlib, json, sqlite3, sys\n"
                "from pathlib import Path\n"
                "source = Path(sys.argv[1])\n"
                "results = Path(sys.argv[sys.argv.index('--results-dir') + 1])\n"
                "digest = hashlib.sha256(source.read_bytes()).hexdigest()\n"
                "with sqlite3.connect(results / 'stars.sqlite') as database:\n"
                "    database.execute('CREATE TABLE IF NOT EXISTS runs "
                "(source_sha256 TEXT, solver_version TEXT, exit_code INTEGER, "
                "source_manifest_json TEXT)')\n"
                "    database.execute('INSERT INTO runs VALUES (?,?,?,?)', "
                "(digest, '0.18.0', 0, json.dumps({'version':'0.18.0'})))\n"
                "print('fake v18 solve complete')\n",
                encoding="utf-8",
            )
            solver.chmod(0o755)
            for name in (
                "plot_mmto_lightcurves.sh",
                "calibrate_mmto_extinction.sh",
                "plot_ALL_planets.sh",
                "plot_planet_empirical_extinction.sh",
            ):
                stage = root / name
                stage.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                stage.chmod(0o755)

            acquisition = PIPELINE.AcquisitionSummary(
                1, 1, 0, 0, 0, (date(2026, 6, 30),)
            )
            with mock.patch.object(
                PIPELINE, "sync_downloads", return_value=acquisition
            ):
                return_code = PIPELINE.main(
                    [
                        "--repo-root", str(root),
                        "--archive", str(archive),
                        "--results-dir", str(results),
                        "--output", str(output),
                        "--lock-file", str(root / "pipeline.lock"),
                        "--start-night", "2026-06-30",
                        "--end-night", "2026-06-30",
                    ]
                )

            self.assertEqual(return_code, 0)
            summary = __import__("json").loads(
                (output / "pipeline_summary.json").read_text()
            )
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["acquisition"]["nights_scanned"], 1)
            self.assertEqual(summary["acquisition"]["backlog_files_missing"], 0)
            self.assertEqual(
                summary["acquisition"]["selected_nights"], ["2026-06-30"]
            )
            self.assertEqual(summary["processing"]["attempted"], 1)
            self.assertEqual(summary["processing"]["succeeded"], 1)
            self.assertEqual(summary["processing"]["solver_failed"], 0)
            with sqlite3.connect(results / "stars.sqlite") as database:
                receipts = database.execute(
                    "SELECT solver_version, exit_code FROM runs"
                ).fetchall()
            self.assertEqual(receipts, [("0.18.0", 0)])


if __name__ == "__main__":
    unittest.main()
