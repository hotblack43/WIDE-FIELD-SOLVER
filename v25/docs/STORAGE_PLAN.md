# Lossless storage reduction — 19 September 2026

## Contract and design

Reduce physical duplication, not scientific evidence. All runs, product paths,
original text bytes, CSV rows, flags and identifiers remain available through
ordinary SQLite. Preserve fixed-arity inserts from frozen v6–v10 writers and
their application/user version checks. No scientific calculations change.

Store each exact product once by SHA-256, with per-run/path references. Store
parsed CSV bodies once per product hash/row number, with small indexed per-run
measurement references. Compatibility views and insert triggers retain the
existing public SQL schema without decompression functions. Compact only JSON
whitespace in parsed rows; raw product bytes remain exact. Transactionally
upgrade legacy databases; explicit VACUUM reclaims old pages without replacing
the database file or losing concurrent commits.

After successful analysis and recording, losslessly ZIP intermediate directories
`joint_candidate_solution` and `stellar_only_products`; verify every member
before removing loose originals. Keep final reports/products directly accessible.
The recorder also reads archived text snapshots under their original paths.
Failures to archive warn and preserve loose files; never change fit success.

## Task 1: compatible database deduplication

Write failing duplicate-payload, legacy-migration and frozen-writer tests. Add
internal content tables and SQL compatibility views/triggers; migrate atomically.
Add explicit compaction command. Verify exact bytes, logical rows, plain SQLite
JSON queries, rollback, concurrency and rejection of invalid formats.

Verification: `cd v11 && uv run --frozen python -m unittest test_point_star_database -v`.
Expected: all tests pass, duplicate imports grow references, not payload bodies.

## Task 2: compressed intermediate snapshots

Write failing round-trip, archive-failure and integration tests. Add verified
archive helper, recorder support and successful-analysis finalization. Never
archive failed analyses or alter root products. Verify re-recording archives
preserves all product paths/bytes and CSV rows.

Verification: `cd v11 && uv run --frozen python -m unittest test_point_star_storage test_point_star_database -v`.
Expected: lossless archive, unchanged root files, safe failure and repeated calls.

## Task 3: acceptance and publication

Update DATABASE/FEATURE_STATUS and source manifest deliberately. Measure the
existing final v11 run before/after; compare logical database digests, every
archived byte and final report hashes. Run full v11 suite/demo and root suite/demo
before committing. Obtain one independent review of storage changes, resolve
important findings with regression tests, then commit/push this bounded change.
Remove only confirmed disposable verification copies after publication.

## Review focus

Legacy fixed-arity writers, stock SQLite readers, transaction rollback, archival
failure/retry, no silent loss of intermediate evidence, symlinks, concurrent
writers, and unchanged final scientific bytes. Large/unsupported database
extensions must fail explicitly rather than silently migrate.

## Execution record

Pre-flight: Task 2 consumes Task 1 append API unchanged; archived snapshot paths
must be identical to loose paths. Task 3 checks both via exact-byte digests.
Work stays in the existing user-authorized checkout; no frozen runtime edits.
Commits are deferred until full root verification, as required by AGENTS.md.

Task 1: duplicate-content and legacy-writer tests RED→GREEN; physical payloads
remain single-copy across repeated imports. Task 2: archive round-trip,
failure, symlink and success-finalization tests RED→GREEN. Focused suite passed
25 tests before final review. Actual copied run passed logical equality for
94 products, 32,216 measurements and 1,409 stellar joins; 127 original files
verified, including the unchanged PDF. Total 365,969,312 → 268,317,827 bytes.

Final review: one important finding, customized legacy view definitions could
be silently replaced despite unchanged object names. Regression reproduced
this failure; migration now compares complete supported schema definitions.
No declined judgments or deferred findings. Review also exercised mixed
concurrent v6–v10/v11 writers and compaction: all expected 19 runs retained,
integrity and foreign-key checks clean.
