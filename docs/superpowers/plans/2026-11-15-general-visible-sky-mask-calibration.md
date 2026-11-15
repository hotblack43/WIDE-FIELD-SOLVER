# General Visible-Sky Mask Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalise v24's approved MMTO detector-obstruction mask into a safe proposal, review, approval, registry, assignment, and automatic-resolution workflow for any supported fixed all-sky camera, then reproduce the MMTO proposal from a sealed cold start with held-out dates.

**Architecture:** Keep the existing temporal-consensus numerical method and runtime mask application unchanged. Add focused v24 calibration-lifecycle and registry modules, retain the current MMTO module as a compatibility facade, make downloader integration opt-in, and route both generic `go24.sh` and the MMTO pipeline through the generic resolver. Cold-start proposal and reference evaluation are separate commands so the approved MMTO mask cannot enter generation before the proposal inventory is sealed.

**Tech Stack:** Python 3.12, Bash, `unittest`, NumPy, SciPy, Pillow, Astropy, SQLite, append-only JSONL with `fcntl`, `uv` locked environments.

**Spec:** `docs/superpowers/specs/2026-11-15-general-visible-sky-mask-calibration-design.md`

## Global Constraints

- Preserve `v0.1.0`, every frozen runtime through v23, the historical examples, and all existing user changes.
- Do not delete, overwrite, rename away, or hide working code; retain `scripts/mmto_camera_installations.py` as a compatible public facade.
- Keep `v24/data/sky_masks/mmto_installation_2026a.png` and `.json` byte-for-byte unchanged.
- Keep the generic no-mask numerical path unchanged and record `not_configured`.
- Never auto-approve a proposal or silently fall back from a configured mask to an unmasked solve.
- Observation dates and within-night ordering may select diverse calibration frames and predeclare held-out dates, but may not classify pixels or enter the blind solve.
- Bind existing and future images by source SHA-256; never infer an installation from observation date.
- A camera move, rotation, crop, or replacement requires a new immutable installation ID and approved mask.
- Runtime masks remain binary detector-coordinate PNGs with `mask[y, x]`, top-left origin, exact shape, no resampling, and SHA-256 verification.
- Develop only in v24 while it remains active; do not modify v23 or earlier runtime files.
- Preserve unrelated dirty-worktree changes. Apply narrow patches and stage only files owned by the task.
- Before any commit, run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-unique-name` as required by `AGENTS.md`; if pre-existing unrelated changes prevent safe staging, leave the task uncommitted and report it.

## File Structure

- Create `v24/visible_sky_calibration.py`: camera-neutral proposal metadata, managed-download selection, deterministic held-out split, proposal revision, sealing, and approval finalisation.
- Create `v24/visible_sky_registry.py`: append-only calibration registration, activation, source assignment, layered lookup, and automatic resolution.
- Modify `v24/scripts/build_visible_sky_mask.py`: preserve existing numerical functions and imports, add camera-neutral CLI subcommands backed by the two focused modules.
- Modify `scripts/mmto_camera_installations.py`: compatibility facade over the generic v24 registry/assignment API; keep existing names and schemas readable.
- Modify `allsky_download/cli.py`: opt-in calibration-registry and assignment options after verified download; unchanged behaviour without them.
- Modify `v24/run.sh` and `v24/analyse_image.py`: accept automatic registry/assignment resolution in addition to the existing explicit manifest pair.
- Modify `scripts/run_mmto_photometry_pipeline_v24.py`: use bundled and user registry layers while preserving MMTO fail-closed constants, mask identity, receipt rules, and all unrelated current edits.
- Create `v24/data/sky_masks/registry.jsonl`: bundled read-only record for the existing MMTO calibration.
- Create `v24/scripts/replay_visible_sky_cold_start.py`: isolated `propose` and later `evaluate` commands with a sealed artifact inventory.
- Create `v24/test_visible_sky_calibration.py`, `v24/test_visible_sky_registry.py`, and `v24/test_visible_sky_cold_start.py`; extend existing builder, launcher, downloader, MMTO-assignment, pipeline, and boundary tests rather than replacing them.
- Modify `v24/README.md`, `README.md`, `docs/FEATURE_STATUS.md`, `docs/VERSIONS.md`, `v24/data/sky_masks/README.md`, and `v24/scripts/update_v24_manifest.py` after behaviour is verified.

## Review Focus

- Mixed detector signatures in one proposal must fail before writing an output directory; pinned in Task 2.
- A truncated or conflicting JSONL registry under concurrent access must fail closed without losing prior records; pinned in Task 4.
- Changing an active installation must not reassign any previously downloaded source checksum; pinned in Tasks 4 and 6.
- An interrupted download/assignment sequence must preserve the verified original as explicitly unassigned and return failure; pinned in Task 6.
- Missing, moved, corrupt, or checksum-mismatched raw files selected from the download manifest must fail with the exact source record and never be skipped silently; pinned in Task 2.

---

### Task 1: Repair the existing clean-checkout runtime-boundary failure

**Files:**
- Modify: `docs/v12-runtime.json`
- Modify: `test_v13_boundary.py`
- Add to tracked inventory without changing its bytes: `v23/examples/mmto/WCS_FOUND/2026_09_19__02_20_01_WCS.fits.bz2`
- Modify: `test_v23_runtime_boundary.py`
- Test: `test_v13_boundary.py`
- Test: `test_v23_runtime_boundary.py`

**Interfaces:**
- Consumes: existing `docs/v12-runtime.json`, `docs/v23-runtime.json`, and tracked-file inventories.
- Produces: clean-checkout boundary checks that cover source/runtime files but never require generated `__pycache__/*.pyc` files or an untracked absent example.

- [ ] **Step 1: Reproduce and isolate the two current CI failures without changing files**

Run the exact failing boundary tests and compare each recorded manifest path with `git ls-files` and filesystem state. Record whether each bad path originated in a generator, an accidentally generated cache, or an omitted tracked artifact.

- [ ] **Step 2: Add the smallest failing regression for generated cache exclusion and exact tracked coverage**

The regression asserts that runtime manifests contain no path component named `__pycache__`, no `.pyc` suffix, and exactly the intended tracked runtime inventory.

- [ ] **Step 3: Run the focused tests and verify the new regression fails for the observed reason**

Run: `uv run --frozen python -m unittest -v test_v13_boundary test_v23_runtime_boundary`

Expected: FAIL only on the recorded cache/example mismatch before the fix.

- [ ] **Step 4: Correct the two frozen-boundary metadata inventories, not the missing-file symptom**

Rebuild `docs/v12-runtime.json` from the exact tracked v12 package plus its
protected launchers, excluding `.venv`, caches, and generated bytecode. Preserve
the existing v23 manifest and its recorded WCS example: verify the local file's
SHA-256 is the already recorded
`3de98e39ddb0652c405d895a7bd8b52ca2cbcbcdb00b363debb78421344e9ad9`, then add
that exact existing file to the tracked inventory. Make both boundary tests
derive expected coverage from `git ls-files` only, never `--others`, and retain
digest equality. Do not manufacture `.pyc` files, regenerate or alter a frozen
runtime source, remove the expected v23 example, or relax equality checks.

- [ ] **Step 5: Regenerate only the affected manifest files and inspect their diff**

Confirm no frozen runtime source file changed and no unrelated user edit was overwritten.

- [ ] **Step 6: Run the focused boundary tests**

Run: `uv run --frozen python -m unittest -v test_v13_boundary test_v23_runtime_boundary`

Expected: PASS with no missing-file errors and no weakened runtime coverage.

- [ ] **Step 7: Checkpoint safely**

Run the repository-required root suite and demo before staging exact Task 1 files. Commit only if the worktree can be staged without unrelated changes; otherwise retain the verified diff uncommitted.

### Task 2: Add camera-neutral proposal metadata and managed-source selection

**Files:**
- Create: `v24/visible_sky_calibration.py`
- Create: `v24/test_visible_sky_calibration.py`
- Modify: `v24/scripts/build_visible_sky_mask.py`
- Modify: `v24/test_visible_sky_mask_builder.py`

**Interfaces:**
- Produces: `CalibrationSource`, `DetectorSignature`, and `CalibrationSplit` frozen dataclasses.
- Produces: `verified_sources_from_manifest(manifest_path: Path, archive_root: Path, source_id: str, camera_id: str) -> tuple[CalibrationSource, ...]`.
- Produces: `detector_signature(path: Path, *, orientation: str) -> DetectorSignature` using the v24 scientific loader.
- Produces: `partition_dates(sources: Sequence[CalibrationSource], *, holdout_modulus: int = 5, holdout_remainder: int = 0) -> CalibrationSplit`.
- Produces: `draft_filename(installation_id: str) -> str` with no MMTO default.
- Consumes: existing `select_representative_sources`, `load_native_luminance`, `accumulate_temporal_evidence`, `propose_visible_sky`, and `write_proposal` numerical behaviour.

- [ ] **Step 1: Write failing tests for generic identifiers and exact managed-download selection**

Tests create a temporary `downloads` table containing verified/unverified, missing, corrupt, wrong-source, and wrong-camera rows. Assert only verified matching files are returned, every selected file is size/hash checked, and errors name the offending record.

- [ ] **Step 2: Write failing tests for mixed detector signatures**

Create FITS fixtures differing individually in shape, plane layout, instrument, and declared orientation. Assert proposal preparation fails before creating its output directory.

- [ ] **Step 3: Write failing tests for deterministic date splitting**

Assert every fifth sorted observing date is held out, at least one fifth of dates are held out, no date appears in both sets, and representative early/middle/late cycling occurs only inside calibration dates.

- [ ] **Step 4: Run the new and existing builder tests to verify failure**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_calibration test_visible_sky_mask_builder`

Expected: FAIL because the generic types/functions and CLI metadata do not exist.

- [ ] **Step 5: Implement the dataclasses and selection functions**

Use read-only SQLite URI access, explicit path containment under `archive_root`, existing SHA-256 values plus fresh file verification, and the v24 loader's decoded provenance for signature comparison.

- [ ] **Step 6: Generalise the proposal CLI without removing legacy `--sources`**

Add explicit `--source`, `--camera`, `--installation-id`, and `--orientation`; add the mutually exclusive managed `--download-manifest`/`--archive-root` route. Replace the hardcoded draft filename and draft ID with safe installation-derived values while preserving existing numerical functions and compatibility imports.

- [ ] **Step 7: Run the focused tests**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_calibration test_visible_sky_mask_builder`

Expected: PASS, including the existing ten builder tests.

- [ ] **Step 8: Checkpoint safely**

Run required verification and stage only Task 2 files if a safe commit is possible.

### Task 3: Add immutable proposal revision and explicit approval

**Files:**
- Modify: `v24/visible_sky_calibration.py`
- Modify: `v24/scripts/build_visible_sky_mask.py`
- Modify: `v24/test_visible_sky_calibration.py`
- Modify: `v24/test_visible_sky_mask_builder.py`

**Interfaces:**
- Produces: `revise_proposal(parent_selection: Path, edited_mask: Path, output: Path) -> Path` returning the new `selection.json`.
- Produces: `approve_proposal(proposal_selection: Path, calibration_root: Path, *, reviewed_draft_sha256: str, mask_id: str, approved_by: str, safety_margin_pixels: int) -> Path` returning the approved manifest path.
- Preserves: `finalize_approved_mask(...)` as an importable compatibility name from `v24/scripts/build_visible_sky_mask.py`.

- [ ] **Step 1: Write failing tests for revision immutability and provenance**

Assert `revise_proposal` refuses an existing output, rejects non-binary/wrong-shape edits, regenerates both overlays, hashes every artifact, and records the parent selection and inventory hashes.

- [ ] **Step 2: Write failing tests for approval integrity**

Assert approval rejects the wrong reviewed-draft hash, modified proposal artifacts, missing identity fields, duplicate output IDs, negative safety margin, and a draft that was never sealed.

- [ ] **Step 3: Run tests and verify failure**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_calibration test_visible_sky_mask_builder`

Expected: FAIL because revision/approval commands do not exist.

- [ ] **Step 4: Implement revision as a new child proposal**

Never edit the parent directory. Reuse the original temporal reference, regenerate normal/inverted overlays, write a new immutable selection record, and fsync before returning.

- [ ] **Step 5: Implement approval finalisation**

Move the existing five-pixel erosion implementation behind `approve_proposal`, write PNG and JSON to a new installation subdirectory, validate the result with `VisibleSkyMask.load`, and leave registry activation to Task 4.

- [ ] **Step 6: Add `revise` and `approve` CLI subcommands**

Keep `propose` review-only. Make every destination explicit and refuse overwrite.

- [ ] **Step 7: Run focused tests**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_calibration test_visible_sky_mask_builder test_point_star_visible_sky`

Expected: PASS.

- [ ] **Step 8: Checkpoint safely**

Run required verification and stage only Task 3 files if safe.

### Task 4: Add layered calibration registry and separate activation

**Files:**
- Create: `v24/visible_sky_registry.py`
- Create: `v24/test_visible_sky_registry.py`
- Create: `v24/data/sky_masks/registry.jsonl`
- Modify: `v24/scripts/build_visible_sky_mask.py`
- Modify: `v24/data/sky_masks/README.md`

**Interfaces:**
- Produces: `load_registry(paths: Sequence[Path]) -> tuple[dict[str, object], ...]`.
- Produces: `register_calibration(registry_path: Path, manifest_path: Path, *, source_id: str, camera_id: str) -> dict[str, object]`.
- Produces: `activate_installation(registry_path: Path, *, source_id: str, camera_id: str, installation_id: str) -> dict[str, object]`.
- Produces: `active_installation(registry_paths: Sequence[Path], *, source_id: str, camera_id: str) -> dict[str, object] | None`.
- Consumes: approved manifest paths from Task 3.

- [ ] **Step 1: Write failing tests for append-only registration and layered lookup**

Assert identical registration is idempotent; conflicting installation ID, mask ID, manifest hash, or source/camera mapping is fatal across bundled and user registry layers.

- [ ] **Step 2: Write failing tests for truncation and concurrent appends**

Assert a malformed/truncated JSONL line fails closed with its line number, two concurrent identical registrations yield one logical record, and a rejected append preserves every prior byte.

- [ ] **Step 3: Write failing tests for separate activation**

Assert approval/registration alone creates no active installation; activation appends a distinct record; changing active installation leaves earlier activation history intact; missing/unapproved targets are rejected.

- [ ] **Step 4: Run tests and verify failure**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_registry`

Expected: FAIL because the registry module does not exist.

- [ ] **Step 5: Implement locked, fsynced JSONL operations**

Use `fcntl.flock`, parse and validate the complete existing file before append, append one canonical JSON line, flush and fsync, and release the lock. Resolve relative manifest paths relative to their registry file.

- [ ] **Step 6: Add the exact bundled MMTO registry record**

Generate it from the existing immutable MMTO manifest. Verify before and after SHA-256 values of `mmto_installation_2026a.png` and `.json` are identical.

- [ ] **Step 7: Wire approval registration and `activate` CLI**

Approval calls `register_calibration` only. `activate` is a separate subcommand with explicit source, camera, and installation.

- [ ] **Step 8: Run focused tests**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_registry test_visible_sky_calibration test_point_star_visible_sky`

Expected: PASS.

- [ ] **Step 9: Checkpoint safely**

Run required verification and stage only Task 4 files if safe.

### Task 5: Generalise immutable source assignments and preserve the MMTO facade

**Files:**
- Modify: `v24/visible_sky_registry.py`
- Modify: `v24/test_visible_sky_registry.py`
- Modify: `scripts/mmto_camera_installations.py`
- Modify: `test_mmto_camera_installations.py`

**Interfaces:**
- Produces: `assign_source(assignments_path: Path, source: Path, source_sha256: str, *, source_id: str, camera_id: str, registry_paths: Sequence[Path], installation_id: str, orientation: str) -> dict[str, object]`.
- Produces: `assignment_for_source(assignments_path: Path, source_sha256: str) -> dict[str, object] | None`.
- Produces: `resolve_source_calibration(registry_paths: Sequence[Path], assignments_path: Path, source_sha256: str) -> dict[str, object]`.
- Preserves: `scripts.mmto_camera_installations.assign_source(...)`, `assignment_for_source(...)`, and their current call signatures as wrappers.

- [ ] **Step 1: Write failing generic assignment tests**

Cover exact checksum verification, source/camera identity, instrument with missing serial compatibility, different explicit serial rejection, shape/layout/orientation mismatch, idempotence, and conflicting reassignment.

- [ ] **Step 2: Write failing active-change history test**

Assign an image to installation A, activate B, and assert resolution of the original checksum remains A while a later image may be assigned B.

- [ ] **Step 3: Run generic and existing MMTO tests to verify failure**

Run: `uv run --frozen python -m unittest -v test_mmto_camera_installations` and `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_registry`

Expected: generic tests FAIL; existing MMTO tests remain a compatibility baseline.

- [ ] **Step 4: Implement assignment and resolution in the generic module**

Reuse `VisibleSkyMask.load` and v24 decoded provenance; store registry/manifest/mask hashes and the source/camera IDs in canonical append-only records.

- [ ] **Step 5: Convert the MMTO module into a compatibility facade**

Keep its dataclass and existing functions importable, delegate to generic functions, and read existing `mmto-camera-installation-assignments.jsonl` records without rewriting them.

- [ ] **Step 6: Run focused tests**

Run both commands from Step 3.

Expected: PASS with no change to current MMTO assignment semantics.

- [ ] **Step 7: Checkpoint safely**

Run required verification and stage only Task 5 files if safe.

### Task 6: Assign future managed downloads without changing default downloader behaviour

**Files:**
- Modify: `allsky_download/cli.py`
- Modify: `allsky_download/manifest.py`
- Modify: `tests/test_allsky_manifest.py`
- Modify: `tests/test_allsky_cli.py`
- Modify: `v24/test_visible_sky_registry.py`

**Interfaces:**
- Consumes: `active_installation` and `assign_source` from Task 5.
- Produces: opt-in CLI options `--calibration-registry`, `--installation-assignments`, and `--camera-orientation` that must be supplied together.
- Preserves: `Manifest.record_success(...)` and every existing invocation without calibration options.

- [ ] **Step 1: Write failing parser and unchanged-default tests**

Assert existing download commands parse and behave identically. Partial calibration option sets fail before network access.

- [ ] **Step 2: Write failing successful-ingest assignment test**

With an active fixture installation, download a valid FITS fixture, record it verified, then assert its source checksum is assigned before the command reports success.

- [ ] **Step 3: Write failing interrupted/invalid assignment tests**

Simulate no active installation, identity mismatch, and assignment append failure. Assert the raw file and verified download row remain, no solver job is enqueued for the configured path, the file is explicitly reported unassigned, and the command returns nonzero.

- [ ] **Step 4: Run downloader tests and verify failure**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_manifest` plus the downloader CLI test module.

Expected: FAIL only for the new opt-in behaviour.

- [ ] **Step 5: Implement conditional v24 assignment integration**

Import the v24 registry module only when calibration options are present. After `record_success`, resolve the active installation and append the assignment before printing `DOWNLOAD` or enqueuing configured processing. Preserve verified-but-unassigned evidence on failure.

Add nullable `installation_assignment_status`, `installation_id`, and
`installation_assignment_error` columns through an idempotent SQLite schema
migration. Record `assigned` only after the append-only assignment succeeds;
record `unassigned` plus the diagnostic when it fails.

- [ ] **Step 6: Add bounded `assign-existing` CLI support**

Require source, camera, absolute `--limit`, registry, assignments path, and explicit apply flag. Dry-run prints source checksums; apply validates each and appends without altering existing assignments.

- [ ] **Step 7: Run downloader and registry tests**

Expected: PASS, including all pre-v24 downloader tests without calibration options.

- [ ] **Step 8: Checkpoint safely**

Run required verification and stage only Task 6 files if safe.

### Task 7: Add automatic calibration resolution to the generic v24 launcher

**Files:**
- Modify: `v24/run.sh`
- Modify: `v24/analyse_image.py`
- Create: `v24/test_visible_sky_launcher_resolution.py`
- Modify: `v24/test_point_star_visible_sky.py`
- Modify: `v24/test_visible_sky_mask_integration.py`

**Interfaces:**
- Consumes: `resolve_source_calibration(...)` from Task 5.
- Produces: `--calibration-registry PATH`, repeatable `--bundled-calibration-registry PATH`, `--installation-assignments PATH`, and `--allow-unconfigured-visible-sky` automatic-resolution options.
- Preserves: explicit `--visible-sky-mask-manifest` plus `--camera-installation-id` and the no-mask path.

- [ ] **Step 1: Write failing parser exclusivity tests**

Assert explicit and automatic modes cannot be combined, partial automatic
option sets fail, and ordinary unmanaged local no-mask invocation remains
valid. `--allow-unconfigured-visible-sky` is valid only with a complete
automatic-resolution option set and permits fallback only for a missing source
assignment; corrupt, conflicting, or mismatched configuration remains fatal.

- [ ] **Step 2: Write failing resolution tests**

Given a source checksum assignment, assert the solver passes the resolved approved manifest/installation into the existing detection path and records source ID, camera ID, registry hash, assignment evidence, manifest hash, and mask hash.

- [ ] **Step 3: Write failing unknown/ambiguous resolution tests**

Assert missing assignment, conflicting layered registry records, missing manifest, and checksum mismatch fail before output creation and never fall back to `not_configured`.

- [ ] **Step 4: Run focused tests and verify failure**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_visible_sky test_visible_sky_mask_integration` plus the parser test module.

Parser module: `test_visible_sky_launcher_resolution`.

- [ ] **Step 5: Implement resolution before `prepare_output`**

Hash the input, resolve the assignment and manifest, then pass the existing explicit pair into `run`. Do not change `VisibleSkyMask.combine` or detection mathematics.

- [ ] **Step 6: Extend `v24/run.sh` option forwarding**

Retain all current options and help text; add automatic-resolution options without changing default result paths or launcher versions.

- [ ] **Step 7: Run focused tests and the existing v24 mask suite**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_visible_sky test_visible_sky_mask_builder test_visible_sky_calibration test_visible_sky_registry test_visible_sky_mask_integration`

Expected: PASS.

- [ ] **Step 8: Checkpoint safely**

Run required verification and stage only Task 7 files if safe.

### Task 8: Route MMTO production through the generic registry without changing receipts

**Files:**
- Modify: `scripts/run_mmto_photometry_pipeline_v24.py`
- Modify: `test_run_mmto_photometry_pipeline_v24.py`
- Modify: `scripts/mmto_camera_installations.py`
- Modify: `test_mmto_camera_installations.py`

**Interfaces:**
- Consumes: bundled `v24/data/sky_masks/registry.jsonl`, generic assignment/resolution APIs, and existing immutable MMTO mask IDs.
- Preserves: `MMTO_VISIBLE_SKY_MASK_MANIFEST`, `MMTO_CAMERA_INSTALLATION_ID`, `MMTO_VISIBLE_SKY_MASK_ID`, `_latest_completed_masked_v24_receipt`, and existing assignment JSONL readability.

- [ ] **Step 1: Write failing generic-routing tests while retaining all current pipeline tests**

Assert `_prepare_solver_run` resolves through the bundled registry and still emits the exact existing explicit manifest and installation arguments. Assert unassigned and non-MMTO-mask assignments remain fatal.

- [ ] **Step 2: Add migration compatibility tests**

Existing assignment records resolve idempotently; no database receipt or assignment file is rewritten; v23 receipts and successful existing masked v24 receipts retain current completed-work semantics.

- [ ] **Step 3: Run pipeline tests and verify only new expectations fail**

Run: `uv run --frozen python -m unittest -v test_mmto_camera_installations test_run_mmto_photometry_pipeline_v24`

- [ ] **Step 4: Replace MMTO-only assignment internals with generic calls**

Patch only calibration-related lines in the already modified pipeline. Preserve concurrent solver logging, receipt ordering, photometry-stage commands, figure requirements, and every unrelated working-tree edit.

- [ ] **Step 5: Verify immutable MMTO artifact hashes**

Run `sha256sum` on the approved MMTO PNG/JSON and compare with the pre-task values and bundled registry record.

- [ ] **Step 6: Run pipeline and assignment tests**

Expected: PASS with the same solver command mask ID, installation ID, and receipt queries.

- [ ] **Step 7: Checkpoint safely**

Run required verification and stage only Task 8 files if safe.

### Task 9: Implement and run the sealed cold-start MMTO replay

**Files:**
- Create: `v24/scripts/replay_visible_sky_cold_start.py`
- Create: `v24/test_visible_sky_cold_start.py`
- Produce: a new preserved result directory under `results/` with a unique cold-start name

**Interfaces:**
- Produces: `propose` subcommand accepting only raw/download inputs, split rule, installation metadata, and output directory; it has no approved-reference option.
- Produces: `evaluate` subcommand accepting a sealed proposal inventory, held-out source list, and explicit approved reference manifest.
- Produces: `proposal-seal.json`, `date-split.json`, `held-out/` overlays,
  `comparison.json`, `comparison.csv`, `cold_start_boundary_review.png`,
  `cold_start_boundary_review_inverted.png`, `approved_comparison.png`, and
  detection audit summaries.
- Consumes: Task 2 selection, Task 3 sealing, and the existing approved MMTO mask only in `evaluate`.

- [ ] **Step 1: Write failing isolation tests**

Assert the `propose` parser rejects approved-mask/reference options, output must be new, no path under `v24/data/sky_masks` is opened, and the seal inventories every proposal artifact before evaluation.

- [ ] **Step 2: Write failing deterministic split and leakage tests**

Assert calibration and held-out dates are disjoint, every fifth sorted date is held out, at least one fifth are held out, and held-out paths cannot enter proposal source records.

- [ ] **Step 3: Write failing evaluation tests**

On synthetic masks, assert exact pixel agreement, IoU, false-visible, false-excluded, and boundary-distance metrics; reject any proposal whose current artifact hash differs from the seal.

- [ ] **Step 4: Run cold-start tests and verify failure**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_cold_start`

Expected: FAIL because the replay tool does not exist.

- [ ] **Step 5: Implement separate `propose` and `evaluate` commands**

Process selected calibration frames with the existing temporal method. Process held-out frames sequentially so the 3,194-file archive is inventoried and validated without constructing a 3,194-frame cube.

- [ ] **Step 6: Run synthetic cold-start tests**

Expected: PASS.

- [ ] **Step 7: Run the real isolated MMTO proposal**

Use `/media/pth/Sandisk8TB/pth13-offload/WIDE-FIELD-SOLVER/raw_allsky_samples/manifest.sqlite` and its archive root. Write a new result directory; do not copy or expose the approved mask path to `propose`.

- [ ] **Step 8: Inspect and seal proposal outputs before reveal**

Record the proposal seal hash and inspect the normal and inverted boundary overlays. Do not tune thresholds or edit the mask after viewing the approved reference.

- [ ] **Step 9: Run held-out evaluation and then reveal the approved reference**

Generate held-out stability/detection evidence first. Then pass `v24/data/sky_masks/mmto_installation_2026a.json` to `evaluate` and save comparison metrics/figures.

- [ ] **Step 10: Ask Peter to review the cold-start normal and inverted overlays**

No cold-start proposal becomes approved automatically. If correction is requested, use Task 3's immutable `revise` workflow and preserve the original cold-start proposal.

- [ ] **Step 11: Fix conservative regression thresholds only after approval**

Record observed sealed metrics and documented margins; do not weaken them later to conceal a failure.

- [ ] **Step 12: Checkpoint safely**

Preserve every user-facing cold-start figure and evidence file. Stage only code/tests, not large generated results, unless Peter explicitly requests result tracking.

### Task 10: Documentation, manifest, and full verification

**Files:**
- Modify: `v24/README.md`
- Modify: `README.md`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `docs/VERSIONS.md`
- Modify: `v24/data/sky_masks/README.md`
- Modify: `v24/scripts/update_v24_manifest.py`
- Modify: `v24/SOURCE_MANIFEST.json` using the updater
- Modify: `.github/workflows/tests.yml` to exercise the packaged/current runtime without removing preserved baseline jobs
- Create: `test_v24_documentation.py`

**Interfaces:**
- Consumes: all completed commands, schemas, and cold-start evidence.
- Produces: one consistent public workflow and a deliberate v24 source manifest.

- [ ] **Step 1: Write or extend documentation assertions before editing prose**

Assert README commands name v24 consistently, describe draft versus approved masks, retain the no-mask path, and do not claim cross-camera validation from MMTO replay.

- [ ] **Step 2: Update user documentation**

Document proposal, revision, approval, activation, future-download assignment, bounded historical assignment, automatic resolution, camera-reset rules, and cold-start limitations. Correct the existing v23 launcher references in `v24/README.md`.

- [ ] **Step 3: Update feature status factually**

Distinguish implemented generic machinery, MMTO cold-start evidence, and the still-missing real non-MMTO validation.

- [ ] **Step 4: Extend CI without deleting preserved checks**

Retain root/v4/v5 jobs and add focused v24 calibration tests plus a v24 demo or separately bounded current-runtime job. Keep failures visible.

- [ ] **Step 5: Update the v24 manifest change list and regenerate hashes**

Run: `uv run --project v24 --frozen python v24/scripts/update_v24_manifest.py`

Inspect every manifest diff and confirm no cache, result, raw-image, or unrelated path entered the runtime inventory.

- [ ] **Step 6: Run focused calibration verification**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_mask_builder test_visible_sky_calibration test_visible_sky_registry test_point_star_visible_sky test_visible_sky_mask_integration test_visible_sky_cold_start`

Expected: PASS.

- [ ] **Step 7: Run complete v24 verification**

Run: `cd v24 && uv run --frozen python -m unittest discover -v`

Expected: PASS with zero failures/errors.

Run: `./v24/demo.sh --output v24/results/general-mask-final-<unique>`

Expected: baseline PASS and preserved user-facing report/figures.

- [ ] **Step 8: Run complete root verification required by the repository**

Run: `uv run --frozen python -m unittest discover -v`

Expected: PASS with zero failures/errors.

Run: `./demo.sh --output results/check-unique-name`

Expected: baseline PASS.

- [ ] **Step 9: Run documentation verification**

Run: `uvx --with mkdocs-material==9.7.7 mkdocs==1.6.1 build --strict`

Expected: exit 0 with no warnings promoted to errors.

- [ ] **Step 10: Verify preservation boundaries**

Compare pre/post hashes for approved MMTO PNG/JSON, run v23/v24 boundary tests, inspect `git diff --stat` and `git status --short`, and confirm no existing working code, result, raw image, launcher, or frozen runtime disappeared.

- [ ] **Step 11: Final review and safe handoff**

Use `superpowers:requesting-code-review`, address findings through `superpowers:receiving-code-review`, rerun verification, and present figures first: cold-start normal/inverted overlays, approved-boundary comparison, held-out examples, and the fresh v24 demo report.
