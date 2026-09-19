from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import uuid

from allsky_download.http import DownloadedFile
from allsky_download.manifest import Manifest
from allsky_download.model import Candidate
from allsky_download.processing import (
    ClaimLostError,
    ProcessingQueue,
    run_one,
)


def make_candidate(
    url: str = "https://example.test/one.fits.bz2",
    filename: str = "one.fits.bz2",
) -> Candidate:
    return Candidate(
        "mmto",
        "mmto-skycam",
        datetime(2026, 9, 19, tzinfo=timezone.utc),
        "2026_09_19__00_00_00",
        url,
        filename,
        4,
        {},
    )


class ProcessingEnqueueTests(unittest.TestCase):
    def _download(
        self, root: Path, filename: str, content: bytes = b"data"
    ) -> DownloadedFile:
        path = root / "mmto" / "mmto-skycam" / "2026-09-18" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return DownloadedFile(path, len(content), hashlib.sha256(content).hexdigest())

    def test_opted_in_success_atomically_enqueues_one_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = make_candidate()
            downloaded = self._download(root, candidate.filename)
            with Manifest(root / "manifest.sqlite") as manifest:
                manifest.record_attempt(candidate)
                manifest.record_success(
                    candidate, downloaded, root, enqueue_processing=True
                )
                job = manifest.connection.execute(
                    "SELECT remote_url, source_sha256, solver_target, state, "
                    "attempt_count FROM processing_jobs"
                ).fetchone()
                event = manifest.connection.execute(
                    "SELECT previous_state, new_state, reason "
                    "FROM processing_events"
                ).fetchone()
            self.assertEqual(
                job,
                (
                    candidate.url,
                    downloaded.sha256,
                    "go10",
                    "pending",
                    0,
                ),
            )
            self.assertEqual(event, (None, "pending", "new verified download"))

    def test_default_success_does_not_enqueue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = make_candidate()
            downloaded = self._download(root, candidate.filename)
            with Manifest(root / "manifest.sqlite") as manifest:
                manifest.record_attempt(candidate)
                manifest.record_success(candidate, downloaded, root)
                count = manifest.connection.execute(
                    "SELECT count(*) FROM processing_jobs"
                ).fetchone()[0]
            self.assertEqual(count, 0)

    def test_duplicate_sha256_is_one_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = make_candidate()
            second = make_candidate(
                "https://example.test/two.fits.bz2", "two.fits.bz2"
            )
            with Manifest(root / "manifest.sqlite") as manifest:
                for candidate in (first, second):
                    downloaded = self._download(root, candidate.filename)
                    manifest.record_attempt(candidate)
                    manifest.record_success(
                        candidate, downloaded, root, enqueue_processing=True
                    )
                jobs = manifest.connection.execute(
                    "SELECT remote_url, source_sha256 FROM processing_jobs"
                ).fetchall()
                events = manifest.connection.execute(
                    "SELECT new_state FROM processing_events"
                ).fetchall()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0][0], first.url)
            self.assertEqual(events, [("pending",)])

    def test_download_and_job_roll_back_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = make_candidate()
            downloaded = self._download(root, candidate.filename)
            with Manifest(root / "manifest.sqlite") as manifest:
                manifest.record_attempt(candidate)
                manifest.connection.execute(
                    "CREATE TRIGGER refuse_processing BEFORE INSERT ON processing_jobs "
                    "BEGIN SELECT RAISE(ABORT, 'refused'); END"
                )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "refused"):
                    manifest.record_success(
                        candidate, downloaded, root, enqueue_processing=True
                    )
                row = manifest.connection.execute(
                    "SELECT download_status, validation_status FROM downloads "
                    "WHERE remote_url=?",
                    (candidate.url,),
                ).fetchone()
            self.assertEqual(row, ("attempting", "pending"))


class ProcessingQueueTests(unittest.TestCase):
    def _seed(self, root: Path, *, enqueue: tuple[bool, ...]) -> list[int | None]:
        job_ids = []
        with Manifest(root / "manifest.sqlite") as manifest:
            for index, opted_in in enumerate(enqueue, 1):
                filename = f"image-{index}.fits.bz2"
                content = f"raw{index}".encode("ascii")
                candidate = make_candidate(
                    f"https://example.test/{filename}", filename
                )
                downloaded = ProcessingEnqueueTests()._download(
                    root, filename, content
                )
                manifest.record_attempt(candidate)
                manifest.record_success(
                    candidate,
                    downloaded,
                    root,
                    enqueue_processing=opted_in,
                )
                row = manifest.connection.execute(
                    "SELECT job_id FROM processing_jobs WHERE remote_url=?",
                    (candidate.url,),
                ).fetchone()
                job_ids.append(None if row is None else row[0])
        return job_ids

    def test_claim_is_fifo_and_token_controls_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_ids = self._seed(root, enqueue=(True, True))
            with ProcessingQueue(root / "manifest.sqlite") as queue:
                first = queue.claim_next()
                self.assertIsNotNone(first)
                self.assertEqual(first.job_id, job_ids[0])
                with self.assertRaises(ClaimLostError):
                    queue.finish(
                        first.job_id,
                        "foreign-token",
                        state="succeeded",
                        solver_exit_code=0,
                    )
                queue.finish(
                    first.job_id,
                    first.worker_token,
                    state="succeeded",
                    solver_exit_code=0,
                    solver_run_id="run-1",
                    analysis_path="/analysis/one",
                )
                row = queue.connection.execute(
                    "SELECT state, solver_run_id, analysis_path FROM processing_jobs "
                    "WHERE job_id=?",
                    (first.job_id,),
                ).fetchone()
            self.assertEqual(tuple(row), ("succeeded", "run-1", "/analysis/one"))

    def test_terminal_failure_does_not_block_next_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_ids = self._seed(root, enqueue=(True, True))
            with ProcessingQueue(root / "manifest.sqlite") as queue:
                first = queue.claim_next()
                queue.finish(
                    first.job_id,
                    first.worker_token,
                    state="solver_failed",
                    solver_exit_code=1,
                    failure_kind="solver",
                    error="no solution",
                )
                second = queue.claim_next()
            self.assertEqual(second.job_id, job_ids[1])

    def test_running_job_does_not_block_later_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_ids = self._seed(root, enqueue=(True, True))
            with ProcessingQueue(root / "manifest.sqlite") as queue:
                first = queue.claim_next()
                second = queue.claim_next()
            self.assertEqual(first.job_id, job_ids[0])
            self.assertEqual(second.job_id, job_ids[1])

    def test_status_reports_counts_oldest_pending_and_stale_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root, enqueue=(True, True))
            with ProcessingQueue(root / "manifest.sqlite") as queue:
                running = queue.claim_next()
                queue.connection.execute(
                    "UPDATE processing_jobs SET started_utc='2000-01-01T00:00:00Z' "
                    "WHERE job_id=?",
                    (running.job_id,),
                )
                queue.connection.commit()
                status = queue.status(stale_after_seconds=60)
            self.assertEqual(status.counts["running"], 1)
            self.assertEqual(status.counts["pending"], 1)
            self.assertEqual(len(status.stale_running), 1)
            self.assertIsNotNone(status.oldest_pending_utc)

    def test_cleanup_requeues_only_selected_operational_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_ids = self._seed(root, enqueue=(True, True))
            with ProcessingQueue(root / "manifest.sqlite") as queue:
                operational = queue.claim_next()
                queue.finish(
                    operational.job_id,
                    operational.worker_token,
                    state="operational_failed",
                    failure_kind="operational",
                    error="storage offline",
                )
                scientific = queue.claim_next()
                queue.finish(
                    scientific.job_id,
                    scientific.worker_token,
                    state="solver_failed",
                    solver_exit_code=1,
                    failure_kind="solver",
                    error="no solution",
                )
                candidates = queue.audit_cleanup(job_ids=(job_ids[0],), limit=10)
                self.assertEqual([item.kind for item in candidates], ["operational_failed"])
                queue.apply_cleanup(candidates)
                states = dict(
                    queue.connection.execute(
                        "SELECT job_id, state FROM processing_jobs"
                    ).fetchall()
                )
            self.assertEqual(states[job_ids[0]], "pending")
            self.assertEqual(states[job_ids[1]], "solver_failed")

    def test_cleanup_can_enqueue_one_explicit_overlooked_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root, enqueue=(False,))
            with ProcessingQueue(root / "manifest.sqlite") as queue:
                candidates = queue.audit_cleanup(source="mmto", limit=1)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].kind, "missing_job")
                queue.apply_cleanup(candidates)
                job = queue.connection.execute(
                    "SELECT state, remote_url FROM processing_jobs"
                ).fetchone()
            self.assertEqual(tuple(job), ("pending", "https://example.test/image-1.fits.bz2"))


def create_solver_receipt(
    results_root: Path,
    run_id: str,
    source_sha256: str,
    exit_code: int,
) -> Path:
    analysis = results_root / "runs" / run_id / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    database = results_root / "stars.sqlite"
    with sqlite3.connect(database) as connection:
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
                source_sha256,
                str(analysis),
                exit_code,
                None if exit_code == 0 else "RuntimeError: no solution",
            ),
        )
    return analysis


class ProcessingWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.archive = self.base / "archive"
        self.results = self.base / "results"
        self.repo = self.base / "repo"
        (self.repo / "v10").mkdir(parents=True)
        (self.repo / "go10.sh").write_bytes(b"#!/bin/sh\n")
        (self.repo / "v10" / "SOURCE_MANIFEST.json").write_bytes(b"{}\n")

    def tearDown(self):
        self.temporary.cleanup()

    def seed(
        self,
        *,
        filename: str = "worker.fits.bz2",
        content: bytes = b"data",
        suffix: str = "worker",
    ) -> tuple[int, Path, str]:
        candidate = make_candidate(
            f"https://example.test/{suffix}.fits.bz2", filename
        )
        path = self.archive / "mmto" / "mmto-skycam" / "2026-09-18" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with Manifest(self.archive / "manifest.sqlite") as manifest:
            manifest.record_attempt(candidate)
            manifest.record_success(
                candidate,
                DownloadedFile(path, len(content), digest),
                self.archive,
                enqueue_processing=True,
            )
            job_id = manifest.connection.execute(
                "SELECT job_id FROM processing_jobs WHERE remote_url=?",
                (candidate.url,),
            ).fetchone()[0]
        return job_id, path, digest

    @staticmethod
    def output_for(results: Path, run_id: str) -> str:
        return f"Database: {results / 'stars.sqlite'} (run {run_id})\n"

    def test_worker_invokes_exactly_one_image_without_shell(self):
        job_id, image, digest = self.seed()
        run_id = str(uuid.uuid4())
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(argv=argv, kwargs=kwargs)
            create_solver_receipt(self.results, run_id, digest, 0)
            kwargs['stdout'].write(self.output_for(self.results, run_id))
            return subprocess.CompletedProcess(argv, 0)

        with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
            result = run_one(
                queue,
                self.archive,
                self.results,
                self.repo,
                run_process=fake_run,
            )
            stored = queue.get_job(job_id)
        self.assertEqual(
            seen["argv"],
            [
                str(self.repo / "go10.sh"),
                str(image.resolve()),
                "--results-dir",
                str(self.results.resolve()),
            ],
        )
        self.assertNotIn("shell", seen["kwargs"])
        self.assertEqual(seen["kwargs"]["cwd"], self.repo.resolve())
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(stored.solver_run_id, run_id)
        self.assertEqual(stored.solver_exit_code, 0)
        self.assertEqual(
            stored.launcher_sha256,
            hashlib.sha256((self.repo / "go10.sh").read_bytes()).hexdigest(),
        )
        self.assertTrue((self.archive / stored.processing_log).is_file())

    def test_zero_exit_without_matching_receipt_is_operational_failure(self):
        job_id, _, _ = self.seed()
        missing_id = str(uuid.uuid4())

        def fake_run(argv, **kwargs):
            kwargs['stdout'].write(self.output_for(self.results, missing_id))
            return subprocess.CompletedProcess(argv, 0)

        with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
            result = run_one(
                queue, self.archive, self.results, self.repo, run_process=fake_run
            )
            stored = queue.get_job(job_id)
        self.assertEqual(result.state, "operational_failed")
        self.assertEqual(stored.failure_kind, "operational")
        self.assertEqual(stored.solver_exit_code, 0)
        self.assertIn("receipt", stored.error)

    def test_worker_rejects_symlinked_receipt_database(self):
        job_id, _, digest = self.seed()
        run_id = str(uuid.uuid4())

        def fake_run(argv, **kwargs):
            analysis = self.results / "runs" / run_id / "analysis"
            analysis.mkdir(parents=True, exist_ok=True)
            foreign = self.base / "foreign-stars.sqlite"
            with sqlite3.connect(foreign) as connection:
                connection.execute(
                    """
                    CREATE TABLE runs (
                      run_id TEXT PRIMARY KEY, source_sha256 TEXT,
                      analysis_path TEXT NOT NULL, exit_code INTEGER NOT NULL,
                      error TEXT
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, 0, NULL)",
                    (run_id, digest, str(analysis)),
                )
            (self.results / "stars.sqlite").symlink_to(foreign)
            kwargs['stdout'].write(self.output_for(self.results, run_id))
            return subprocess.CompletedProcess(argv, 0)

        with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
            result = run_one(
                queue, self.archive, self.results, self.repo, run_process=fake_run
            )
            stored = queue.get_job(job_id)
        self.assertEqual(result.state, "operational_failed")
        self.assertEqual(stored.failure_kind, "operational")
        self.assertIn("symlink", stored.error)

    def test_nonzero_matching_receipt_is_solver_failure_and_next_job_runs(self):
        first_id, _, digest = self.seed(suffix="first")
        second_id, _, _ = self.seed(filename="second.fits.bz2", content=b"more", suffix="second")
        run_id = str(uuid.uuid4())

        def fake_run(argv, **kwargs):
            create_solver_receipt(self.results, run_id, digest, 1)
            kwargs['stdout'].write(self.output_for(self.results, run_id))
            return subprocess.CompletedProcess(argv, 1)

        with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
            result = run_one(
                queue, self.archive, self.results, self.repo, run_process=fake_run
            )
            first = queue.get_job(first_id)
            next_job = queue.claim_next()
        self.assertEqual(result.state, "solver_failed")
        self.assertEqual(first.failure_kind, "solver")
        self.assertEqual(first.solver_run_id, run_id)
        self.assertEqual(next_job.job_id, second_id)

    def test_invalid_inputs_fail_operationally_without_starting_solver(self):
        cases = ("missing", "size", "checksum", "traversal", "leaf_symlink", "parent_symlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                self.tearDown()
                self.temporary = tempfile.TemporaryDirectory(dir=tmp)
                self.base = Path(self.temporary.name)
                self.archive = self.base / "archive"
                self.results = self.base / "results"
                self.repo = self.base / "repo"
                (self.repo / "v10").mkdir(parents=True)
                (self.repo / "go10.sh").write_bytes(b"#!/bin/sh\n")
                (self.repo / "v10" / "SOURCE_MANIFEST.json").write_bytes(b"{}\n")
                job_id, image, _ = self.seed()
                if case == "missing":
                    image.unlink()
                elif case == "size":
                    image.write_bytes(b"longer")
                elif case == "checksum":
                    image.write_bytes(b"date")
                elif case == "traversal":
                    with sqlite3.connect(self.archive / "manifest.sqlite") as connection:
                        connection.execute(
                            "UPDATE downloads SET local_path='../outside.fits'"
                        )
                elif case == "leaf_symlink":
                    target = image.with_name("target.fits.bz2")
                    image.rename(target)
                    image.symlink_to(target.name)
                else:
                    camera_dir = image.parent
                    real_dir = camera_dir.with_name("real-camera")
                    camera_dir.rename(real_dir)
                    camera_dir.symlink_to(real_dir.name, target_is_directory=True)
                called = []

                def forbidden_run(argv, **kwargs):
                    called.append(argv)
                    raise AssertionError("invalid input reached solver")

                with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
                    result = run_one(
                        queue,
                        self.archive,
                        self.results,
                        self.repo,
                        run_process=forbidden_run,
                    )
                    stored = queue.get_job(job_id)
                self.assertEqual(result.state, "operational_failed")
                self.assertEqual(stored.failure_kind, "operational")
                self.assertEqual(called, [])

    def test_acquisition_can_commit_while_solver_is_running(self):
        self.seed(suffix="first")
        started = threading.Event()
        release = threading.Event()
        finished = []

        def blocking_run(argv, **kwargs):
            started.set()
            self.assertTrue(release.wait(5))
            digest = hashlib.sha256(b"data").hexdigest()
            run_id = str(uuid.uuid4())
            create_solver_receipt(self.results, run_id, digest, 0)
            kwargs['stdout'].write(self.output_for(self.results, run_id))
            return subprocess.CompletedProcess(argv, 0)

        def worker():
            with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
                finished.append(
                    run_one(
                        queue,
                        self.archive,
                        self.results,
                        self.repo,
                        run_process=blocking_run,
                    )
                )

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(started.wait(5))
        with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
            running = queue.status().running[0]
        self.assertTrue((self.archive / running.processing_log).is_file())
        second_id, _, _ = self.seed(
            filename="second.fits.bz2", content=b"more", suffix="second"
        )
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(finished[0].state, "succeeded")
        with ProcessingQueue(self.archive / "manifest.sqlite") as queue:
            self.assertEqual(queue.get_job(second_id).state, "pending")


if __name__ == "__main__":
    unittest.main()
