# V25 Visible-Sky Operator Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze accepted v24 and create an independent v25 runtime with one configuration-driven visible-sky calibration launcher and real v25 solving/MMTO commands.

**Architecture:** Snapshot the complete v24 boundary first, then mechanically fork its self-contained runtime and v24-labelled MMTO support into v25. Add one small Python orchestration module that validates a portable TOML file and delegates to the existing immutable calibration lifecycle; expose it through a Bash launcher while keeping proposal, approval, and activation separate.

**Tech Stack:** Python 3.12, Bash, `tomllib`, `argparse`, `unittest`, existing NumPy/SciPy/Pillow/Astropy calibration code, `uv` locked environments.

**Spec:** `docs/superpowers/specs/2026-11-16-v25-visible-sky-operator-workflow-design.md`

## Global Constraints

- Preserve every historical runtime and all user-owned raw-archive changes; never delete, hide, or overwrite working code.
- Include the accepted cold-start receipt and candidate mask in the final v24 checkpoint before recording `docs/v24-runtime.json`.
- After the v24 boundary is recorded, do not modify `go24.sh`, `go_v0.24.0.sh`, `go_mmto_photometry_v24.sh`, or any file in `v24/`.
- V25 must be complete without imports from v24 and must own its launchers, catalogue, lockfile, ephemeris data, masks, examples, and source manifest.
- Preserve the blind-solving boundary and existing MMTO mask numerics.
- `propose`, `revise`, `approve`, and `activate` remain explicit separate operations; no stage may silently perform the next.
- Relative configuration paths resolve from the configuration file.
- Do not claim cross-camera validation; the example configuration is illustrative only.
- Execute in the current native checkout because accepted v24 work and user changes are already present; do not create a worktree that omits them.
- Before any commit, run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-unique-name`; retain the known unrelated host-offload failure honestly.

## File Structure

- Create `docs/v24-runtime.json` and `test_v25_runtime_boundary.py`: freeze v24 launchers/package and protect v25 independence.
- Create `v25/`: complete mechanical fork of v24 with version-owned data, lockfile, examples, scripts, tests, README, and source manifest.
- Create `go25.sh`, `go_v0.25.0.sh`, `go_mmto_photometry_v25.sh`: public v25 solving and MMTO entry points.
- Create v25-labelled root MMTO support by copying the v24 pipeline and every invoked v24-labelled wrapper/script that is not already inside `v25/`.
- Create `v25/visible_sky_operator.py`: TOML schema/path validation and exact delegation argument construction.
- Create `v25/test_visible_sky_operator.py`: focused configuration and stage-separation tests.
- Create `go_visible_sky_v25.sh`: locked public entry point.
- Create `v25/examples/visible_sky_operator.example.toml`: portable documented example.
- Modify only root current-version documentation/tests after v24 is frozen: `README.md`, `docs/FEATURE_STATUS.md`, `docs/VERSIONS.md`, CI tests/workflow, and v25 manifest generator.

## Review Focus

- A configuration invoked from another working directory must resolve every relative path against its own directory; pinned in Task 3.
- Unknown/missing/empty configuration values must fail before creating the proposal directory; pinned in Task 3.
- No command may chain approval into activation or mutate a prior proposal; pinned in Task 3.
- Mechanical version substitution must not alter catalogue, ephemeris, example FITS, or approved mask bytes; pinned in Tasks 1 and 2.
- V25 MMTO receipt completion rules must identify exactly which predecessor receipts count and must not accidentally retain `0.24.0`; pinned in Task 2.

---

### Task 1: Finalise and freeze the accepted v24 checkpoint

**Files:**
- Modify: current accepted v24 checkpoint files already present in the working tree
- Create: `docs/v24-runtime.json`
- Create: `test_v25_runtime_boundary.py`

**Interfaces:**
- Produces: immutable v24 hash inventory covering `v24/`, `go24.sh`, `go_v0.24.0.sh`, `go_mmto_photometry_v24.sh`, and v24-labelled MMTO support files.
- Produces: boundary helpers used to prove v24 remains unchanged and v25 owns its runtime.

- [ ] **Step 1: Add failing boundary tests**

Assert the v24 snapshot exists, covers the intended tracked runtime exactly, matches every SHA-256, includes the accepted candidate/receipt, and excludes caches/results/raw archives.

- [ ] **Step 2: Run the boundary test and verify the missing snapshot failure**

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary`

Expected: FAIL because `docs/v24-runtime.json` does not exist.

- [ ] **Step 3: Generate the v24 snapshot from exact intended paths**

Record version `0.24.0`, snapshot kind, protected launchers/support files, and every repository v24 file including currently untracked accepted evidence. Do not include user raw-archive deletions.

- [ ] **Step 4: Run acceptance and boundary tests**

Run: `cd v24 && PYTHONPATH="$PWD:$PWD/.." uv run --project . --frozen python -m unittest -v test_visible_sky_cold_start test_visible_sky_calibration test_visible_sky_registry`

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary`

Expected: PASS.

### Task 2: Fork the complete independent v25 runtime and production launchers

**Files:**
- Create: `v25/` from the final v24 package
- Create: `go25.sh`, `go_v0.25.0.sh`, `go_mmto_photometry_v25.sh`
- Create: v25-labelled root MMTO pipeline/wrappers/tests required by `go_mmto_photometry_v25.sh`
- Modify: `test_v25_runtime_boundary.py`

**Interfaces:**
- Produces: version `0.25.0` solver entry points and an MMTO pipeline that invokes only v25-owned runtime paths.
- Consumes: exact v24 snapshot from Task 1 as the fork source and preservation oracle.

- [ ] **Step 1: Add failing tests for v25 version and independence**

Assert all three launchers report/use v25, `v25/pyproject.toml` is `0.25.0`, v25 source contains no runtime import from v24, every configured MMTO stage exists, and the v24 snapshot remains unchanged.

- [ ] **Step 2: Run tests and verify missing-v25 failures**

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary`

Expected: FAIL on missing v25 files.

- [ ] **Step 3: Mechanically fork runtime and support files**

Copy bytes first, then perform only version/path/name substitutions required for v25 ownership. Preserve catalogue, ephemeris, approved masks, example inputs, and lock dependency versions byte-for-byte; regenerate only version-dependent manifests and expected outputs.

- [ ] **Step 4: Define and test v25 MMTO receipt semantics**

Only v25 receipts represent completed v25 masked solves. Preserve bounded acquisition progress exactly as documented for v24/v23 unless an existing explicit rule requires otherwise; add focused tests before changing constants or SQL predicates.

- [ ] **Step 5: Run v25 boundary and launcher tests**

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary test_run_mmto_photometry_pipeline_v25`

Expected: PASS with the v24 snapshot unchanged.

### Task 3: Add the configuration-driven calibration operator command

**Files:**
- Create: `v25/visible_sky_operator.py`
- Create: `v25/test_visible_sky_operator.py`
- Create: `go_visible_sky_v25.sh`
- Create: `v25/examples/visible_sky_operator.example.toml`

**Interfaces:**
- Produces: `OperatorConfig.load(path: Path) -> OperatorConfig`.
- Produces: `delegate_arguments(command: str, config: OperatorConfig, args: argparse.Namespace) -> list[str]` for the v25 builder CLI.
- Produces: `main(argv: Sequence[str] | None = None) -> int`.
- Consumes: `v25/scripts/build_visible_sky_mask.py:main(argv)` without changing its scientific functions.

- [ ] **Step 1: Write failing configuration tests**

Test the exact schema and required keys, unknown/missing/empty values, path resolution from a different working directory, unsafe installation IDs, and failure before output creation.

- [ ] **Step 2: Write failing delegation and stage-separation tests**

Assert each public subcommand delegates only its corresponding builder operation with exact config-derived arguments; `propose` cannot approve, `approve` cannot activate, existing destinations are refused by the underlying immutable lifecycle, and the Bash launcher selects the v25 locked project.

- [ ] **Step 3: Run tests and verify missing-module failure**

Run: `cd v25 && PYTHONPATH="$PWD:$PWD/.." uv run --project . --frozen python -m unittest -v test_visible_sky_operator`

Expected: FAIL because the operator module and launcher do not exist.

- [ ] **Step 4: Implement the minimal TOML loader and delegator**

Use `tomllib`; reject keys outside the eight-key schema; resolve paths from `config.parent`; validate all input paths before calling the builder; default proposal output to `review_root/installation_id`; print the exact delegated builder result.

- [ ] **Step 5: Add the Bash entry point and example configuration**

The launcher unsets `VIRTUAL_ENV` and executes `uv run --project "$repo/v25" --frozen python "$repo/v25/visible_sky_operator.py" "$@"`. The example contains no real-camera validation claim.

- [ ] **Step 6: Run focused tests and help smoke tests**

Run: `cd v25 && PYTHONPATH="$PWD:$PWD/.." uv run --project . --frozen python -m unittest -v test_visible_sky_operator test_visible_sky_calibration test_visible_sky_registry`

Run: `./go_visible_sky_v25.sh --help`

Expected: PASS and help lists `propose`, `revise`, `approve`, and `activate`.

### Task 4: Document the real v25 workflow and refresh manifests

**Files:**
- Modify: `v25/README.md`
- Modify: `README.md`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `docs/VERSIONS.md`
- Modify: `.github/workflows/tests.yml`
- Modify: documentation/runtime-boundary tests
- Modify: `v25/scripts/update_v25_manifest.py`
- Regenerate: `v25/SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: verified commands and files from Tasks 1–3.
- Produces: user-facing instructions that lead with production/calibration commands and CI that exercises the v25 boundary and operator workflow.

- [ ] **Step 1: Add failing documentation and CI assertions**

Assert v24 is frozen, v25 is active, the README names all real v25 commands before the demo, the example config and operator test are in the v25 manifest, and CI runs the new focused tests.

- [ ] **Step 2: Run documentation tests and verify failure**

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary test_v24_documentation`

Expected: FAIL on missing v25 status/commands.

- [ ] **Step 3: Update documentation and CI without cross-camera claims**

State that MMTO is the only real cold-start validation, explain the mandatory human review boundary, and identify `go_visible_sky_v25.sh`, `go25.sh`, and `go_mmto_photometry_v25.sh` as operational entry points.

- [ ] **Step 4: Regenerate and verify the v25 source manifest**

Run the v25 manifest updater, confirm the complete tracked/new v25 inventory, and verify v24 hashes still match `docs/v24-runtime.json`.

- [ ] **Step 5: Run focused v25 verification**

Run isolated v25 calibration/operator/demo tests and root v24/v25 boundary/documentation tests. Expected: PASS.

### Task 5: Run repository verification and prepare the handoff

**Files:**
- No planned scientific-code changes; fix only failures caused by Tasks 1–4 using new failing regression tests.

**Interfaces:**
- Consumes: complete v25 implementation.
- Produces: evidence-backed status and precise inspection targets.

- [ ] **Step 1: Run required complete root tests**

Run: `uv run --frozen python -m unittest discover -v`

Expected: all new v25 tests pass; report the already documented host-offload-path failure separately if it remains.

- [ ] **Step 2: Run required root and v25 demos with fresh output names**

Run: `./demo.sh --output results/check-v25-boundary-20261116`

Run: `./v25/demo.sh --output v25/results/check-v25-demo-20261116`

Expected: both numerical baselines pass without modifying historical outputs.

- [ ] **Step 3: Request independent code review**

Review version preservation, config fail-closed behaviour, stage separation, receipt semantics, packaging inventory, and documentation claims. Resolve every Critical or Important issue test-first.

- [ ] **Step 4: Inspect final diff and status**

Run `git diff --check`, confirm raw-archive deletions remain untouched, and list only task-owned files for any eventual exact-file staging.

- [ ] **Step 5: Checkpoint safely**

Commit only if repository rules and exact-file staging permit it; otherwise leave the verified v25 diff uncommitted and report the known blocker. Do not tag or publish.
