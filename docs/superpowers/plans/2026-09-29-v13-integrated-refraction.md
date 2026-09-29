# V13 Integrated Refraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a self-contained v13 that robustly co-fits atmospheric refraction with the Barghini model and validates it on existing full-fisheye solutions.

**Architecture:** Preserve v12 as an immutable versioned snapshot, clone it to v13, then extend the v13 camera with physical-zenith and A/B refraction state. Bootstrap remains unchanged; all mature association, epoch, and export paths use the coupled robust model. A replay tool compares nested zero and integrated models on deterministic spatial blocks across multiple fisheye camera families.

**Tech Stack:** Python 3.12, NumPy, SciPy `least_squares`, Astropy, unittest, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-v13-integrated-refraction-design.md`

## Global Constraints

- Preserve root legacy and v4 through v12 byte for byte after their boundary manifests are recorded.
- Do not create or use a development branch or linked worktree.
- Use robust radial soft-L1 least squares; never OLS.
- Do not use site, timestamp, filename date, saved identities, or saved camera state to seed a fresh blind solve.
- Use all detected sources for association; keep saturated and broad sources eligible.
- Never move measured or predicted plot symbols cosmetically.
- Do not weaken regression thresholds.
- Validate only full-fisheye/all-sky images; exclude small fields.

## Review Focus

- Refraction/lens degeneracy must not manufacture nonzero A/B on zero-refraction data; Task 2 tests nested fallback.
- Near-horizon tangent growth must remain finite and explicitly invalid outside the supported domain; Task 2 tests the boundary.
- Epoch profiling must refit the complete coupled model at every trial rather than reuse stale refraction; Task 3 tests trial-state changes.
- Saved coordinates and forward projections must be inverse-consistent under adopted refraction; Task 2 and Task 3 test both directions.
- Real-image selection must reject small/non-fisheye fields without consulting site/time metadata; Task 4 tests the selector.

---

### Task 1: Preserve v12 and establish the v13 boundary

**Files:**
- Create: `v12/`, `go12.sh`, `go_v0.12.0.sh`, `docs/v12-runtime.json`, `test_v12_boundary.py`
- Create: `v13/`, `go13.sh`, `go_v0.13.0.sh`, `test_v13_boundary.py`
- Modify: `AGENTS.md`

**Interfaces:**
- Produces: immutable v12 package and independent v13 package/launchers.
- Consumes: the existing complete v12 snapshot; no scientific behavior changes.

- [ ] Write boundary tests that require complete local v12/v13 packages, independent launchers, locks, data and manifests while proving older runtime hashes remain unchanged.
- [ ] Run the boundary tests and verify they fail because v12/v13 are absent from `main`.
- [ ] Copy the existing v12 package without modification, record its hashes, clone it mechanically to v13, and update only v13 names/version references/manifests.
- [ ] Run boundary and preserved-version tests and verify they pass.
- [ ] Run the repository-required root suite and demo, then commit the version boundary.

### Task 2: Add a coupled robust refracted Barghini camera

**Files:**
- Modify: `v13/point_star_barghini.py`
- Modify: `v13/point_star_refraction.py`
- Create: `v13/test_integrated_refraction.py`

**Interfaces:**
- Produces: `IntegratedRefraction`, refraction-aware `BarghiniCamera.to_sky()` / `project()`, and `fit_camera(..., fit_refraction=True)`.
- Consumes: v13 Barghini detector geometry and existing `apply_refraction` / `remove_refraction` physics.

- [ ] Write failing synthetic tests for zero/injected refraction, robust outlier resistance, forward/inverse consistency, serialization and horizon-domain rejection.
- [ ] Run the focused tests and verify failures identify the missing integrated API.
- [ ] Implement the minimal coupled parameterization and robust residual path.
- [ ] Run focused tests and the full v13 suite; verify they pass.
- [ ] Run the repository-required root suite and demo, then commit the coupled camera.

### Task 3: Put the coupled model into solve, epoch and export paths

**Files:**
- Modify: `v13/point_star_barghini.py`
- Modify: `v13/point_star_epoch.py`
- Modify: `v13/point_star_joint_epoch.py`
- Modify: `v13/point_star_science.py`
- Modify: `v13/point_star_fits.py`
- Modify: `v13/test_epoch_integration.py`
- Modify: `v13/test_joint_epoch.py`
- Modify: `v13/test_point_star_fits.py`
- Modify: `v13/test_integrated_refraction.py`

**Interfaces:**
- Produces: coupled post-bootstrap iterations, model-selection evidence, authoritative corrected CSV/FITS/planet coordinates.
- Consumes: Task 2 camera API.

- [ ] Write failing integration tests showing every epoch trial refits refraction, rejected refraction becomes exact zero, and adopted refraction changes saved coordinates consistently.
- [ ] Run focused tests and verify the failures correspond to the old downstream-only path.
- [ ] Integrate seeding, joint refinement, blocked robust validation, reassociation and authoritative serialization/export.
- [ ] Replace v13 downstream refraction refitting with reporting of the integrated camera result.
- [ ] Run focused tests and the full v13 suite; verify they pass.
- [ ] Run the repository-required root suite and demo, then commit solver integration.

### Task 4: Compare existing full-fisheye image families

**Files:**
- Create: `v13/scripts/compare_integrated_refraction.py`
- Create: `v13/test_integrated_refraction_comparison.py`
- Create: `v13/docs/INTEGRATED_REFRACTION.md`
- Modify: `v13/docs/FEATURE_STATUS.md`
- Modify: `v13/SOURCE_MANIFEST.json`
- Modify: `GOAL.md`

**Interfaces:**
- Produces: CSV/JSON/Markdown/PNG comparison evidence with all failures retained.
- Consumes: Task 2 coupled fitter and saved `result.json` / `star_coordinates.csv` products.

- [ ] Write failing tests for fisheye-only selection, deterministic spatial blocks, complete failure rows and report products.
- [ ] Run focused tests and verify the comparison tool is missing.
- [ ] Implement the replay/comparison tool and document the robust-only requirement.
- [ ] Select multiple MMTO, APICAM, Subaru and historical full-fisheye solutions by checksum/coverage; explicitly reject small-field families.
- [ ] Run the comparison, inspect every failure, and record factual numerical results without promoting unsupported behavior.
- [ ] Run focused tests, the full v13 suite, preserved-version tests, root suite and both required demos.
- [ ] Update manifests and documentation, verify clean diffs, and commit the evidence.

### Task 5: Final verification and review

**Files:**
- Verify all files changed by Tasks 1–4.

**Interfaces:**
- Produces: reviewed, reproducible v13 working tree ready for GitHub synchronization.
- Consumes: all earlier task outputs.

- [ ] Verify v12 hashes and every older runtime manifest.
- [ ] Run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-v13-root-final`.
- [ ] Run `uv run --project v13 --frozen python -m unittest discover -s v13 -v` and `./v13/demo.sh --output v13/results/check-v13-final`.
- [ ] Review the complete diff for scientific/model consistency and address Critical or Important findings with RED-to-GREEN tests.
- [ ] Fetch GitHub, confirm `main` did not move unexpectedly, then push `main` only after all evidence is green.
