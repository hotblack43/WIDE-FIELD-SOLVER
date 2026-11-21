# V26 Observation-Sidecar Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v26 cumulative differential-photometry replay include every compatible MMTO observation sidecar through v26 without manual enumeration.

**Architecture:** Discover versioned observation tables from SQLite metadata, bound discovery at v26, validate required columns, and feed the resulting ordered tables into the existing conflict-checked union. Keep every version's write table unchanged.

**Tech Stack:** Python 3, SQLite, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-21-v26-observation-sidecar-discovery-design.md`

## Global Constraints

- Change only the v26 development line and its documentation/tests.
- Preserve frozen runtimes and append-only databases.
- Read the manifest database without modification.
- Do not relax regression thresholds.

## Review Focus

- A v25-only observation must replay successfully.
- A future v27 observation table must not affect v26.
- An in-range observation table missing required columns must fail explicitly.
- Duplicate source hashes with identical metadata must remain accepted.
- Duplicate source hashes with conflicting metadata must remain fatal.

---

### Task 1: Replace manual observation-table enumeration

**Files:**
- Modify: `v26/test_mmto_differential_data.py`
- Modify: `v26/mmto_differential_data.py`
- Modify: `v26/README.md`
- Modify: `docs/FEATURE_STATUS.md`

**Interfaces:**
- Consumes: SQLite manifest connection and the existing `_observations()` replay loader.
- Produces: bounded, schema-validated observation discovery through v26.

- [x] **Step 1: Write failing behavioral tests**

Add tests showing that a run backed only by `mmto_v25_observations` loads, a
run backed only by `mmto_v27_observations` is rejected, and a malformed in-range
table raises a schema error.

- [x] **Step 2: Run the focused tests and verify the expected failures**

Run: `uv run --project v26 --frozen python -m unittest -v v26.test_mmto_differential_data`

- [x] **Step 3: Implement bounded discovery**

In `v26/mmto_differential_data.py`, discover names matching the versioned MMTO
observation-table pattern, retain versions `<= 26`, verify the three required
columns, sort numerically, and reuse the existing union/conflict logic.

- [x] **Step 4: Run focused and v26 test suites**

Run the focused test module and then the full v26 test package.

- [x] **Step 5: Update documentation and verify the repository**

Document automatic bounded discovery, run `uv run --frozen python -m unittest discover -v`, and run `./demo.sh --output results/check-unique-name`.
