# MMTO Automatic Processing Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically process each newly downloaded nighttime MMTO image exactly once through frozen `go10`, while retaining a durable FIFO queue and an explicit, non-automatic cleanup path.

**Architecture:** Extend the acquisition manifest with transactional processing-job and event tables. A separate root CLI claims at most one job, validates the immutable input, invokes frozen `go10.sh` without a shell, verifies the resulting SQLite receipt, and records a terminal state; a separate cron lock serializes workers without blocking acquisition.

**Tech Stack:** Python 3.12 standard library (`argparse`, `dataclasses`, `hashlib`, `sqlite3`, `subprocess`, `uuid`), existing `unittest` suite, SQLite WAL transactions, shell `flock`, frozen v10 launcher boundary.

**Spec:** `docs/superpowers/specs/2026-09-19-mmto-processing-queue-design.md`

## Global Constraints

- Do not modify `go10.sh`, any file below `v10/`, `go11.sh`, or any file below `v11/`.
- Queue metadata must never seed, constrain, or select a blind scientific solution.
- Enqueue only genuinely new, verified MMTO cron downloads; deployment must not flood the queue with existing or `REUSE` images.
- Never automatically retry a failed or interrupted job and never automatically delete images, results, logs, queue rows, or events.
- Use one worker, FIFO claims, short SQLite transactions, and a worker token for terminal ownership.
- Automated runs use `results/mmto-automatic/` and record the exact `go10.sh` and `v10/SOURCE_MANIFEST.json` hashes.
- Preserve unrelated working-tree changes. Do not commit from this shared dirty worktree.

## Review Focus

- A byte-identical image under a second URL must not produce a second solver run; Task 1 pins unique SHA handling.
- A symlink in any input path component must be refused even when its resolved target remains below the archive root; Task 3 pins component-wise rejection.
- A zero launcher exit without a matching run UUID/database row must be operational failure, not success; Task 3 pins receipt verification.
- A nonzero launcher exit with a matching database row must be a terminal solver failure and must not block the next pending job; Tasks 2 and 3 pin both behaviors.
- A cleanup sweep must be harmless by default and must not requeue scientific solver failures; Task 4 pins dry-run and state-selection behavior.

---

### Task 1: Atomic queue schema and acquisition enqueue

**Files:**
- Create: `allsky_download/processing.py`
- Modify: `allsky_download/manifest.py`
- Modify: `allsky_download/cli.py`
- Modify: `allsky_download/cron.py`
- Test: `tests/test_allsky_processing.py`
- Test: `tests/test_allsky_manifest.py`
- Test: `tests/test_allsky_cron.py`

**Interfaces:**
- Consumes: existing `Manifest.record_success(candidate, downloaded, output_root)` and downloader CLI argument construction.
- Produces: `ensure_processing_schema(connection) -> None`, `enqueue_job(connection, remote_url, source_sha256, solver_target='go10') -> int | None`, and `Manifest.record_success(..., enqueue_processing: bool = False) -> None`.

- [ ] **Step 1: Write failing schema and atomic-enqueue tests**

```python
def test_opted_in_success_atomically_enqueues_one_job(self):
    manifest.record_attempt(candidate)
    manifest.record_success(candidate, downloaded, root, enqueue_processing=True)
    job = manifest.connection.execute(
        "SELECT remote_url, source_sha256, solver_target, state, attempt_count "
        "FROM processing_jobs"
    ).fetchone()
    self.assertEqual(job, (candidate.url, downloaded.sha256, "go10", "pending", 0))
    self.assertEqual(
        manifest.connection.execute(
            "SELECT previous_state, new_state, reason FROM processing_events"
        ).fetchone(),
        (None, "pending", "new verified download"),
    )

def test_default_success_and_reuse_do_not_enqueue(self):
    manifest.record_success(candidate, downloaded, root)
    self.assertEqual(manifest.connection.execute(
        "SELECT count(*) FROM processing_jobs").fetchone()[0], 0)

def test_duplicate_sha_is_one_job(self):
    # Record two verified URLs with the same bytes and opt both in.
    self.assertEqual(manifest.connection.execute(
        "SELECT count(*) FROM processing_jobs").fetchone()[0], 1)
```

- [ ] **Step 2: Run the focused tests and confirm the missing schema/API failures**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing tests.test_allsky_manifest`

Expected: FAIL because `processing_jobs`, `processing_events`, and `enqueue_processing` do not yet exist.

- [ ] **Step 3: Add constrained tables and idempotent enqueue helper**

```python
PROCESSING_STATES = (
    "pending", "running", "succeeded", "solver_failed",
    "operational_failed", "interrupted",
)

def ensure_processing_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS processing_jobs (
          job_id INTEGER PRIMARY KEY,
          remote_url TEXT NOT NULL UNIQUE REFERENCES downloads(remote_url),
          source_sha256 TEXT NOT NULL UNIQUE,
          solver_target TEXT NOT NULL CHECK (solver_target = 'go10'),
          state TEXT NOT NULL CHECK (state IN
            ('pending','running','succeeded','solver_failed','operational_failed','interrupted')),
          enqueued_utc TEXT NOT NULL, started_utc TEXT, finished_utc TEXT,
          attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
          worker_token TEXT, solver_run_id TEXT, analysis_path TEXT,
          solver_exit_code INTEGER, failure_kind TEXT,
          error TEXT, processing_log TEXT,
          launcher_sha256 TEXT, source_manifest_sha256 TEXT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS processing_events (
          event_id INTEGER PRIMARY KEY,
          job_id INTEGER NOT NULL REFERENCES processing_jobs(job_id),
          event_utc TEXT NOT NULL, previous_state TEXT, new_state TEXT NOT NULL,
          worker_token TEXT, reason TEXT NOT NULL
        )
    """)
```

Insert the job and initial event only when `INSERT OR IGNORE` creates a row, using the caller's existing `with self.connection:` transaction.

- [ ] **Step 4: Thread the opt-in only through recurring MMTO acquisition**

Add an internal downloader flag `--enqueue-processing`, pass it in `cron_download_arguments("mmto", ...)`, and call:

```python
manifest.record_success(
    candidate, downloaded, args.output,
    enqueue_processing=args.enqueue_processing,
)
```

Reject `--enqueue-processing` for non-MMTO sources so a future caller cannot accidentally queue an unconfigured telescope.

- [ ] **Step 5: Run focused acquisition tests**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_manifest tests.test_allsky_cron tests.test_allsky_cli tests.test_allsky_processing`

Expected: PASS, including one pending job for a new opted-in success, zero jobs for default/manual success and reuse, and one row for duplicate content.

### Task 2: FIFO claims, terminal ownership, status, and cleanup transitions

**Files:**
- Modify: `allsky_download/processing.py`
- Test: `tests/test_allsky_processing.py`

**Interfaces:**
- Consumes: Task 1 processing tables.
- Produces: `ProcessingQueue`, `ProcessingJob`, `QueueStatus`, `CleanupCandidate`; methods `claim_next()`, `finish()`, `status()`, `audit_cleanup()`, and `apply_cleanup()`.

- [ ] **Step 1: Write failing transition tests**

```python
def test_claim_is_fifo_and_token_controls_finish(self):
    first = queue.claim_next()
    self.assertEqual(first.job_id, first_job_id)
    with self.assertRaises(ClaimLostError):
        queue.finish(first.job_id, "foreign", state="succeeded", solver_exit_code=0)
    queue.finish(first.job_id, first.worker_token, state="succeeded",
                 solver_exit_code=0, solver_run_id="run-1", analysis_path="/analysis")

def test_terminal_failure_does_not_block_next_pending(self):
    first = queue.claim_next()
    queue.finish(first.job_id, first.worker_token, state="solver_failed",
                 solver_exit_code=1, failure_kind="solver", error="no solution")
    self.assertEqual(queue.claim_next().job_id, second_job_id)

def test_stale_running_row_does_not_block_later_pending(self):
    first = queue.claim_next()
    self.assertEqual(queue.claim_next().job_id, second_job_id)
```

- [ ] **Step 2: Run transition tests and confirm missing-interface failures**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing.ProcessingQueueTests`

Expected: FAIL because queue dataclasses and transition methods are absent.

- [ ] **Step 3: Implement short transactional claims and token-guarded completion**

```python
def claim_next(self) -> ProcessingJob | None:
    token = str(uuid.uuid4())
    with self.connection:
        self.connection.execute("BEGIN IMMEDIATE")
        row = self.connection.execute(
            "SELECT job_id FROM processing_jobs WHERE state='pending' "
            "ORDER BY enqueued_utc, job_id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        changed = self.connection.execute(
            "UPDATE processing_jobs SET state='running', started_utc=?, finished_utc=NULL, "
            "attempt_count=attempt_count+1, worker_token=? "
            "WHERE job_id=? AND state='pending'",
            (utc_now(), token, row[0]),
        ).rowcount
        if changed != 1:
            raise ClaimLostError("pending claim changed concurrently")
        self._event(row[0], "pending", "running", token, "worker claim")
    return self.get_job(row[0])
```

`finish()` must update only `WHERE job_id=? AND state='running' AND worker_token=?`, append the event in the same transaction, and raise `ClaimLostError` when no row changed.

- [ ] **Step 4: Implement read-only status and explicit cleanup state selection**

`status()` returns counts by state, active jobs with ages, pending age, and recent rows. `audit_cleanup()` reports stale running jobs, operational failures, and verified downloads without jobs under explicit filters. `apply_cleanup()` accepts explicit job IDs/remote URLs plus a limit, never changes `solver_failed`, and appends `running -> interrupted -> pending` or `operational_failed -> pending` events.

- [ ] **Step 5: Run transition/status/cleanup tests**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing`

Expected: PASS; no transition silently changes a terminal solver failure, and later pending jobs remain claimable.

### Task 3: Validating worker and frozen-launcher receipt verification

**Files:**
- Modify: `allsky_download/processing.py`
- Test: `tests/test_allsky_processing.py`

**Interfaces:**
- Consumes: `ProcessingQueue.claim_next()` and `finish()` from Task 2.
- Produces: `run_one(queue, acquisition_root, results_root, repo_root, run_process=subprocess.run) -> WorkResult` and `reconcile_receipt(results_database, run_id, expected_sha256) -> SolverReceipt`.

- [ ] **Step 1: Write failing worker tests using a fake launcher boundary**

```python
def test_worker_invokes_exactly_one_image_without_shell(self):
    seen = {}
    def fake_run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        create_solver_receipt(results_root / "stars.sqlite", "run-1", digest, 0)
        return subprocess.CompletedProcess(argv, 0,
            stdout=f"Database: {results_root/'stars.sqlite'} (run run-1)\n")
    result = run_one(queue, archive, results_root, repo, run_process=fake_run)
    self.assertEqual(seen["argv"], [str(repo/"go10.sh"), str(image.resolve()),
                                    "--results-dir", str(results_root.resolve())])
    self.assertNotIn("shell", seen["kwargs"])
    self.assertEqual(result.state, "succeeded")

def test_zero_exit_without_matching_receipt_is_operational_failure(self):
    result = run_one(queue, archive, results_root, repo,
                     run_process=fake_zero_without_receipt)
    self.assertEqual(result.state, "operational_failed")

def test_nonzero_with_matching_failed_receipt_is_solver_failure(self):
    result = run_one(queue, archive, results_root, repo,
                     run_process=fake_failed_with_receipt)
    self.assertEqual(result.state, "solver_failed")
    self.assertEqual(queue.claim_next().job_id, later_job_id)
```

Add separate cases for missing files, wrong size, wrong checksum, path traversal, a leaf symlink, and an intermediate-directory symlink.

- [ ] **Step 2: Run worker tests and verify they fail before implementation**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing.ProcessingWorkerTests`

Expected: FAIL because `run_one`, input validation, logging, and receipt reconciliation do not exist.

- [ ] **Step 3: Implement immutable input validation and provenance hashing**

```python
def validated_input(root: Path, local_path: str, expected_size: int,
                    expected_sha256: str) -> Path:
    root = root.resolve(strict=True)
    relative = Path(local_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise OperationalFailure("input path escapes acquisition root")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise OperationalFailure("input path contains a symlink")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file() or resolved.stat().st_size != expected_size:
        raise OperationalFailure("input size no longer matches manifest")
    if sha256_file(resolved) != expected_sha256:
        raise OperationalFailure("input checksum no longer matches manifest")
    return resolved
```

Hash `repo_root/go10.sh` and `repo_root/v10/SOURCE_MANIFEST.json` immediately before launch and persist both against the claimed job.

- [ ] **Step 4: Implement per-attempt logs, subprocess execution, and receipt checks**

Call the launcher with the exact argument vector from the test and `cwd=repo_root`, `text=True`, `stdout` directed to the open per-attempt log, `stderr=subprocess.STDOUT`, `check=False`, and the worker-lock descriptor in `pass_fds`. Close rather than explicitly unlock the wrapper's descriptor: a surviving launcher must keep the lock. Parse `Database: ... (run UUID)` from the completed log, open only `results_root/stars.sqlite`, and require matching `run_id`, `source_sha256`, `analysis_path`, and database `exit_code`. Release review added a subprocess-kill regression proving both lock lifetime and retained log output.

Classify:

```python
if process.returncode == 0 and receipt.exit_code == 0:
    state, failure_kind = "succeeded", None
elif process.returncode != 0 and receipt.exit_code != 0:
    state, failure_kind = "solver_failed", "solver"
else:
    state, failure_kind = "operational_failed", "operational"
```

Any missing/malformed/mismatched receipt is `operational_failed`; no worker code calls `claim_next()` again during the same invocation.

- [ ] **Step 5: Prove SQLite acquisition remains writable during a long solve**

Use a blocking fake `run_process`, wait until the job is `running`, then open a second `Manifest` and record a new download/job. Assert that commit completes before releasing the fake solver, proving no transaction spans solver work.

- [ ] **Step 6: Run all processing tests**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing`

Expected: PASS for exact arguments, all path/integrity failures, success/failure receipt matching, and concurrent acquisition.

### Task 4: Operator CLI for work, status, and bounded cleanup

**Files:**
- Create: `run_allsky_processing.py`
- Modify: `allsky_download/processing.py`
- Test: `tests/test_allsky_processing_cli.py`

**Interfaces:**
- Consumes: Task 2 queue operations and Task 3 `run_one()`.
- Produces: commands `work --once`, `status`, and `cleanup`; exit codes 0 for success/no work/read-only audit, 1 for solver failure, 2 for operational failure, and 3 for refused/invalid cleanup.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_status_is_read_only_and_reports_counts(self):
    before = database_bytes_or_dump(manifest_path)
    completed = run_cli(["--archive", str(archive), "status"])
    self.assertEqual(completed.returncode, 0)
    self.assertIn("pending=1", completed.stdout)
    self.assertEqual(database_bytes_or_dump(manifest_path), before)

def test_cleanup_defaults_to_dry_run(self):
    completed = run_cli(["--archive", str(archive), "cleanup", "--job-id", str(job)])
    self.assertIn("DRY-RUN", completed.stdout)
    self.assertEqual(job_state(manifest_path, job), "operational_failed")

def test_cleanup_apply_never_requeues_solver_failure(self):
    completed = run_cli(["--archive", str(archive), "cleanup", "--apply",
                         "--job-id", str(solver_failed_job)])
    self.assertEqual(completed.returncode, 3)
    self.assertEqual(job_state(manifest_path, solver_failed_job), "solver_failed")
```

- [ ] **Step 2: Run CLI tests and confirm missing-entry-point failures**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing_cli`

Expected: FAIL because `run_allsky_processing.py` and parser commands are absent.

- [ ] **Step 3: Implement explicit global paths and subcommands**

Parser defaults:

```python
--archive      REPO/raw_allsky_samples
--results-dir  REPO/results/mmto-automatic
--repo-root    directory containing this script
```

`work` accepts only `--once`. `cleanup` requires at least one explicit selector (`--job-id`, `--remote-url`, `--night`, or `--source`) when `--apply` is used and requires a positive `--limit`; its default is dry-run. `status` makes no writes, including no implicit schema migration.

- [ ] **Step 4: Add stale reconciliation before any cleanup requeue**

For a selected stale `running` or `operational_failed` job, search `results/mmto-automatic/stars.sqlite` by verified source SHA. If exactly one compatible receipt exists, record its existing success/failure instead of returning the job to pending. If multiple receipts exist, refuse mutation and print their run IDs for an operator decision. Never reconcile from a different results database.

- [ ] **Step 5: Run CLI and full queue tests**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_processing_cli tests.test_allsky_processing`

Expected: PASS, with dry-run byte-for-byte/read-only behavior and bounded explicit mutations only.

### Task 5: Documentation, safe cron deployment, and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-19-mmto-processing-queue-design.md` only if implementation details required factual correction
- Test: `tests/test_allsky_cron.py`
- External state: user crontab, preserving every existing line

**Interfaces:**
- Consumes: tested `run_allsky_processing.py work --once` command.
- Produces: a documented and installed `WIDE_FIELD_SOLVER_MMTO_PROCESSING_ACTIVE` cron entry using a lock distinct from acquisition.

- [ ] **Step 1: Add cron-text regression and operator documentation**

Document these commands:

```bash
uv run --frozen python run_allsky_processing.py status
uv run --frozen python run_allsky_processing.py cleanup --source mmto --night 2026-09-18 --limit 20
uv run --frozen python run_allsky_processing.py cleanup --source mmto --night 2026-09-18 --limit 20 --apply
```

Document all states, no automatic retry, FIFO behavior, separate acquisition/processing locks, stale-job interpretation, cleanup reconciliation, frozen go10 provenance, and explicit exclusion of go11.

- [ ] **Step 2: Run focused acquisition and queue suite**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_manifest tests.test_allsky_cron tests.test_allsky_cli tests.test_allsky_processing tests.test_allsky_processing_cli`

Expected: PASS.

- [ ] **Step 3: Run a controlled fake-worker integration and read-only live status**

Run the fake launcher integration entirely in a temporary directory, then run:

```bash
uv run --frozen python run_allsky_processing.py status
uv run --frozen python run_allsky_processing.py cleanup --source mmto --limit 20
```

Expected: the integration records one verified terminal receipt; live commands do not enqueue or mutate existing downloads.

- [ ] **Step 4: Verify frozen boundaries and repository regressions**

Record pre/post SHA-256 for `go10.sh`, every tracked file below `v10/`, and any present `go11.sh`/`v11/` file, then run:

```bash
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Expected: queue/acquisition tests and demo PASS. Report any unrelated pre-existing preserved-version failures exactly; do not modify thresholds or frozen files to hide them.

- [ ] **Step 5: Install the idempotent processing cron entry**

Preserve the existing crontab byte-for-byte except for replacing any prior line with the same marker, then install:

```cron
# WIDE_FIELD_SOLVER_MMTO_PROCESSING_ACTIVE
*/2 * * * * cd /home/pth/WORKSHOP/WIDE-FIELD-SOLVER && mkdir -p /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/raw_allsky_samples/processing-logs /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/results/mmto-automatic && /home/pth/.local/bin/uv run --frozen python run_allsky_processing.py --archive /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/raw_allsky_samples --results-dir /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/results/mmto-automatic --worker-lock /tmp/wide-field-solver-mmto-processing.lock work --once >> /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/raw_allsky_samples/mmto-processing-cron.log 2>&1
```

- [ ] **Step 6: Verify installed schedule and first harmless invocation**

Run `crontab -l`, confirm acquisition remains at every 20 minutes and processing is every two minutes under its own lock, then invoke `status`. Because deployment deliberately does not enqueue the legacy archive, the worker either reports `NO_WORK` or processes only a genuinely new post-deployment MMTO job.
