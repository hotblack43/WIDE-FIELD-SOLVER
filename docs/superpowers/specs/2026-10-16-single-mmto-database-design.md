# Single MMTO Database Design

Date: 2026-10-16

## Purpose

Consolidate every MMTO solver receipt and its stored scientific evidence into
one canonical database, `results/stars.sqlite`. Eliminate the operational split
that allowed the automatic worker to write `results/mmto-automatic/stars.sqlite`
while the v20 bounded-backward pipeline read only the canonical database.

The migration must preserve every historical run, including repeated analyses
of the same source SHA-256 and both successful and failed solver receipts. After
the migration, every repository MMTO writer and reader uses the canonical
database, so v20 can recognize all completed images before walking backward.

## Current evidence

At diagnosis time, the canonical database used the compact storage schema and
the automatic database used the compatible legacy schema. The automatic
database contained 713 runs, 14,241 products, and 2,841,123 measurement rows.
None of its run UUIDs existed in the canonical database. Its 713 source digests
included 628 already represented by other canonical runs and 85 absent from the
canonical database. Repeated source digests are distinct historical analyses,
not disposable duplicate rows.

The root filesystem had only about 2.3 GB free. The mounted
`/media/pth/Sandisk8TB` filesystem had sufficient space for safety copies and
migration staging.

## Canonical location and writers

`results/stars.sqlite` is the sole operational database. The bounded v20
pipeline already uses this location by default. The automatic processing
worker, its cron-command generator, its installed cron entry, documentation,
and regression tests must be changed from `results/mmto-automatic` to
`results`.

Existing analysis directories below `results/mmto-automatic/runs/` remain in
place because migrated run records point to them. They contain binary and
rendered evidence that is intentionally outside SQLite; retaining those paths
does not constitute a second database.

## Writer quiescence and recovery

Before database mutation, stop or pause the v20 pipeline and automatic worker,
prevent cron from launching another automatic writer, and verify that neither
database has an open writer. Do not merge against a changing database.

Create a byte-preserving safety copy of the canonical database and two
byte-preserving copies of the automatic database on `/media/pth/Sandisk8TB`.
Verify every SHA-256 digest against its original. One automatic copy is the
read-only merge source and the other is untouched recovery evidence; neither is
an operational database. Only then remove the local automatic database file,
thereby releasing enough local space for the canonical database to grow. Do not
delete the recovery artifacts as part of the migration.

If migration or verification fails, leave automatic processing disabled, keep
the canonical database and both automatic recovery artifacts intact, and report
the exact failed check. Do not resume writers until the canonical result has
passed every required check.

## Lossless schema-aware merge

Provide a tested migration helper that accepts an existing compact destination
and a legacy or compact source. It must validate the recognized application ID,
schema version, table layout, source foreign keys, and content hashes before
inserting anything.

Import every source run whose UUID is absent from the destination. A matching
UUID is idempotent only when every run field and all associated logical product
and measurement rows are identical; otherwise fail closed. Preserve all runs
whose source SHA-256 is already represented under another UUID.

For a legacy source, transform logical `products` and `measurements` rows into
the destination compact tables:

- exact product bytes go to `product_content`, keyed by their recorded SHA-256;
- each logical product goes to `product_refs`;
- canonicalized measurement JSON goes to `measurement_content`, keyed by
  product SHA-256 and row number; and
- each logical measurement identity goes to `measurement_refs`.

An existing content key with different bytes or normalized JSON is a hard
conflict. The helper is resumable and commits one complete run at a time, so a
space or interruption failure never leaves a partially imported run. Each run
transaction must pass foreign-key checks before commit.

## Verification and cutover

After import, prove that every source run UUID and all its logical products and
measurements are represented identically through the canonical public views.
Verify source and destination product hashes, per-run row counts, foreign keys,
SQLite integrity, and expected canonical run-count growth. Confirm that all
verified MMTO manifest digests with any historical receipt are visible in the
canonical database.

Run the focused merge, worker-default, cron-generation, and v20-selection tests,
then the complete repository test suite and required historical demo. Update
the installed processing cron entry only from tested code and confirm it names
`results`, never `results/mmto-automatic`.

After successful verification and cron cutover, confirm that the obsolete local
`results/mmto-automatic/stars.sqlite` remains absent. Resume automatic
processing against the canonical database. A v20 dry run must then skip the
merged receipts, list at most one observing night at a time, and demonstrate
that the durable cursor can advance backward instead of draining
already-completed work.

## Non-goals

- Do not delete or coalesce repeated scientific runs.
- Do not move historical analysis directories or rewrite their stored paths.
- Do not modify or erase `v16/`, `v17/`, `v18/`, `v19/`, their launchers,
  catalogues, lockfiles, manifests, runtime-boundary records, or preserved
  reference products. Verify their recorded hashes before and after migration.
- Do not change astrometric, photometric, or planetary algorithms.
- Do not create a branch, worktree, or second operational database.
