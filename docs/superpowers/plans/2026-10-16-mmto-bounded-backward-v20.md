# MMTO Bounded Backward V20 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent v20 MMTO workflow that retains v19 products while selecting, downloading, and analysing at most 40 previously unprocessed images per run through bounded one-night remote requests and a durable backward cursor.

**Architecture:** Freeze v19, clone its self-contained solver as v20, and replace the v19 local-only queue with a v20 orchestrator that lists one MMTO night per request. The orchestrator combines current-night priority with an atomic results-local cursor, uses any existing solver receipt as the completion key, and runs the unchanged v19 derived-product stages after bounded processing.

**Tech Stack:** Python 3.12, SQLite, pathlib, argparse, existing `allsky_download` MMTO adapter/manifest/solar/cadence modules, Bash launchers, `unittest`, uv.

**Spec:** `docs/superpowers/specs/2026-10-16-mmto-bounded-backward-v20-design.md`

## Global Constraints

- Preserve v19 and every earlier runtime byte for byte after freezing v19 at the v20 boundary.
- Never list more than one MMTO observing night in one adapter request.
- Default `--max-images` is exactly `40`, and the cap applies before downloads and solver invocations.
- Default `--oldest-night` is exactly `2026-06-30`; no earlier directory is listed unless the operator explicitly changes it.
- Any solver receipt for a source SHA-256 counts as processed, regardless of version or exit code.
- A downloaded image without a solver receipt remains eligible and is reused without downloading.
- Advance the durable cursor only after every selected item has a receipt; dry runs and operational failures leave it unchanged.
- Preserve the v19 variable-star catalogue, scientific algorithms, numerical thresholds, five derived stages, and stage controls.
- Keep raw FITS `.bz2` inputs; never substitute rendered previews.
- Do not modify historical example or reference products or relax regression thresholds.

## Review Focus

- A nightly listing containing more unfinished cadence images than the cap must retain the same cursor night without losing overflow.
- A verified manifest row whose local file disappeared must be redownloaded, not treated as reusable or finished without a receipt.
- A newly downloaded URL whose digest already has an old receipt must skip solver execution while still allowing safe cursor progress.
- A crash or exception before all selected images receive receipts must leave the pre-run cursor durable.
- The current-night priority scan must not duplicate the cursor scan when both point to the same observing night.

---

### Task 1: Freeze V19 and Establish the Independent V20 Runtime

**Files:**
- Create: `docs/v19-runtime.json`
- Create: `v20/` from tracked `v19/` sources without caches or generated outputs
- Create: `go20.sh`
- Create: `go_v0.20.0.sh`
- Create: `test_v20_runtime_boundary.py`
- Modify in v20 only: version metadata, launchers, documentation, manifest updater, and `SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: frozen tracked v19 package and its v19 source manifest.
- Produces: solver version `0.20.0`, launchers `go20.sh` and `go_v0.20.0.sh`, self-contained `v20/`, and a v19 preservation digest file.

- [ ] **Step 1: Write failing runtime-boundary tests**

  Test executable v20 launchers reporting `0.20.0`, complete v20 manifest ownership based on `../docs/v19-runtime.json`, and exact hashes for every frozen v19 file.

- [ ] **Step 2: Run the focused test and verify the missing-v20 failure**

  Run: `uv run --frozen python -m unittest -v test_v20_runtime_boundary`

  Expected: FAIL because v20 and its launchers do not exist.

- [ ] **Step 3: Freeze v19 and clone/update the v20 runtime**

  Generate `docs/v19-runtime.json` deterministically, copy only tracked v19 files, set active version identity to `0.20.0`, create v20 launchers, and adapt the manifest updater to v20 with the v19 boundary as parent.

- [ ] **Step 4: Refresh the v20 source manifest**

  Run: `uv run --project v20 --frozen python v20/scripts/update_v20_manifest.py`

  Expected: v20 manifest covers every owned source/data file except itself and names the frozen v19 boundary.

- [ ] **Step 5: Run the focused boundary test**

  Run: `uv run --frozen python -m unittest -v test_v20_runtime_boundary`

  Expected: PASS.

### Task 2: Add Bounded One-Night Discovery and Cursor Semantics

**Files:**
- Create: `scripts/run_mmto_photometry_pipeline_v20.py`
- Create: `test_run_mmto_photometry_pipeline_v20.py`

**Interfaces:**
- Consumes: `MmtoAdapter.list_candidates`, `site_night_range`, `filter_by_solar_altitude`, `select_candidates`, manifest rows, and `runs.source_sha256` receipts.
- Produces: `build_acquisition_plan(...) -> AcquisitionPlan`, atomic cursor state, and a selected tuple capped by `max_images`.

- [ ] **Step 1: Write failing selection tests**

  Add behavior tests for one-night calls, default/validated cap 40, early stop, any-version receipt suppression, local unreceipted reuse, current-night priority, partial-night cursor retention, complete-night cursor advancement, archive mismatch, and no dry-run state write.

- [ ] **Step 2: Run focused tests and verify feature-missing failures**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v20`

  Expected: FAIL because the v20 pipeline does not exist.

- [ ] **Step 3: Implement the minimal discovery/state layer**

  Add typed plan/image/state records, receipt and manifest indexes, one-night newest-first discovery, current-night plus cursor ordering without duplication, cap validation, atomic JSON state writes, and exact summary fields from the spec.

- [ ] **Step 4: Run focused tests**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v20`

  Expected: selection/state tests PASS.

### Task 3: Integrate Download, V20 Solving, and V19 Product Stages

**Files:**
- Modify: `scripts/run_mmto_photometry_pipeline_v20.py`
- Modify: `test_run_mmto_photometry_pipeline_v20.py`
- Create: `go_mmto_photometry_v20.sh`

**Interfaces:**
- Consumes: Task 2 acquisition plan and cursor proposal; Task 1 `go20.sh`; v19 `_stage_commands` behavior.
- Produces: one-command bounded v20 workflow, receipt-safe processing, atomic progress, and all five v19 derived-product stages.

- [ ] **Step 1: Write failing orchestration tests**

  Test verified-file reuse, missing/corrupt redownload, post-download duplicate-receipt skip, no cursor advancement on download/receipt failure, cursor advancement after all receipts, v20 receipt validation, unchanged v19 stage order/arguments, portable launcher help, summaries, and figure listing.

- [ ] **Step 2: Run focused tests and verify orchestration failures**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v20`

  Expected: FAIL only for the unimplemented orchestration behaviors.

- [ ] **Step 3: Implement download and processing orchestration**

  Hold the pipeline lock across discovery and work; reuse verified downloads; download missing selections atomically through the manifest; recheck any receipt after hashing; run `go20.sh` only when needed; require a v20 receipt after invocation; commit cursor only after the batch is receipt-complete; then invoke the five v19 product stages unchanged.

- [ ] **Step 4: Run focused v20 tests**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v20 test_v20_runtime_boundary`

  Expected: PASS.

### Task 4: Document, Manifest, and Verify V20

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/VERSIONS.md`
- Modify: `docs/MMTO_PHOTOMETRY_PIPELINE.md`
- Modify in v20 only: `README.md`, `HANDOFF.md`, `docs/FEATURE_STATUS.md`, `AGENTS.md`, `SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: implemented v20 CLI, state location, summary schema, and tests.
- Produces: operator instructions and a manifest-complete, regression-verified v20 runtime.

- [ ] **Step 1: Document exact commands and operational semantics**

  Document `./go_mmto_photometry_v20.sh --dry-run`, the default cap, `--max-images`, any-receipt skip policy, one-night remote requests, cursor location/advance rules, retained v19 products, and recovery behavior without changing frozen v19 docs.

- [ ] **Step 2: Refresh and validate the v20 manifest**

  Run: `uv run --project v20 --frozen python v20/scripts/update_v20_manifest.py`

  Expected: deterministic v20 manifest validation succeeds.

- [ ] **Step 3: Run focused and package verification**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v20 test_v20_runtime_boundary`

  Run: `uv run --project v20 --frozen python -m unittest discover -v v20`

  Expected: PASS with no failures.

- [ ] **Step 4: Run repository-required verification**

  Run: `uv run --frozen python -m unittest discover -v`

  Run: `./demo.sh --output results/check-unique-name-v20`

  Expected: complete suite and preserved historical demo PASS without changing reference evidence.

- [ ] **Step 5: Run v20 smoke verification**

  Run: `./v20/demo.sh --output results/check-v20-milky-way`

  Run: `./go_mmto_photometry_v20.sh --help`

  Run: `bash -n go20.sh go_v0.20.0.sh go_mmto_photometry_v20.sh v20/run.sh`

  Expected: v20 demo passes, help exposes `--max-images 40`, and shell syntax is valid.

- [ ] **Step 6: Inspect the final diff without committing or publishing**

  Run: `git diff --check && git status --short && git diff --stat`

  Expected: only deliberate v20 additions, v19 freeze records, and current documentation changes appear; no preserved runtime bytes changed.
