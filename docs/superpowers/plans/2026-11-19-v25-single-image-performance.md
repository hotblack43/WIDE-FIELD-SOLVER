# V25 Single-Image Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce v25 single-image wall time without changing scientific results.

**Architecture:** Reuse immutable, digest-keyed scientific image objects within
one solver process and reuse exact scalar planet states within one search. Keep
the existing public solver and pipeline interfaces unchanged.

**Tech Stack:** Python 3.12, NumPy, SciPy, Astropy, unittest.

**Spec:** `docs/superpowers/specs/2026-11-19-v25-single-image-performance-design.md`

## Global Constraints

- Modify only active v25 code, tests, and current documentation.
- Preserve byte-verification, blindness, numerical thresholds, products, and receipts.
- Performance must improve with one outer solver worker.

## Review Focus

- Same path with changed bytes must not reuse stale pixels.
- Different FITS load policies must not share a cached image.
- Cached arrays must not allow cross-consumer mutation.
- Scalar planet reuse must preserve visibility and angular residuals.
- Performance counters must continue to describe actual provider work.

---

### Task 1: Digest-keyed scientific image reuse

**Files:**
- Modify: `v25/point_star_image.py`
- Modify: `v25/test_point_star_image.py`

**Interfaces:**
- Produces: unchanged `load_scientific_image(...) -> ScientificImage` and `load_recorded_image(...) -> ScientificImage` APIs with safe process-local reuse.

- [x] Write tests proving identical source/policy returns the reused immutable image and changed bytes invalidate it.
- [x] Run the focused tests and verify they fail for the missing reuse behavior.
- [x] Add digest/policy-keyed one-entry reuse and make published arrays read-only.
- [x] Run the focused image tests and verify they pass.

### Task 2: Exact scalar planet-state reuse

**Files:**
- Modify: `v25/point_star_planets.py`
- Modify: `v25/test_point_star_planets.py`

**Interfaces:**
- Consumes: existing `EphemerisProvider.exact(name, dates)`.
- Produces: per-search scalar state reuse for identical `(planet, jd_tdb)` inputs.

- [x] Write a focused test proving repeated scalar ray/projection consumers use one authoritative provider evaluation while preserving the result.
- [x] Run it and verify the redundant-evaluation assertion fails.
- [x] Implement the minimal per-search scalar state cache and route scalar consumers through it.
- [x] Run focused planet tests and verify they pass.

### Task 3: Numerical and runtime verification

**Files:**
- Modify: `docs/FEATURE_STATUS.md`

**Interfaces:**
- Consumes: representative MMTO input and preserved v25 output checks.
- Produces: before/after wall-time and numerical comparison evidence.

- [x] Run the v25 focused suites for image, planets, MMTO pipeline, mask integration, and demo checks.
- [x] Run an uncached and warm representative `--solver-workers 1` benchmark without database append.
- [x] Compare machine-readable scientific outputs against the baseline, excluding timing/provenance fields that deliberately change.
- [x] Record the measured performance change and its reason in feature status.
- [x] Run repository-required verification commands and report any pre-existing failures without weakening tests.
