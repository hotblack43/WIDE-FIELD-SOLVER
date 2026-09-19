# MMTO Automatic Processing Queue Design

**Date:** 2026-09-19  
**Status:** Approved for implementation

## Purpose

Process each newly downloaded nighttime MMTO image once without repeatedly
passing the accumulated archive to the solver. Acquisition must remain
independent: a slow or failed analysis cannot delay, overwrite, or erase later
downloads. The system must retain an auditable trail and allow an explicit
cleanup sweep to recover genuinely interrupted or overlooked work.

## Fixed boundaries

- Root `go10.sh` and the complete `v10/` runtime are frozen. The worker invokes
  `go10.sh` as an external executable and never modifies its launcher, package,
  database schema, or scientific behavior.
- Another Codex is developing `go11.sh`/`v11/`. This work must neither read from
  nor modify that development path and must not silently switch queued jobs to
  it.
- Queue state is orchestration evidence only. It must never seed, constrain, or
  select a blind astrometric, photometric-zenith, or planetary solution.
- Raw images, solver run directories, queue history, and scientific database
  rows are never automatically deleted.
- A completed image is not automatically reprocessed after code or catalogue
  changes. Reprocessing is always an explicit future action.

## Selected architecture

Use a durable processing queue in the existing acquisition
`raw_allsky_samples/manifest.sqlite`. This is preferred over filesystem marker
files or inferring work state from `results/stars.sqlite` because acquisition,
claiming, recovery, and duplicate suppression then have explicit transactional
state.

The implementation is isolated in new root-level orchestration code:

- `allsky_download/processing.py`: queue schema and transactional operations.
- `run_allsky_processing.py`: `work`, `status`, and `cleanup` commands.
- Focused root tests for queue transitions, worker invocation, reconciliation,
  and cron behavior.

Existing acquisition code changes only where required to create a job in the
same transaction that records a newly downloaded file as verified. No v10 or
v11 file changes are permitted.

## Queue schema

Add two tables without changing the existing `downloads` rows.

### `processing_jobs`

One durable row represents the processing lifecycle of one unique image:

| Column | Meaning |
|---|---|
| `job_id` | Integer primary key |
| `remote_url` | Acquisition identity; unique and references `downloads.remote_url` |
| `source_sha256` | Verified original bytes; unique across jobs |
| `solver_target` | Fixed orchestration target; `go10` for this implementation |
| `state` | `pending`, `running`, `succeeded`, `solver_failed`, `operational_failed`, or `interrupted` |
| `enqueued_utc` | Initial enqueue time |
| `started_utc` | Current/last attempt start |
| `finished_utc` | Terminal attempt time |
| `attempt_count` | Number of explicit worker starts; normally one |
| `worker_token` | Unique claim token for the active attempt |
| `solver_run_id` | Verified `stars.sqlite.runs.run_id`, when recorded |
| `analysis_path` | Solver analysis directory, when recorded |
| `solver_exit_code` | Frozen launcher exit status, when started |
| `failure_kind` | Null, `solver`, `operational`, or `interrupted` |
| `error` | Concise human-readable failure detail |
| `processing_log` | Path to the preserved worker/launcher log |
| `launcher_sha256` | Exact root `go10.sh` bytes used for this attempt |
| `source_manifest_sha256` | Exact `v10/SOURCE_MANIFEST.json` bytes used for this attempt |

`remote_url` and `source_sha256` uniqueness make enqueue idempotent. The path
is resolved through the referenced download row rather than copied into the job
and allowed to become stale.

### `processing_events`

Every transition appends an event with event ID, job ID, UTC time, previous
state, new state, worker token, and reason. Cleanup therefore does not erase the
original failure/interruption trail when it explicitly returns a job to
`pending`.

## Enqueue behavior

The recurring MMTO downloader opts into processing-job creation. Other manual
downloads and other sources do not enqueue unless explicitly enabled later.

For a genuinely new successful MMTO transfer:

1. Verify the downloaded size and SHA-256 as today.
2. In one SQLite transaction, mark the `downloads` row verified and insert the
   `pending` processing job plus its initial event.
3. Commit both together.

Ordinary `REUSE` events do not create jobs. Therefore deploying the queue does
not enqueue the existing MMTO archive. A unique SHA-256 already present in the
queue is a no-op even if a second URL names the same bytes.

If the process dies before the database transaction commits, the file may
exist without a verified download/job record. The existing acquisition retry
and the explicit cleanup audit expose that condition; it is never treated as a
successful invisible job.

## Worker behavior

`run_allsky_processing.py work --once` performs at most one job:

1. Under a short `BEGIN IMMEDIATE` transaction, select the oldest `pending`
   job, verify its referenced download remains `downloaded`/`verified`, assign
   a fresh worker token, increment `attempt_count`, append a transition event,
   and commit `running`.
2. Close the transaction before any file hashing or solver work.
3. Resolve the image beneath the configured acquisition root; refuse symlinks,
   traversal, missing files, size changes, or checksum changes as operational
   failures.
4. Record the current checksums of root `go10.sh` and
   `v10/SOURCE_MANIFEST.json`.
5. Invoke the unchanged command with exactly one input:

   ```sh
   ./go10.sh ABSOLUTE_IMAGE_PATH --results-dir ABSOLUTE_RESULTS_ROOT
   ```

6. Preserve combined stdout/stderr in
   `raw_allsky_samples/processing-logs/job-<id>-attempt-<n>.log` while allowing
   cron output to identify the active job and final disposition.
   Stream output directly to that file, so a terminated wrapper does not lose
   output already written by the solver.
7. Extract the emitted database run UUID, then verify that row in
   `results/stars.sqlite` has the same source SHA-256. Store its run ID and
   analysis path. The emitted value is treated as a receipt to verify, never as
   blind-solver input.
8. Commit the terminal queue state and transition event using the worker token;
   a stale or foreign worker cannot finalize another worker's claim.

The worker never holds a SQLite transaction while `go10.sh` runs.

The initial cron deployment uses the repository-local
`results/mmto-automatic/` as `ABSOLUTE_RESULTS_ROOT`. Keeping automated MMTO
runs in their own append-only database makes queue reconciliation unambiguous
and avoids mixing unattended cadence runs with manual experiments.

## Concurrency and scheduling

Keep acquisition and processing in separate cron entries and use separate
locks:

- Acquisition: existing minutes `0,20,40`, existing MMTO acquisition lock.
- Processing: every two minutes, under a new processing-worker lock.

The processing cron calls `work --once`. The CLI itself takes the nonblocking
worker lock before claiming a row, so direct/manual work and cleanup commands
participate in the same exclusion rule as cron. Minute zero may run before
acquisition has committed; the minute-two invocation then sees the new job. If
an earlier solver process still holds the worker lock, the command reports
`BUSY` and leaves every queued row unchanged. Acquisition continues under its
independent lock and appends later jobs. The next free processing invocation
selects the oldest pending job, so backlog is FIFO and can drain faster than
the 20-minute arrival cadence when ordinary solves take less than 20 minutes.

The launcher inherits the lock descriptor. The wrapper closes its own descriptor
without explicitly unlocking the shared open-file description, keeping a
surviving launcher protected if the wrapper is killed or unwinds early.

One worker is the default. Parallel solver processes are intentionally excluded
until measured backlog and resource use justify a separate design.

## Failure classification and retry policy

There is no stochastic retry policy. The production solver is deterministic
for the same image, code, data, and arguments; deterministic initial seeds are
not random retry trials.

- `succeeded`: launcher returned zero and the matching solver database receipt
  was verified. Never automatically processed again.
- `solver_failed`: launcher returned nonzero and a matching solver run row
  records a completed scientific/analysis failure. Never automatically retried.
- `operational_failed`: the worker could not validate input, start the launcher,
  access storage, or verify a solver receipt. Never automatically retried.
- `running`: an active claimed attempt.
- `interrupted`: assigned only by an explicit cleanup operation after proving a
  stale running job has no completed solver result.

Later pending jobs are not blocked by a terminal failure or stale running row.

## Status and cleanup

`run_allsky_processing.py status` is read-only and reports:

- Active/running job and age.
- Pending count and oldest pending age.
- Counts for success, solver failure, operational failure, interrupted, and
  stale running jobs.
- Recent job IDs, image paths, states, and result/run identifiers.

`run_allsky_processing.py cleanup` is also read-only by default. It audits:

- Verified downloads with no processing job, optionally bounded by source,
  observing night, explicit job/image, and limit so the legacy archive is not
  accidentally flooded into the queue.
- Stale running jobs.
- Operational failures.
- Queue jobs whose matching solver result exists in `stars.sqlite` but whose
  queue terminal state was never recorded.

Cleanup first reconciles by verified source SHA-256 and solver run receipt. If
the solver finished, it records the existing success/failure rather than
rerunning the image. Only an explicit `cleanup --apply` may:

- Enqueue selected overlooked verified images.
- Move a proven stale/no-result job through `interrupted` back to `pending`.
- Return a selected operational failure to `pending`.

Cleanup never requeues `solver_failed`. There is no periodic automatic cleanup
cron in this version.

## Frozen solver and future versions

Jobs created by this implementation have an explicit solver target of root
`go10.sh`. The worker refuses a different target. It records launcher and v10
source-manifest hashes for provenance but does not require them to equal a
compiled-in value, because the repository may contain legitimate local state
that still needs to be recorded exactly.

Introducing go11 processing later requires a deliberate new target/policy. It
must not silently reinterpret or rerun completed go10 jobs.

## Security and integrity

- Resolve and validate every input beneath the configured acquisition root.
- Reject symlinks and path traversal.
- Recompute size and SHA-256 immediately before processing and compare them to
  the verified acquisition manifest.
- Pass subprocess arguments as an argument vector, never through a shell.
- Use SQLite foreign keys, constrained state values, transactions, and worker
  tokens for transitions.
- Store concise database errors and full process output in the per-attempt log.
- Do not expose timestamps, paths, prior identities, or queue data to the blind
  scientific command beyond the input path already required by `go10.sh`.

## Testing

Tests use temporary directories/databases and a fake executable implementing
the frozen launcher boundary. They do not modify or repeatedly execute go10.

Required regression evidence:

1. A newly verified opted-in MMTO download atomically creates one pending job.
2. Existing rows and `REUSE` do not create an initial processing flood.
3. Duplicate URL and duplicate SHA-256 enqueue attempts remain one job.
4. FIFO claiming and worker-token ownership are enforced.
5. The database is not transaction-locked during a long fake solve; acquisition
   can commit another download/job concurrently.
6. The process lock prevents a second active worker.
7. Exact one-image go10 argument construction is verified without a shell.
8. Input path, symlink, size, and checksum failures are operational failures.
9. Success requires both zero exit and a matching database run receipt.
10. Solver and operational failures are classified separately and never
    automatically retried.
11. A killed worker leaves a visible stale running row while later pending work
    remains claimable.
12. Cleanup reconciles an already-recorded solver run without rerunning it.
13. Cleanup is dry-run by default and only explicit bounded `--apply` changes
    state or enqueues legacy omissions.
14. Status counts and oldest-job age are correct.
15. Frozen `go10.sh`/v10 hashes and all go11/v11 paths remain unchanged by the
    implementation.

Before handoff, run the focused queue/acquisition tests, the full repository
unit command, the required demo regression, a dry-run cleanup/status audit, and
one controlled fake-worker integration. Existing unrelated preserved-version
failures must be reported rather than hidden or relaxed.

## Documentation and operations

Update the acquisition README with:

- Queue state meanings and no-auto-retry policy.
- Status and bounded cleanup examples.
- Separate acquisition/processing cron entries and locks.
- Backlog interpretation and the invariant that no file/result is erased.
- The frozen go10 boundary and explicit exclusion of go11 work.

Do not install the processing cron until implementation tests pass and a manual
`status` plus controlled one-job invocation succeed.
