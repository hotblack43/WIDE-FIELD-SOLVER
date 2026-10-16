# MMTO Bounded Backward V20 Design

Date: 2026-10-16

## Purpose

Create an independent v0.20.0 runtime that preserves every v19 scientific and
plotting capability while adding a genuinely bounded MMTO acquisition queue.
Each invocation may select at most 40 unfinished 20-minute dark-sky cadence
images by default. It must walk backward through the MMTO archive without first
inventorying the complete historical range and without analysing an image that
already has a solver receipt.

This is a new version. V19 and all earlier runtimes, launchers, manifests,
examples, and result directories remain unchanged.

## Meaning of finished work

An image is finished when the selected `stars.sqlite` contains any solver run
receipt for its source SHA-256. Receipts from v16, v17, v18, v19, v20, and other
repository solver generations all count. Both successful and scientific-failure
receipts count, preserving the established no-automatic-retry rule. A verified
download with no solver receipt is unfinished and must be considered before a
new remote file. Duplicate remote URLs resolving to a finished SHA-256 must not
be analysed again.

## Version boundary

- Freeze the complete v19 package at the v20 boundary in
  `docs/v19-runtime.json` and add a preservation regression.
- Copy the complete v19 runtime to `v20/`, update only active version identity,
  v20 documentation, and v20 source-manifest ownership.
- Add `go20.sh`, `go_v0.20.0.sh`, and `go_mmto_photometry_v20.sh`.
- Keep v20 runnable through its own frozen project without `.worktrees`.
- Keep the v19 variable-star catalogue and every v19 analysis stage unchanged.

## Bounded acquisition and selection

V20 never calls the MMTO adapter with a multi-night historical date range. It
requests one observing-night directory at a time. Within a night it applies the
existing Sun-below-minus-12-degree and 20-minute cadence rules before consulting
the local download manifest and solver receipts.

The default `--max-images 40` is a hard per-invocation bound on selected
unfinished images and is configurable to another positive integer. Selection is
newest first. The current MMTO observing night is checked first so new images
retain routine priority. Remaining capacity is filled from the durable backward
cursor, one older observing night at a time. Discovery stops immediately when
the cap is full; it does not list older nights merely to report backlog totals.
The default oldest observing night is 2026-06-30, matching the v19 variable-star
product boundary, and `--oldest-night` may explicitly move that floor earlier.
No MMTO directory earlier than the effective floor is listed.

For a known manifest URL, its recorded digest determines whether any solver
receipt already finished the image. A known verified download lacking a receipt
is selected without downloading it again. An unseen or invalid local download
is selected for download. Because an unseen remote file has no digest until it
is downloaded, v20 rechecks its SHA-256 against all receipts before invoking the
solver; this prevents analysis of byte-identical duplicates.

If the cap is reached partway through a night, the next cursor remains on that
night. The next run relists that one night, skips newly receipted selections, and
takes the next unfinished images. If the whole night was examined, the cursor
moves to the preceding night.

## Durable progress and failures

The cursor is stored beside the selected results database in a small v20 state
file. It records the resolved archive identity and next backfill night. A state
file for a different archive is rejected rather than silently reused.

Dry runs read state but never download, analyse, create outputs, or advance the
cursor. Real runs update the cursor atomically only after every selected image
has either an earlier receipt or a new v20 receipt. An operational download or
solver failure without a receipt leaves the cursor unchanged, so unfinished
work cannot be skipped. A v20 scientific failure that records a receipt counts
as finished. Photometry-stage failure does not roll the cursor back because the
per-image solver receipts are already durable and the derived stages can be
regenerated from the database.

The existing pipeline lock covers discovery, download, solver execution, state
advancement, and derived products. Summary JSON and logs record the cap, nights
listed, cursor before and after, selected images, reused downloads, downloads,
receipt skips, attempts, successes, and solver failures. V20 does not compute or
claim a complete remote-backlog count.

## V19 products retained by v20

After bounded image processing, v20 runs the same five stages as v19 in the same
order: stellar light curves, nightly extinction, variable-star time series,
planet photometry, and planet-only empirical extinction. The v19 defaults and
output schemas remain unchanged. V20 changes orchestration and version identity,
not the underlying scientific algorithms or numerical thresholds.

## Tests and evidence

Tests use controlled nightly listings and temporary SQLite databases to prove:

1. every MMTO adapter request spans exactly one observing night;
2. discovery stops as soon as the image cap is filled;
3. the default cap is 40 and non-positive caps are rejected;
4. receipts of any solver version, including failures, suppress repeat analysis;
5. downloaded files without receipts are selected and reused;
6. current-night work has priority over the backward cursor;
7. a partial-night cap retains that night, while a fully scanned night advances;
8. dry runs and acquisition or solver failures before receipt completion do
   not advance state;
9. archive-identity mismatch fails closed;
10. a post-download duplicate digest is not sent to go20;
11. all v19 derived stages and variable-star controls remain present; and
12. frozen v19 files remain byte-identical.

Verification includes the focused v20 tests, v20 package tests, the complete root
suite, the required historical demo, a v20 demo, manifest checks, shell syntax,
and a dry run whose output shows bounded one-night-at-a-time discovery.
