# V26 Saturated-Source Photometric Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve and use direct fluxes, accepted saturated-wing estimates, and clipped-aperture lower bounds when ranking blind planet candidates.

**Architecture:** Create a complete v26 successor from v25, add a small typed-evidence module, and integrate its soft costs into the existing non-detection candidate ordering. Photometry may reorder otherwise comparable aliases but cannot alter astrometry or establish a unique date by itself.

**Tech Stack:** Python, NumPy, Astropy, SciPy, unittest, uv.

**Spec:** `docs/superpowers/specs/2026-11-21-v26-saturated-photometric-evidence-design.md`

## Global Constraints

- Preserve every existing version and launcher.
- Do not use site/time metadata in the blind calculation.
- Do not change measured centroids, Barghini coordinates, or positional costs.
- Retain lower bounds and rejected fits with explicit provenance.
- Use test-first development and do not relax regression limits.

## Review Focus

- Accepted wing rate is used only when its saved status says it is modelled from unsaturated wings.
- Rejected wing fits fall back to a one-sided aperture lower bound.
- A candidate brighter than a lower bound is not penalized; a fainter candidate is.
- Missing calibration or rates produce explicit unavailable records and zero cost.
- Photometric ordering never changes a single-planet alias set into a unique-date claim.

---

### Task 1: Establish the v26 boundary

**Files:** Create `v26/`, `go26.sh`, `go_v0.26.0.sh`, `go_mmto_photometry_v26.sh`, and v26 pipeline/test counterparts.

- [x] Copy the complete v25 runtime and versioned launchers to v26 without editing v25.
- [x] Mechanically update package/version references and create a deliberate v26 source manifest.
- [x] Run manifest and launcher smoke tests.

### Task 2: Add typed saturated-source evidence

**Files:** Create `v26/point_star_photometric_evidence.py`; test in `v26/test_photometric_evidence.py`.

- [x] Write failing tests for direct, accepted-wing, lower-bound, and unavailable evidence.
- [x] Run the tests and confirm the expected missing-module/API failure.
- [x] Implement `measurement_evidence`, `matched_planet_evidence`, and soft-L1 cost calculation.
- [x] Run the focused tests to green.

### Task 3: Integrate evidence into candidate ordering

**Files:** Modify `v26/point_star_planet_nondetections.py`; tests in `v26/test_planet_nondetections.py`.

- [x] Write a failing test showing typed photometry reorders equal-count aliases without changing either positional fit.
- [x] Write a failing test showing lower-bound evidence is one-sided.
- [x] Load saved source photometry and photometric calibration, attach candidate evidence, and add its cost after hard physical checks but before positional cost.
- [x] Preserve the existing ambiguity rule for single-planet aliases.
- [x] Run focused tests to green.

### Task 4: Report and verify

**Files:** Modify `v26/README.md`, `v26/HANDOFF.md`, `v26/docs/FEATURE_STATUS.md`, root `docs/FEATURE_STATUS.md`, and v26 manifest.

- [x] Document evidence types, uncertainty floors, limitations, and numerical effects.
- [ ] Run the full v26 suite and repository suite. Repository suite: 757 tests passed; broad v26 discovery: 676 passed and five inherited discovery/fixture errors reproduced in v25.
- [x] Run `./v26/demo.sh --output results/check-v26-saturated-evidence` on the preserved MMTO input.
- [x] Inspect candidate JSON and report products; record all changed user-facing products.
