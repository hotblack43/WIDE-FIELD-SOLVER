# V25 Automatic Visible-Sky Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one fail-closed zero-argument `go_visible_sky_v25.sh` command that performs bounded acquisition for supported uncalibrated public RAW cameras, discovers eligible managed populations, then validates, accepts, registers, and activates their masks without manual identity, path, or hash handling; retain `auto --config …` as an advanced override.

**Architecture:** Keep `visible_sky_operator.py` as a thin CLI and place automatic orchestration in a dedicated v25 module. Refactor the existing cold-start code only enough to reuse sealed proposal construction for the primary split and five deterministic calibration-date folds; keep gate evaluation pure, approval provenance explicit, and every registry mutation behind the final acceptance decision and a source/camera lock.

**Tech Stack:** Python 3.12, `unittest`, NumPy, Pillow, SciPy, SQLite-backed managed-source manifest, append-only JSONL calibration registry, Bash/uv v25 launcher.

**Spec:** `docs/superpowers/specs/2026-11-16-v25-automatic-visible-sky-setup-design.md`

## Global Constraints

- Preserve frozen v24 and `docs/v24-runtime.json` byte-for-byte.
- Keep existing manual `propose`, `revise`, `approve`, and `activate` behavior and CLI syntax unchanged.
- Use only checksum-verified native originals from the configured download manifest and archive root.
- Keep the primary held-out observing dates out of every primary and fold proposal.
- Fixed v25 gates are not configurable: 10 total dates; 8 calibration dates; 2 held-out dates; 20 held-out originals; visible fraction 0.10–0.95; held-out footprint IoU median 0.80 and minimum 0.50; 100 aggregate detections; boundary-intersection fraction 0.05; five fold comparisons with IoU 0.95, mean boundary distance 10 px, and p95 distance 24 px.
- Missing, Boolean, non-finite, or zero-denominator gate inputs fail closed.
- Automatic provenance must say `approval_mode: automated_validation` and `approved_by: wide-field-solver-v25-auto`; it must never claim visual approval.
- Use a content-addressed canonical acceptance record and mask ID `<installation>-auto-<masksha12>-<acceptancesha12>`.
- Serialize automatic runs per calibration-root/source/camera and refuse a different active installation unless `--replace-active` is explicit.
- Exit zero only when the configured installation is active; gate rejection exits one, usage/configuration exits two, and operational failure exits three.
- Preserve all inputs and generated evidence; never overwrite a prior run directory, production mask, receipt, or registry history.
- Do not change the accepted MMTO mask, activate an MMTO replacement in tests, or publish externally.
- Before any commit, run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/<unique-name>` as required by `AGENTS.md`; if either is red, do not commit.

## Review Focus

- Insufficient or degenerate data must produce a durable rejection receipt while leaving calibration-registry bytes unchanged; Task 1 and Task 4 pin this.
- Identical reruns must reuse the same content-addressed acceptance identity without conflicting manifests; Task 1, Task 3, and Task 4 pin this.
- Two automatic processes for one source/camera must not race registration or activation; Task 4 pins lock refusal before output mutation.
- A different active installation must remain active unless `--replace-active` is explicit and the new run passes every gate; Task 4 and Task 5 pin this.
- Interrupted or tampered proposal, fold, held-out, finalized-mask, or acceptance evidence must never reach registration; Task 2 and Task 4 pin each boundary.

---

### Task 1: Pure automatic gates and content-addressed identity

**Files:**
- Create: `v25/visible_sky_automatic.py`
- Create: `v25/test_visible_sky_automatic.py`

**Interfaces:**
- Consumes: gate values and artifact hashes supplied as plain mappings and sequences.
- Produces: `AUTOMATIC_ACCEPTANCE_SCHEMA`, `AUTOMATIC_ACCEPTANCE_THRESHOLDS`, `evaluate_automatic_gates(metrics: Mapping[str, object], fold_metrics: Sequence[Mapping[str, object]]) -> dict[str, object]`, `canonical_acceptance_payload(*, identity: Mapping[str, object], sources: Sequence[Mapping[str, object]], metrics: Mapping[str, object], fold_metrics: Sequence[Mapping[str, object]], artifact_sha256: Mapping[str, str], code_sha256: Mapping[str, str], finalized_mask_sha256: str) -> dict[str, object]`, `canonical_json_sha256(payload: Mapping[str, object]) -> str`, `automatic_mask_id(installation_id: str, mask_sha256: str, acceptance_sha256: str) -> str`, and `atomic_write_json(path: Path, payload: Mapping[str, object]) -> None`.

- [ ] **Step 1: Write failing gate tests**

Add tests named `test_exact_fixed_thresholds_pass_at_boundaries`, `test_each_gate_fails_independently`, and `test_boolean_missing_nonfinite_and_zero_denominator_values_fail_closed`. Assert the exact constants from Global Constraints, all five fold rows, explicit numerator/denominator fields for source-support fractions, and a stable ordered list of failed gate names.

- [ ] **Step 2: Run the gate tests and verify RED**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_automatic`

Expected: import failure because `visible_sky_automatic.py` does not exist.

- [ ] **Step 3: Implement pure gate evaluation**

Implement the constants and `evaluate_automatic_gates`. Return schema, immutable threshold values, one check row per gate with observed value/relation/limit/pass, `status` equal to `pass` or `fail`, and `failed_gates`. Require exactly five finite fold metric mappings.

- [ ] **Step 4: Write failing canonical-identity tests**

Add `test_acceptance_payload_is_path_and_time_independent`, `test_canonical_hash_is_order_independent`, `test_mask_id_binds_mask_and_acceptance_hashes`, and `test_atomic_json_never_leaves_partial_destination`. Include absolute-path and timestamp variants in run-local inputs and prove they are absent from the canonical payload.

- [ ] **Step 5: Implement canonical evidence helpers**

Implement canonical JSON with sorted keys and compact separators, strict lowercase SHA-256 validation, safe installation-ID validation through the existing identifier policy, deterministic mask ID construction, and sibling-temporary-file plus `os.replace` JSON publication.

- [ ] **Step 6: Run Task 1 tests and verify GREEN**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_automatic`

Expected: all Task 1 tests pass.

- [ ] **Step 7: Review checkpoint**

Inspect `git diff --check` and the Task 1 diff. Do not commit unless both repository-required pre-commit commands have also passed; otherwise retain the tested working-tree checkpoint.

### Task 2: Reusable sealed primary and fold proposals

**Files:**
- Modify: `v25/scripts/replay_visible_sky_cold_start.py`
- Modify: `v25/test_visible_sky_cold_start.py`
- Test: `v25/test_visible_sky_automatic.py`

**Interfaces:**
- Consumes: `Sequence[CalibrationSource]`, installation identity, orientation, and a new output directory.
- Produces: `create_sealed_proposal_from_sources(sources: Sequence[CalibrationSource], *, output: Path, source_id: str, camera_id: str, installation_id: str, orientation: str) -> Path`, `calibration_date_folds(sources: Sequence[CalibrationSource], *, fold_count: int = 5) -> tuple[tuple[CalibrationSource, ...], ...]`, and unchanged CLI behavior through `propose_command(args) -> Path`.

- [ ] **Step 1: Write failing refactor-preservation tests**

Add `test_source_helper_reproduces_cli_proposal_artifacts` and `test_primary_cli_still_holds_out_complete_dates_before_pixels`. Assert identical selected source hashes, detector signature, proposal audit, seal inventory, and output filenames for helper and CLI paths.

- [ ] **Step 2: Refactor proposal construction without numerical changes**

Extract `create_sealed_proposal_from_sources` from the existing `propose_command`; keep `verified_sources_from_manifest`, `partition_dates`, selected-frame loading, proposal generation, `date-split.json`, review images, and seal creation in the same order. Make the CLI call the helper.

- [ ] **Step 3: Run cold-start regression tests**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_cold_start`

Expected: all existing and new cold-start tests pass with the accepted MMTO thresholds unchanged.

- [ ] **Step 4: Write failing fold-isolation tests**

Add `test_five_folds_are_deterministic_and_omit_disjoint_calibration_dates`, `test_primary_holdout_dates_never_enter_any_fold`, `test_too_few_calibration_dates_fail_before_output`, and `test_fold_seal_detects_any_artifact_tampering`. Use deliberately shuffled `CalibrationSource` fixtures and assert date membership, not input order.

- [ ] **Step 5: Implement deterministic calibration folds**

Sort unique calibration dates, assign `index % 5`, and return five training populations each omitting its fold dates. Reject fewer than five unique calibration dates. Reuse `create_sealed_proposal_from_sources` for each immutable `fold-0` through `fold-4` directory; compare masks using the existing `comparison_metrics` function.

- [ ] **Step 6: Add held-out audit integrity tests**

Add tests proving changed held-out bytes, changed proposal-seal artifacts, missing detail rows, and non-prefix resumed JSONL each fail before a gate payload is produced.

- [ ] **Step 7: Run Task 2 suites and verify GREEN**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_cold_start test_visible_sky_automatic`

Expected: all tests pass.

- [ ] **Step 8: Review checkpoint**

Run `git diff --check`; inspect that only v25 cold-start code changed and that v24 hashes still match `docs/v24-runtime.json`. Commit only if the required full suite and root demo pass.

### Task 3: Explicit manual and automated approval provenance

**Files:**
- Modify: `v25/visible_sky_calibration.py`
- Modify: `v25/test_visible_sky_calibration.py`
- Modify: `v25/visible_sky_registry.py` only if validation must recognize the new provenance fields
- Modify: `v25/test_visible_sky_registry.py` only with the matching validation tests

**Interfaces:**
- Consumes: existing proposal path and approval arguments, plus `approval_mode: Literal["human_review", "automated_validation"] = "human_review"`, `automatic_acceptance_path: Path | None = None`, and `automatic_acceptance_sha256: str | None = None` on `approve_proposal`.
- Produces: unchanged manual manifests with explicit `approval_mode: human_review`; automated manifests with `approval_mode: automated_validation`, actor `wide-field-solver-v25-auto`, and a calibration-root-relative canonical acceptance path plus hash.

- [ ] **Step 1: Write failing backward-compatibility tests**

Add `test_manual_approval_defaults_to_human_review_without_cli_changes` and rerun the existing approval/registration tests. Assert no existing required argument changes and no v24 import or data dependency.

- [ ] **Step 2: Write failing automated-provenance tests**

Add `test_automated_approval_requires_exact_content_addressed_receipt`, `test_automated_actor_cannot_be_overridden`, `test_human_mode_rejects_automatic_receipt_arguments`, and `test_registry_revalidates_automated_receipt_hash_and_relative_path`.

- [ ] **Step 3: Implement approval-mode validation and serialization**

Extend `approve_proposal` with the exact interface above. Require the automated receipt to be within `calibration_root`, named `<sha256>.json`, and byte-matched; force the automated actor. Keep historical manifests without `approval_mode` readable and never rewrite them.

- [ ] **Step 4: Run calibration and registry suites**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_calibration test_visible_sky_registry`

Expected: all tests pass.

- [ ] **Step 5: Review checkpoint**

Run `git diff --check`; inspect manifest compatibility and append-only behavior. Commit only after the repository-required full suite and root demo pass.

### Task 4: Locked automatic workflow orchestration

**Files:**
- Create: `v25/visible_sky_auto_workflow.py`
- Create: `v25/test_visible_sky_auto_workflow.py`
- Modify: `v25/visible_sky_automatic.py`

**Interfaces:**
- Consumes: `AutomaticWorkflowConfig(source_id: str, camera_id: str, installation_id: str, orientation: str, download_manifest: Path, archive_root: Path, review_root: Path, calibration_root: Path)`, `replace_active: bool`, and injectable `now_utc` only for tests.
- Produces: `AutomaticWorkflowResult(status: Literal["activated", "rejected", "operational_failure"], exit_code: int, run_root: Path, receipt_path: Path, manifest_path: Path | None)` and `run_automatic_workflow(config: AutomaticWorkflowConfig, *, replace_active: bool = False, now_utc: str | None = None) -> AutomaticWorkflowResult`.

- [ ] **Step 1: Write failing successful-workflow test**

Add `test_success_runs_primary_holdout_folds_acceptance_registration_and_activation_in_order`. Patch only expensive image operations; use real gate, receipt, approval, registry, and activation code. Assert canonical receipt publication, deterministic mask ID, final `ACTIVATED` state, and unchanged source files.

- [ ] **Step 2: Implement stage orchestration through gate evaluation**

Create the immutable timestamped run, atomically write `automatic_run.json`, build the primary proposal and five folds, verify every seal, audit all held-out originals, compute fold comparisons, finalize a run-local five-pixel-margin mask, and evaluate Task 1 gates. Do not call approval or registry functions in this step.

- [ ] **Step 3: Write and pass every-gate rejection tests**

Add a table-driven `test_each_failed_gate_writes_rejection_and_preserves_registry_bytes`. Cover insufficient total/calibration/holdout dates, insufficient held-out frames/detections, mixed signature, visible-fraction bounds, footprint bounds, boundary fraction, fold IoU, and fold boundary distances.

- [ ] **Step 4: Implement accepted publication and activation**

On pass, write the canonical receipt to the calibration root, derive the mask ID, call automated `approve_proposal`, register via the existing idempotent function, and activate through the existing append-only function. Re-hash all evidence immediately before the first registry write.

- [ ] **Step 5: Add active-installation and idempotency tests**

Add `test_no_active_installation_activates`, `test_same_active_installation_is_idempotent`, `test_different_active_installation_refuses_before_run_without_replace`, `test_replace_active_switches_only_after_all_gates_pass`, and `test_identical_rerun_reuses_content_addressed_acceptance_without_registry_conflict`.

- [ ] **Step 6: Add concurrency and partial-failure tests**

Add `test_second_process_lock_refuses_before_run_directory`, `test_registration_then_activation_failure_records_registered_inactive_state`, `test_post_activation_receipt_failure_reports_active_without_rollback`, and tamper tests for proposal, fold, held-out detail, finalized mask, and canonical receipt. Assert exact registry bytes at each failure boundary.

- [ ] **Step 7: Implement lock and durable partial-state handling**

Use `fcntl.flock(..., LOCK_EX | LOCK_NB)` on the safe per-source/camera path and hold it through receipt publication. Convert gate rejection to exit one, configuration validation to exit two, and operational exceptions to a durable exit-three receipt; after an activation record exists, final status must remain activated even if later reporting fails.

- [ ] **Step 8: Run workflow, calibration, registry, and cold-start suites**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_auto_workflow test_visible_sky_automatic test_visible_sky_calibration test_visible_sky_registry test_visible_sky_cold_start`

Expected: all tests pass.

- [ ] **Step 9: Review checkpoint**

Run `git diff --check`; inspect that no failure path mutates historical artifacts. Commit only if the required full suite and root demo pass.

### Task 5: One-command CLI, portable launcher, and operator documentation

**Files:**
- Modify: `v25/visible_sky_operator.py`
- Modify: `v25/test_visible_sky_operator.py`
- Modify: `go_visible_sky_v25.sh` only if launcher behavior needs adjustment
- Modify: `v25/examples/visible_sky_operator.example.toml`
- Modify: `v25/README.md`
- Modify: `README.md`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `.github/workflows/tests.yml`
- Modify: `test_v25_documentation.py`

**Interfaces:**
- Consumes: no arguments for managed-archive discovery, or `auto --config PATH [--replace-active]` as an advanced override using the existing exact TOML schema.
- Produces: compact stage progress plus exactly one final `ACTIVATED …` or `NOT ACTIVATED …` line; exits with the workflow result code.

- [ ] **Step 1: Write failing CLI delegation tests**

Add zero-argument discovery coverage plus `test_auto_requires_only_config`, `test_auto_delegates_one_workflow_call`, `test_auto_replace_active_is_explicit`, `test_auto_maps_result_status_to_exact_exit_code`, and `test_manual_subcommands_are_unchanged`. Assert managed discovery, config-relative override paths, and no user-supplied path/hash/mask-ID/actor options on `auto`.

- [ ] **Step 2: Implement the thin `auto` command**

Add parser arguments, translate `OperatorConfig` to `AutomaticWorkflowConfig`, call `run_automatic_workflow` once, print the exact compact terminal line, and return its exit code. Do not place scientific gates or registry writes in the CLI module.

- [ ] **Step 3: Test portable real launcher help**

Run from `/tmp` with a deliberately wrong `VIRTUAL_ENV`:

`env VIRTUAL_ENV=/tmp/wrong /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/go_visible_sky_v25.sh auto --help`

Expected: exit zero and help showing only `--config` and `--replace-active` for `auto`.

- [ ] **Step 4: Write failing documentation and CI assertions**

Require the v25 README to lead with the single automatic command, explain minimum data and every fixed gate, distinguish automated from visual approval, document `--replace-active`, and retain manual commands as advanced recovery tools. Require CI to run automatic success/rejection/locking tests and the v25 demo.

- [ ] **Step 5: Update docs, example comments, and CI**

Keep the example TOML’s nine-key schema unchanged. State plainly that real non-MMTO validation is still limited until another camera passes the automatic gates. Do not call this a GitHub release.

- [ ] **Step 6: Run operator and documentation suites**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_operator test_visible_sky_auto_workflow test_visible_sky_automatic`

Run: `uv run --frozen python -m unittest -v test_v25_documentation test_v25_runtime_boundary`

Expected: all tests pass.

- [ ] **Step 7: Regenerate and verify the v25 manifest**

Run: `uv run --project v25 --frozen python v25/scripts/update_v25_manifest.py`

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary`

Expected: manifest inventory and every hash match, while `docs/v24-runtime.json` remains unchanged.

- [ ] **Step 8: Review checkpoint**

Run `git diff --check`; inspect all user-facing commands directly. Commit only if the repository-required full suite and root demo pass.

### Task 6: Full verification and independent review

**Files:**
- Modify only files required to correct issues found by verification or review.
- Preserve new outputs under unique result directories.

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: final evidence that the automatic path, manual path, v25 runtime, v24 snapshot, and preserved demos remain valid.

- [ ] **Step 1: Run all focused v25 lifecycle suites**

Run: `cd v25 && uv run --frozen python -m unittest -v test_visible_sky_operator test_visible_sky_auto_workflow test_visible_sky_automatic test_visible_sky_calibration test_visible_sky_registry test_visible_sky_cold_start test_visible_sky_mask_builder test_visible_sky_mask_integration`

Expected: all pass.

- [ ] **Step 2: Run root boundary and pipeline suites**

Run: `uv run --frozen python -m unittest -v test_v24_documentation test_v24_runtime_boundary test_v25_documentation test_v25_runtime_boundary test_run_mmto_photometry_pipeline_v25`

Expected: all pass.

- [ ] **Step 3: Run the exact required root suite**

Run: `uv run --frozen python -m unittest discover -v`

Expected: all task-related tests pass. If the pre-existing offloaded-results-path assertion remains the only failure, record its exact traceback and do not claim a clean suite or commit.

- [ ] **Step 4: Run both preserved demos in new directories**

Run: `./demo.sh --output results/check-v25-auto-root-20261116`

Run: `./v25/demo.sh --output v25/results/check-v25-auto-demo-20261116`

Expected: both baseline checks pass; no historical output is overwritten.

- [ ] **Step 5: Exercise automatic rejection without registry mutation**

Run the real launcher against a temporary managed fixture with insufficient dates. Expected: exit one, one `NOT ACTIVATED` line, durable rejection receipt, and byte-identical registry.

- [ ] **Step 6: Exercise synthetic automatic activation end to end**

Run the real launcher against a temporary multi-date native fixture that meets every gate. Expected: exit zero, one `ACTIVATED` line, content-addressed acceptance, production manifest, registration, activation, and a valid load through `VisibleSkyMask.load`.

- [ ] **Step 7: Request independent code review**

Ask a fresh reviewer to check gate integrity, held-out isolation, fold independence, automated provenance wording, content-addressed idempotency, lock coverage, replacement safety, partial failures, v24 preservation, docs, and test evidence. Address every Critical or Important finding test-first.

- [ ] **Step 8: Final hygiene and commit decision**

Run `uv run --project v25 --frozen python v25/scripts/update_v25_manifest.py`, `git diff --check`, and `git status --short --branch`. Preserve unrelated raw-archive changes. Only if both AGENTS-required commands pass, stage the exact task files and commit with `feat: automate v25 visible-sky activation`; otherwise leave the verified working tree uncommitted and report the blocker precisely.
