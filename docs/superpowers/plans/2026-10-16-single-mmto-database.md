# Single MMTO Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Losslessly merge the automatic MMTO database into
`results/stars.sqlite` and make that file the sole operational database for all
future MMTO processing.

**Architecture:** Add a resumable, schema-aware migration helper that imports
legacy logical rows into the canonical compact schema one complete run per
transaction. Quiesce writers, put verified recovery copies on the mounted
external disk, perform and verify the in-place canonical merge, then point the
automatic worker and installed cron entry at the canonical results directory.

**Tech Stack:** Python 3.12, SQLite, `unittest`, Bash launchers, system cron.

**Spec:** `docs/superpowers/specs/2026-10-16-single-mmto-database-design.md`

## Global Constraints

- `results/stars.sqlite` is the sole operational solver database after cutover.
- Preserve every run UUID, including failures and repeated source SHA-256 values.
- Preserve exact product bytes and every logical measurement row.
- Never modify or erase `v16/`, `v17/`, `v18/`, `v19/`, or any associated
  launcher, catalogue, lockfile, manifest, boundary record, or reference product.
- Do not create a branch, worktree, or parallel operational database.
- Keep historical `results/mmto-automatic/runs/` analysis directories because
  migrated records reference them.
- Stop all writers before copying or merging; fail closed if either database is
  open for writing.
- Recovery copies live on `/media/pth/Sandisk8TB` and are never used by runtime
  code.
- Do not commit; the worktree already contains Peter's uncommitted v20 work.

## Review Focus

- Insufficient local space must abort before import, without a partial run.
- A repeated run UUID must be accepted only when all run, product, and
  measurement fields are identical; otherwise fail closed.
- Identical product SHA-256 with different bytes or measurement JSON must fail
  before the affected run commits.
- An interruption between runs must be safely resumable without duplicated
  logical rows.
- Cron must not restart a writer during backup, merge, verification, or cutover.

---

### Task 1: Add a lossless, resumable database merger

**Files:**
- Create: `scripts/merge_point_star_databases.py`
- Create: `test_merge_point_star_databases.py`

**Interfaces:**
- Produces `DatabaseLayout` and `MergeReport` dataclasses.
- Produces `inspect_database(path: Path) -> DatabaseLayout`.
- Produces `estimate_merge(destination: Path, source: Path) -> MergeReport`.
- Produces `merge_databases(destination: Path, source: Path) -> MergeReport`.
- CLI requires `--destination PATH --source PATH`; `--verify-only` performs the
  complete equivalence audit without writes.

- [ ] **Step 1: Write failing legacy-to-compact merge tests**

  Add tests proving that two source runs with the same source SHA-256 but
  different UUIDs both survive; failed receipts survive; exact product bytes,
  product references, normalized measurement bodies, measurement identities,
  and public compatibility views match the source; and the source file is
  byte-identical before and after.

- [ ] **Step 2: Run the focused tests and observe the missing-helper failure**

  Run: `uv run --frozen python -m unittest -v test_merge_point_star_databases`

  Expected: FAIL because the helper module does not exist.

- [ ] **Step 3: Implement schema inspection and preflight estimation**

  Recognize only the repository application ID/schema version and the exact
  legacy or compact layouts. Validate source foreign keys and recorded product
  SHA-256 values. Return source logical counts, absent run counts, unique missing
  content sizes, and a conservative required-free-space estimate. Refuse a
  destination/source identity match, symlinks, unknown schema, malformed JSON,
  hash conflicts, and insufficient free space.

- [ ] **Step 4: Run focused preflight tests**

  Expected: the layout, source-integrity, content-conflict, symlink, and
  insufficient-space tests PASS while merge tests remain red.

- [ ] **Step 5: Implement one-run transactional import**

  For each absent source run UUID, begin an immediate transaction, insert its
  `runs` row, materialize legacy or compact logical products into
  `product_content`/`product_refs`, materialize canonical JSON into
  `measurement_content`/`measurement_refs`, run a foreign-key check, and commit.
  Existing UUIDs use exact logical equality as the idempotency test. Emit a
  progress line after each committed run.

- [ ] **Step 6: Add and run interruption/idempotency/conflict tests**

  Tests must interrupt after one committed run, resume to completion, rerun a
  completed merge without changing counts, reject a conflicting run UUID, reject
  conflicting product bytes, and reject conflicting normalized measurement
  JSON. Run the focused module and require all tests to PASS.

- [ ] **Step 7: Add and run complete equivalence verification tests**

  `--verify-only` must compare every source UUID and every logical product and
  measurement row through the destination public views, check product hashes,
  check destination foreign keys, and report explicit counts. Corrupt a fixture
  row to prove the verifier fails, restore it, and require the complete focused
  test module to PASS.

### Task 2: Make the canonical database the only runtime destination

**Files:**
- Modify: `run_allsky_processing.py:52-59`
- Modify: `allsky_download/cron.py:19-35`
- Modify: `scripts/plot_things_1.py:609-625`
- Modify: `tests/test_allsky_cron.py:12-25`
- Modify: `tests/test_allsky_processing_cli.py`
- Modify: `test_plot_things_1.py`
- Modify: `README.md:240-270`
- Modify: `docs/DATABASE_INSPECTION_PLOTS.md:1-15`
- Modify: `docs/MMTO_PHOTOMETRY_PIPELINE.md`

**Interfaces:**
- Automatic processing defaults to `REPO_ROOT / "results"`.
- `processing_cron_lines(...)` emits `--results-dir REPO_ROOT/results` and never
  creates or names `results/mmto-automatic`.
- Inspection plots default to the single canonical database while retaining
  explicit repeated `--database` arguments for deliberate external comparisons.

- [ ] **Step 1: Write failing canonical-path tests**

  Assert the processing CLI default is the repository `results` directory, the
  generated cron line names that directory exactly, no generated command or
  default plot invocation names `mmto-automatic`, and explicit multi-database
  plotting remains available only when requested.

- [ ] **Step 2: Run the focused tests and verify the old split-path failures**

  Run: `uv run --frozen python -m unittest -v tests.test_allsky_cron tests.test_allsky_processing_cli test_plot_things_1`

  Expected: only the new canonical-path assertions FAIL.

- [ ] **Step 3: Apply the minimal runtime path changes**

  Change only the active root scheduler/worker/inspection code. Do not edit any
  file below `v16/`, `v17/`, `v18/`, or `v19/`, and do not alter their launchers.

- [ ] **Step 4: Update current operator documentation**

  Describe `results/stars.sqlite` as the sole database, the historical automatic
  analysis-directory retention, the completed migration, and recovery-copy
  location. Leave historical design/plan documents factual and unchanged.

- [ ] **Step 5: Run the focused tests**

  Require the three focused test modules to PASS with no unexpected warnings.

### Task 3: Prove frozen v16-v19 preservation and quiesce writers

**Files:**
- Read only: `docs/v16-runtime.json`, `docs/v17-runtime.json`,
  `docs/v18-runtime.json`, `docs/v19-runtime.json`
- Read only: complete `v16/`, `v17/`, `v18/`, `v19/` packages and their launchers
- External state: installed crontab and live MMTO processes

**Interfaces:**
- Produces pre-migration hashes and test receipts for the frozen versions.
- Produces a paused processing-cron state with no database writer alive.

- [ ] **Step 1: Capture preservation evidence before mutation**

  Run the v16, v17, v18, v19, and v20 boundary tests and save their output under
  the external recovery directory. Independently hash every path recorded by the
  four runtime boundary JSON files into a pre-migration audit file.

- [ ] **Step 2: Pause only the MMTO processing cron entry**

  Preserve the complete pre-change crontab in the external recovery directory,
  comment the command following `# WIDE_FIELD_SOLVER_MMTO_PROCESSING_ACTIVE`,
  install the paused crontab, and confirm the raw-image acquisition cron remains
  active and unchanged.

- [ ] **Step 3: Stop or wait out existing writers**

  Stop the redundant v20 batch if still active, wait for any inherited go10
  worker to exit, then use process inspection, lock acquisition, and `lsof` to
  prove neither database has an open writer. Do not kill unrelated processes.

### Task 4: Back up, merge, verify, and cut over the live data

**Files:**
- Mutate: `results/stars.sqlite`
- Remove after two external copies are verified:
  `results/mmto-automatic/stars.sqlite`
- Preserve: `results/mmto-automatic/runs/`
- Create recovery artifacts below:
  `/media/pth/Sandisk8TB/WIDE-FIELD-SOLVER-db-merge-20261016/`
- External state: installed crontab

**Interfaces:**
- Consumes Task 1's merge CLI and Task 2's tested canonical cron generator.
- Produces one verified canonical database and one canonical installed writer.

- [ ] **Step 1: Record immutable pre-merge facts**

  Record database sizes, SHA-256 digests, schemas, application/user versions,
  run/product/measurement counts, manifest coverage, filesystem free space, and
  the absence of writers in a timestamped audit file on the external disk.

- [ ] **Step 2: Create and verify recovery copies**

  Copy the canonical database once and the automatic database twice to the
  external recovery directory. Designate one automatic copy as the read-only
  merge source and leave the other untouched as recovery evidence. `fsync` the
  copies and directory, require SHA-256 equality with their local sources, then
  remove the local automatic database to free its 5.3 GB without touching its
  `runs/` directory.

- [ ] **Step 3: Run merge preflight**

  Run the helper's estimate/report mode against canonical destination and
  external automatic source. Require recognized schemas, 713 source runs,
  14,241 source products, 2,841,123 source measurements (or explicitly record
  any additional rows created before quiescence), no UUID/content conflicts,
  and sufficient free-space margin before proceeding.

- [ ] **Step 4: Perform the resumable merge**

  Import one complete run per transaction with both MMTO orchestration locks
  held. Stream progress to the external audit directory. On any exception, stop
  with processing cron still paused and retain every recovery artifact.

- [ ] **Step 5: Verify source equivalence and database health**

  Run `--verify-only`, `PRAGMA foreign_key_check`, and full
  `PRAGMA integrity_check`. Confirm expected count growth, exact product hashes,
  exact logical measurement equality, and that the canonical database sees the
  union of every receipt associated with verified MMTO manifest digests.

- [ ] **Step 6: Verify frozen versions again**

  Repeat the boundary tests and recorded-file hashes from Task 3. Require exact
  pre/post equality for v16, v17, v18, and v19 before cutover.

- [ ] **Step 7: Install the tested canonical cron command**

  Replace only the paused MMTO processing line with the output of
  `processing_cron_lines(...)`. Confirm the installed entry points to
  `results`, contains no `mmto-automatic`, and the raw acquisition entry remains
  byte-identical.

- [ ] **Step 8: Remove the obsolete local database path and resume processing**

  Confirm `results/mmto-automatic/stars.sqlite` is absent, retain its historical
  `runs/` tree, and allow the next cron worker to write only
  `results/stars.sqlite`. Keep external recovery artifacts untouched.

### Task 5: End-to-end regression and backward-cursor proof

**Files:**
- Update if numerical/data counts changed: `docs/MMTO_PHOTOMETRY_PIPELINE.md`
- Produce a new v20 dry-run audit log in the external recovery directory

**Interfaces:**
- Demonstrates repository correctness, one writer destination, and genuine
  backward v20 discovery after merged receipts are visible.

- [ ] **Step 1: Run focused migration and orchestration tests**

  Run: `uv run --frozen python -m unittest -v test_merge_point_star_databases tests.test_allsky_cron tests.test_allsky_processing_cli test_plot_things_1 test_run_mmto_photometry_pipeline_v20 test_v20_runtime_boundary`

  Expected: PASS.

- [ ] **Step 2: Run the complete repository suite**

  Run: `uv run --frozen python -m unittest discover -v`

  Expected: PASS with zero failures or errors.

- [ ] **Step 3: Run the required historical demo**

  Run: `./demo.sh --output results/check-unique-name`

  Expected: PASS without overwriting historical reference evidence.

- [ ] **Step 4: Prove one operational database**

  Check active root code, generated cron, installed cron, and current operator
  documentation for `mmto-automatic/stars.sqlite`; only historical plan/spec
  records may mention the former database. Confirm no live process has the old
  path open and the next automatic worker receipt appears in
  `results/stars.sqlite`.

- [ ] **Step 5: Prove v20 can walk backward**

  Run `./go_mmto_photometry_v20.sh --dry-run`, capture the complete output, and
  require merged receipts to be skipped. Verify it lists no more than one night
  per MMTO request and that its proposed cursor is older than the current night
  when the legitimate unfinished local queue does not fill the cap. If genuine
  unfinished files fill the cap, record their exact count and use a temporary
  copied state/database fixture—not the live cursor—to demonstrate backward
  advancement without processing or deleting those files.

- [ ] **Step 6: Inspect final changes and evidence**

  Run `git diff --check`, `git status --short`, database count/hash audits, and
  pre/post frozen-version comparisons. Report every changed code/document path,
  canonical database location, recovery directory, retained historical run
  directory, installed cron command, and primary dry-run/verification logs.
