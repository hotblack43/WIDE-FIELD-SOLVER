from __future__ import annotations

import gc
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings


from scripts.run_mmto_photometry_pipeline import (
    _run_command,
    build_processing_plan,
    main,
)


def create_manifest(path: Path, images: list[tuple[str, str, str]]) -> None:
    """Create a manifest from (observed UTC, relative path, contents)."""

    with sqlite3.connect(path) as database:
        database.execute(
            """
            CREATE TABLE downloads (
                remote_url TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                observed_utc TEXT NOT NULL,
                local_path TEXT,
                observed_bytes INTEGER,
                sha256 TEXT,
                download_status TEXT NOT NULL,
                validation_status TEXT NOT NULL
            )
            """
        )
        for number, (observed_utc, relative, contents) in enumerate(images):
            encoded = contents.encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()
            database.execute(
                "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"https://mmto/{number}",
                    "mmto",
                    "mmto-skycam",
                    observed_utc,
                    relative,
                    len(encoded),
                    digest,
                    "downloaded",
                    "verified",
                ),
            )


def create_results(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            """
            CREATE TABLE runs (
                source_sha256 TEXT,
                solver_version TEXT,
                exit_code INTEGER,
                source_manifest_json TEXT
            )
            """
        )


def write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


class MmtoPhotometryPipelineSelectionTests(unittest.TestCase):
    def test_plan_skips_successful_and_failed_v11_receipts_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            manifest = archive / "manifest.sqlite"
            with sqlite3.connect(manifest) as database:
                database.execute(
                    """
                    CREATE TABLE downloads (
                        remote_url TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        camera_id TEXT NOT NULL,
                        observed_utc TEXT NOT NULL,
                        local_path TEXT,
                        observed_bytes INTEGER,
                        sha256 TEXT,
                        download_status TEXT NOT NULL,
                        validation_status TEXT NOT NULL
                    )
                    """
                )
                rows = (
                    ("https://mmto/a", "mmto", "mmto-skycam", "2026-08-01T01:00:00Z", "mmto/a.fits", 10, "a" * 64, "downloaded", "verified"),
                    ("https://mmto/b", "mmto", "mmto-skycam", "2026-08-01T02:00:00Z", "mmto/b.fits", 20, "b" * 64, "downloaded", "verified"),
                    ("https://mmto/c", "mmto", "mmto-skycam", "2026-08-01T03:00:00Z", "mmto/c.fits", 30, "c" * 64, "downloaded", "verified"),
                    ("https://mmto/d", "mmto", "mmto-skycam", "2026-08-01T04:00:00Z", "mmto/d.fits", 40, "d" * 64, "downloaded", "verified"),
                    ("https://other/e", "oasi", "oasi", "2026-08-01T05:00:00Z", "oasi/e.fits", 50, "e" * 64, "downloaded", "verified"),
                    ("https://mmto/f", "mmto", "mmto-skycam", "2026-08-01T06:00:00Z", "mmto/f.fits", 60, "f" * 64, "failed", "failed"),
                    ("https://mmto/g", "mmto", "mmto-skycam", "2026-08-01T07:00:00Z", "mmto/g.fits", 70, "g" * 64, "downloaded", "verified"),
                )
                database.executemany(
                    "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?,?)", rows
                )

            results = root / "stars.sqlite"
            with sqlite3.connect(results) as database:
                database.execute(
                    """
                    CREATE TABLE runs (
                        source_sha256 TEXT,
                        solver_version TEXT,
                        exit_code INTEGER,
                        source_manifest_json TEXT
                    )
                    """
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    (
                        ("a" * 64, "0.11.0", 0, None),
                        ("b" * 64, "0.11.0", 1, None),
                        ("c" * 64, "0.10.0", 0, '{"version":"0.10.0"}'),
                        ("g" * 64, None, 1, '{"version":"0.11.0"}'),
                    ),
                )

            plan = build_processing_plan(archive, results)

            self.assertEqual(plan.verified_mmto_images, 5)
            self.assertEqual(plan.skipped_v11_receipts, 3)
            self.assertEqual(
                [item.source_sha256 for item in plan.pending],
                ["c" * 64, "d" * 64],
            )
            self.assertEqual(
                [item.local_path.as_posix() for item in plan.pending],
                ["mmto/c.fits", "mmto/d.fits"],
            )


class MmtoPhotometryPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.results = self.root / "results"
        self.results.mkdir()
        self.database = self.results / "stars.sqlite"
        create_results(self.database)
        self.output = self.results / "photometry-run"
        self.call_log = self.root / "calls.jsonl"

    def install_stage_launchers(self) -> None:
        stage_source = f"""#!/usr/bin/env python3
import json
from pathlib import Path
import sys
name = Path(sys.argv[0]).name
with Path({str(self.call_log)!r}).open('a', encoding='utf-8') as stream:
    stream.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
arguments = sys.argv[1:]
output = Path(arguments[arguments.index('--output') + 1])
output.mkdir(parents=True)
(output / 'complete.txt').write_text(name + '\\n', encoding='utf-8')
"""
        for name in (
            "plot_mmto_lightcurves.sh",
            "calibrate_mmto_extinction.sh",
            "plot_ALL_planets.sh",
        ):
            write_executable(self.repo / name, stage_source)

    def test_recorded_solver_failure_does_not_prevent_photometry_suite(self) -> None:
        images = [
            ("2026-08-01T01:00:00Z", "mmto/good.fits", "good image"),
            ("2026-08-01T02:00:00Z", "mmto/fail.fits", "failed image"),
        ]
        for _observed, relative, contents in images:
            path = self.archive / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        create_manifest(self.archive / "manifest.sqlite", images)
        go11_source = f"""#!/usr/bin/env python3
import hashlib
from pathlib import Path
import sqlite3
import sys
image = Path(sys.argv[1])
results = Path(sys.argv[sys.argv.index('--results-dir') + 1])
digest = hashlib.sha256(image.read_bytes()).hexdigest()
exit_code = 1 if image.name == 'fail.fits' else 0
with sqlite3.connect(results / 'stars.sqlite') as database:
    solver_version = None if exit_code else '0.11.0'
    database.execute(
        'INSERT INTO runs VALUES (?,?,?,?)',
        (digest, solver_version, exit_code, '{{"version":"0.11.0"}}'),
    )
with Path({str(self.call_log)!r}).open('a', encoding='utf-8') as stream:
    stream.write(__import__('json').dumps(['go11.sh', *sys.argv[1:]]) + '\\n')
raise SystemExit(exit_code)
"""
        write_executable(self.repo / "go11.sh", go11_source)
        self.install_stage_launchers()

        with patch.dict(os.environ, {}, clear=False):
            status = main(
                [
                    "--archive", str(self.archive),
                    "--results-dir", str(self.results),
                    "--output", str(self.output),
                    "--repo-root", str(self.repo),
                    "--lock-file", str(self.root / "pipeline.lock"),
                ]
            )

        self.assertEqual(status, 0)
        calls = [
            json.loads(line)
            for line in self.call_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [call[0] for call in calls],
            [
                "go11.sh",
                "go11.sh",
                "plot_mmto_lightcurves.sh",
                "calibrate_mmto_extinction.sh",
                "plot_ALL_planets.sh",
            ],
        )
        planet_call = calls[-1]
        self.assertIn("--nightly-calibration", planet_call)
        self.assertIn(str(self.output / "nightly-extinction"), planet_call)
        summary = json.loads(
            (self.output / "pipeline_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["processing"]["attempted"], 2)
        self.assertEqual(summary["processing"]["succeeded"], 1)
        self.assertEqual(summary["processing"]["solver_failed"], 1)
        self.assertEqual(summary["status"], "complete")

    def test_missing_solver_receipt_stops_before_photometry_suite(self) -> None:
        images = [("2026-08-01T01:00:00Z", "mmto/broken.fits", "broken")]
        image = self.archive / images[0][1]
        image.parent.mkdir(parents=True)
        image.write_text(images[0][2], encoding="utf-8")
        create_manifest(self.archive / "manifest.sqlite", images)
        write_executable(
            self.repo / "go11.sh",
            "#!/usr/bin/env bash\nexit 1\n",
        )
        self.install_stage_launchers()

        status = main(
            [
                "--archive", str(self.archive),
                "--results-dir", str(self.results),
                "--output", str(self.output),
                "--repo-root", str(self.repo),
                "--lock-file", str(self.root / "pipeline.lock"),
            ]
        )

        self.assertEqual(status, 2)
        self.assertFalse(self.call_log.exists())
        summary = json.loads(
            (self.output / "pipeline_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["status"], "operational_failed")
        self.assertIn("no v11 database receipt", summary["error"])
        self.assertFalse((self.output / "nightly-extinction").exists())

    def test_command_runner_closes_its_output_stream(self) -> None:
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", ResourceWarning)
            status = _run_command(
                ["/bin/true"], io.StringIO(), cwd=self.root
            )
            gc.collect()

        self.assertEqual(status, 0)
        self.assertEqual(
            [item for item in observed if item.category is ResourceWarning],
            [],
        )

    def test_dry_run_lists_pending_images_without_writing_or_running(self) -> None:
        images = [("2026-08-01T01:00:00Z", "mmto/new.fits", "new image")]
        image = self.archive / images[0][1]
        image.parent.mkdir(parents=True)
        image.write_text(images[0][2], encoding="utf-8")
        create_manifest(self.archive / "manifest.sqlite", images)
        output = io.StringIO()

        with patch("sys.stdout", output):
            status = main(
                [
                    "--archive", str(self.archive),
                    "--results-dir", str(self.results),
                    "--output", str(self.output),
                    "--repo-root", str(self.repo),
                    "--dry-run",
                ]
            )

        self.assertEqual(status, 0)
        self.assertIn("pending=1", output.getvalue())
        self.assertIn("DRY_RUN", output.getvalue())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.call_log.exists())


class MmtoPhotometryPipelineLauncherTests(unittest.TestCase):
    def test_real_launcher_help_works_from_another_directory(self) -> None:
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [str(root / "go_mmto_photometry.sh"), "--help"],
                cwd=temporary,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("--dry-run", completed.stdout)
        self.assertIn("--results-dir", completed.stdout)

    def test_launcher_is_portable_and_forwards_all_arguments(self) -> None:
        root = Path(__file__).resolve().parent
        launcher = root / "go_mmto_photometry.sh"
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            invocation = work / "uv.txt"
            fake_uv = bin_dir / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" > \"$FAKE_UV_LOG\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment["FAKE_UV_LOG"] = str(invocation)

            completed = subprocess.run(
                [
                    "bash", str(launcher),
                    "--archive", "/archive path",
                    "--dry-run",
                ],
                cwd=work,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(
                invocation.read_text(encoding="utf-8").strip(),
                f"run --project {root} --frozen python "
                f"{root / 'scripts' / 'run_mmto_photometry_pipeline.py'} "
                "--archive /archive path --dry-run",
            )


if __name__ == "__main__":
    unittest.main()
