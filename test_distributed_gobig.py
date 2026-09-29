import sqlite3
import tempfile
import unittest
from pathlib import Path

import run_distributed_gobig as distributed


class DistributedGoBigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "raw").mkdir()
        for name in ("one.fits.bz2", "two.fits.bz2", "three.fits.bz2"):
            (self.root / "raw" / name).write_bytes(name.encode())

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self, lines):
        path = self.root / "goBIG"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_load_jobs_accepts_only_independent_go11_image_commands(self):
        manifest = self.write_manifest([
            "./go11.sh ./raw/one.fits.bz2",
            "",
            "./go11.sh './raw/two.fits.bz2'",
        ])

        jobs = distributed.load_jobs(manifest, self.root)

        self.assertEqual([(job.line_no, job.relative_image.as_posix()) for job in jobs], [
            (1, "raw/one.fits.bz2"),
            (3, "raw/two.fits.bz2"),
        ])

    def test_load_jobs_rejects_options_duplicates_and_paths_outside_repo(self):
        cases = [
            ["./go11.sh ./raw/one.fits.bz2 --blind-planets"],
            ["./go11.sh ./raw/one.fits.bz2", "./go11.sh ./raw/one.fits.bz2"],
            ["./go11.sh ../outside.fits.bz2"],
        ]
        for number, lines in enumerate(cases):
            with self.subTest(lines=lines):
                manifest = self.root / f"goBIG-{number}"
                manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    distributed.load_jobs(manifest, self.root)

    def test_initialize_state_partitions_remaining_lines_and_is_idempotent(self):
        manifest = self.write_manifest([
            "./go11.sh ./raw/one.fits.bz2",
            "./go11.sh ./raw/two.fits.bz2",
            "./go11.sh ./raw/three.fits.bz2",
        ])
        jobs = distributed.load_jobs(manifest, self.root)
        database = self.root / "state.sqlite"

        distributed.initialize_state(database, jobs, start_line=2)
        distributed.initialize_state(database, jobs, start_line=2)

        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT line_no, relative_image, assigned, status FROM jobs ORDER BY line_no"
            ).fetchall()
        self.assertEqual(rows, [
            (2, "raw/two.fits.bz2", "local", "pending"),
            (3, "raw/three.fits.bz2", "remote", "pending"),
        ])

    def test_initialize_state_refuses_a_different_manifest_or_start_line(self):
        manifest = self.write_manifest([
            "./go11.sh ./raw/one.fits.bz2",
            "./go11.sh ./raw/two.fits.bz2",
        ])
        jobs = distributed.load_jobs(manifest, self.root)
        database = self.root / "state.sqlite"
        distributed.initialize_state(database, jobs, start_line=1)

        with self.assertRaises(ValueError):
            distributed.initialize_state(database, jobs, start_line=2)

    def test_init_command_succeeds_while_jobs_are_pending(self):
        manifest = self.write_manifest(["./go11.sh ./raw/one.fits.bz2"])
        database = self.root / "state.sqlite"

        result = distributed.main([
            "--state", str(database), "--repo", str(self.root), "init",
            "--manifest", str(manifest), "--start-line", "1",
        ])

        self.assertEqual(result, 0)

    def test_claim_and_finish_are_atomic_and_assignment_specific(self):
        manifest = self.write_manifest([
            "./go11.sh ./raw/one.fits.bz2",
            "./go11.sh ./raw/two.fits.bz2",
            "./go11.sh ./raw/three.fits.bz2",
        ])
        jobs = distributed.load_jobs(manifest, self.root)
        database = self.root / "state.sqlite"
        distributed.initialize_state(database, jobs, start_line=1)

        local = distributed.claim_job(database, "local")
        remote = distributed.claim_job(database, "remote")
        self.assertEqual(local.line_no, 1)
        self.assertEqual(remote.line_no, 2)
        self.assertEqual(distributed.claim_job(database, "remote"), None)

        distributed.finish_job(database, local.line_no, "succeeded", 0, "/runs/one")
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT status, exit_code, run_dir, attempts FROM jobs WHERE line_no=1"
            ).fetchone()
        self.assertEqual(row, ("succeeded", 0, "/runs/one", 1))

    def test_extract_run_directory_must_be_below_expected_runs_root(self):
        expected = Path("/srv/results/runs")
        output = "noise\nRun folder: /srv/results/runs/example-v0.11.0-ABC123\n"
        self.assertEqual(
            distributed.extract_run_directory(output, expected),
            expected / "example-v0.11.0-ABC123",
        )
        with self.assertRaises(ValueError):
            distributed.extract_run_directory("Run folder: /tmp/other\n", expected)

    def test_worker_records_an_unexpected_operational_failure_and_continues(self):
        manifest = self.write_manifest([
            "./go11.sh ./raw/one.fits.bz2",
            "./go11.sh ./raw/two.fits.bz2",
            "./go11.sh ./raw/three.fits.bz2",
        ])
        database = self.root / "state.sqlite"
        distributed.initialize_state(database, distributed.load_jobs(manifest, self.root), 1)
        visited = []

        def action(job):
            visited.append(job.line_no)
            if job.line_no == 1:
                raise OSError("lost executable")
            distributed.finish_job(database, job.line_no, "succeeded", 0, "/run")

        distributed._worker_loop("local", database, action)

        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT line_no, status, error FROM jobs WHERE assigned='local' ORDER BY line_no"
            ).fetchall()
        self.assertEqual(visited, [1, 3])
        self.assertEqual(rows, [
            (1, "operational_failed", "lost executable"),
            (3, "succeeded", None),
        ])


if __name__ == "__main__":
    unittest.main()
