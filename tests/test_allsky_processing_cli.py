from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import tempfile
import unittest
import uuid

from allsky_download.http import DownloadedFile
from allsky_download.manifest import Manifest
from allsky_download.model import Candidate
from allsky_download.processing import ProcessingQueue


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "run_allsky_processing.py"


class ProcessingCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = self.root / "archive"
        self.results = self.root / "results"

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--archive",
                str(self.archive),
                "--results-dir",
                str(self.results),
                "--worker-lock",
                str(self.root / "worker.lock"),
                *arguments,
            ],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def seed(self, *, state: str = "pending") -> tuple[int, str]:
        content = b"data"
        digest = hashlib.sha256(content).hexdigest()
        image = self.archive / "mmto/mmto-skycam/2026-09-18/image.fits.bz2"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(content)
        candidate = Candidate(
            "mmto",
            "mmto-skycam",
            datetime(2026, 9, 19, tzinfo=timezone.utc),
            "2026_09_19__00_00_00",
            "https://example.test/image.fits.bz2",
            image.name,
            len(content),
            {},
        )
        with Manifest(self.archive / "manifest.sqlite") as manifest:
            manifest.record_attempt(candidate)
            manifest.record_success(
                candidate,
                DownloadedFile(image, len(content), digest),
                self.archive,
                enqueue_processing=True,
            )
            job_id = manifest.connection.execute(
                "SELECT job_id FROM processing_jobs"
            ).fetchone()[0]
        if state != "pending":
            with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
                job = queue.claim_next()
                queue.finish(
                    job.job_id,
                    job.worker_token,
                    state=state,
                    solver_exit_code=1 if state == "solver_failed" else None,
                    failure_kind=(
                        "solver" if state == "solver_failed" else "operational"
                    ),
                    error="seeded failure",
                )
        return job_id, digest

    def add_receipt(self, digest: str, *, exit_code: int = 0) -> str:
        run_id = str(uuid.uuid4())
        analysis = self.results / "runs" / run_id / "analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.results / "stars.sqlite") as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  run_id TEXT PRIMARY KEY,
                  source_sha256 TEXT,
                  analysis_path TEXT NOT NULL,
                  exit_code INTEGER NOT NULL,
                  error TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    digest,
                    str(analysis),
                    exit_code,
                    None if exit_code == 0 else "RuntimeError: no solution",
                ),
            )
        return run_id

    def state(self, job_id: int) -> tuple[str, str | None]:
        with sqlite3.connect(self.archive / "manifest.sqlite") as connection:
            return connection.execute(
                "SELECT state, solver_run_id FROM processing_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()

    def test_status_is_read_only_and_reports_counts(self):
        self.seed()
        database = self.archive / "manifest.sqlite"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        completed = self.run_cli("status")
        after = hashlib.sha256(database.read_bytes()).hexdigest()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("pending=1", completed.stdout)
        self.assertRegex(completed.stdout, r"oldest_pending_age_seconds=\d+")
        self.assertEqual(after, before)

    def test_cleanup_defaults_to_dry_run(self):
        job_id, _ = self.seed(state="operational_failed")
        completed = self.run_cli("cleanup", "--job-id", str(job_id))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("DRY-RUN", completed.stdout)
        self.assertEqual(self.state(job_id)[0], "operational_failed")

    def test_cleanup_apply_never_requeues_solver_failure(self):
        job_id, _ = self.seed(state="solver_failed")
        completed = self.run_cli(
            "cleanup", "--apply", "--job-id", str(job_id)
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("solver_failed", completed.stderr)
        self.assertEqual(self.state(job_id)[0], "solver_failed")

    def test_cleanup_apply_requeues_selected_operational_failure(self):
        job_id, _ = self.seed(state="operational_failed")
        completed = self.run_cli(
            "cleanup", "--apply", "--job-id", str(job_id)
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("REQUEUED", completed.stdout)
        self.assertEqual(self.state(job_id)[0], "pending")

    def test_cleanup_reconciles_existing_receipt_instead_of_requeueing(self):
        job_id, digest = self.seed(state="operational_failed")
        run_id = self.add_receipt(digest)
        completed = self.run_cli(
            "cleanup", "--apply", "--job-id", str(job_id)
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("RECONCILED", completed.stdout)
        self.assertEqual(self.state(job_id), ("succeeded", run_id))

    def test_cleanup_refuses_ambiguous_receipts_without_mutation(self):
        job_id, digest = self.seed(state="operational_failed")
        first = self.add_receipt(digest)
        second = self.add_receipt(digest)
        completed = self.run_cli(
            "cleanup", "--apply", "--job-id", str(job_id)
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn(first, completed.stderr)
        self.assertIn(second, completed.stderr)
        self.assertEqual(self.state(job_id)[0], "operational_failed")

    def test_cleanup_refuses_symlinked_receipt_database(self):
        job_id, digest = self.seed(state="operational_failed")
        self.add_receipt(digest)
        database = self.results / "stars.sqlite"
        foreign = self.root / "foreign-stars.sqlite"
        database.rename(foreign)
        database.symlink_to(foreign)
        completed = self.run_cli(
            "cleanup", "--apply", "--job-id", str(job_id)
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("symlink", completed.stderr)
        self.assertEqual(self.state(job_id)[0], "operational_failed")

    def test_work_once_with_empty_queue_is_harmless(self):
        self.seed()
        with sqlite3.connect(self.archive / "manifest.sqlite") as connection:
            connection.execute("DELETE FROM processing_events")
            connection.execute("DELETE FROM processing_jobs")
        completed = self.run_cli("work", "--once")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("NO_WORK", completed.stdout)

    def test_work_once_uses_worker_lock_before_claiming(self):
        job_id, _ = self.seed()
        lock_path = self.root / "worker.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            completed = self.run_cli(
                "--repo-root", str(self.root / "missing-repo"), "work", "--once"
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("BUSY", completed.stdout)
        self.assertEqual(self.state(job_id)[0], "pending")

    def test_solver_retains_lock_and_live_log_after_worker_is_killed(self):
        job_id, _ = self.seed()
        repo = self.root / 'fake-repo'
        (repo / 'v10').mkdir(parents=True)
        (repo / 'v10/SOURCE_MANIFEST.json').write_text('{}\n')
        ready = self.root / 'solver.pid'
        launcher = repo / 'go10.sh'
        launcher.write_text(
            f'#!{sys.executable}\n'
            'import os, time\nfrom pathlib import Path\n'
            'print("solver-started", flush=True)\n'
            f'Path({str(ready)!r}).write_text(str(os.getpid()))\n'
            'time.sleep(15)\n')
        launcher.chmod(0o755)
        worker = subprocess.Popen([
            sys.executable, str(SCRIPT), '--archive', str(self.archive),
            '--results-dir', str(self.results), '--repo-root', str(repo),
            '--worker-lock', str(self.root / 'worker.lock'), 'work', '--once'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and worker.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists(), 'synthetic solver did not start')
            child_pid = int(ready.read_text())
            worker.kill()
            worker.wait(timeout=5)
            os.kill(child_pid, 0)  # The solver, unlike its wrapper, remains alive.
            with self.subTest('lock lifetime'):
                completed = self.run_cli('work', '--once')
                self.assertIn('BUSY', completed.stdout)
                cleanup = self.run_cli('cleanup', '--apply', '--job-id', str(job_id), '--stale-after', '0')
                self.assertEqual(cleanup.returncode, 3)
                self.assertEqual(self.state(job_id)[0], 'running')
            with self.subTest('streamed log'):
                log = self.archive / f'processing-logs/job-{job_id}-attempt-1.log'
                self.assertIn('solver-started', log.read_text())
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=5)
            if child_pid is not None:
                try:
                    os.kill(child_pid, 15)
                except ProcessLookupError:
                    pass

    def test_cleanup_apply_requires_an_explicit_selector(self):
        self.seed(state="operational_failed")
        completed = self.run_cli("cleanup", "--apply")
        self.assertEqual(completed.returncode, 3)
        self.assertIn("selector", completed.stderr)

    def test_cleanup_apply_refuses_while_worker_lock_is_held(self):
        job_id, _ = self.seed(state="operational_failed")
        lock_path = self.root / "worker.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            completed = self.run_cli(
                "cleanup", "--apply", "--job-id", str(job_id)
            )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("worker lock", completed.stderr)
        self.assertEqual(self.state(job_id)[0], "operational_failed")

    def test_missing_manifest_is_a_concise_operational_error(self):
        completed = self.run_cli("status")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("acquisition manifest is missing", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
