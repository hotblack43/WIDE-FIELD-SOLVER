# Wide-field Solver 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated v2 wide-field solver that compares Tycho-2 limits 7.5, 8.0, and 8.5 with the existing bright Hipparcos supplement.

**Architecture:** New `*2.py` files preserve v1 while reusing stable detector, Barghini model, reporting, and science helpers. The v2 driver runs independent magnitude-limited solutions and writes comparison evidence without selecting a winner.

**Tech Stack:** Python 3.12, NumPy, SciPy, Astropy, astroquery, tetra3, unittest.

**Spec:** `docs/superpowers/specs/2026-09-14-wide-solver2-design.md`

## Global Constraints

- Do not modify existing runtime Python files or the frozen v1 catalogue.
- Every new executable Python source and test basename ends in `2`.
- Candidate limits are exactly 7.5, 8.0, and 8.5.
- Retain the Hipparcos V <= 2.0 bright-star supplement.
- Use all detected sources by default and do not relax regression thresholds.
- Keep `uv.lock` committed and unchanged unless dependency resolution requires a documented change.

---

### Task 1: Depth schedule and catalogue filtering

**Files:**
- Create: `test_point_star_barghini2.py`
- Create: `point_star_barghini2.py`

**Interfaces:**
- Produces: `SUPPORTED_LIMITS2`, `association_stages2(limit)`, `catalogue_indices2(magnitudes, limit)`, and `run2(..., magnitude_limit)`.

- [ ] **Step 1: Write failing schedule and filtering tests**

Test that 7.5 contains no deeper stages, 8.0 adds an 8.0 stage, 8.5 adds ordered 8.0 and 8.5 stages, invalid limits raise `ValueError`, and final indices exclude stars fainter than the selected limit.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run --frozen python -m unittest -v test_point_star_barghini2.py`
Expected: import failure because `point_star_barghini2.py` does not exist.

- [ ] **Step 3: Implement the minimal v2 solver**

Copy the working v1 solver to the new suffixed file, add the tested helpers, add a required `magnitude_limit` argument to `run2`, use the selected limit for progressive and final associations, and write v2 result metadata without changing v1.

- [ ] **Step 4: Run focused and full tests**

Run the focused v2 test, then `uv run --frozen python -m unittest discover -v`.
Expected: all tests pass.

### Task 2: V2 catalogue builder

**Files:**
- Create: `scripts/rebuild_catalogue2.py`
- Extend: `test_point_star_barghini2.py`

**Interfaces:**
- Produces: parser defaults of magnitude 8.5, Hipparcos supplement 2.0, and output `data/stars_tycho2_mag85_v2.csv`.

- [ ] **Step 1: Write a failing parser-default test**

Load the new script as a module and assert its parser exposes the three literal defaults.

- [ ] **Step 2: Run the focused test and verify RED**

Expected: failure because `scripts/rebuild_catalogue2.py` does not exist.

- [ ] **Step 3: Implement the builder**

Create the suffixed builder from the proven v1 logic, changing only v2 defaults and output labelling.

- [ ] **Step 4: Run focused and full tests**

Expected: all tests pass and no v1 file changes.

### Task 3: Comparison driver and stability summary

**Files:**
- Create: `analyse_image2.py`
- Extend: `test_point_star_barghini2.py`

**Interfaces:**
- Produces: `validate_limits2(values)`, `association_stability2(previous_rows, current_rows)`, and CLI output `limiting_magnitude_comparison2.json`.

- [ ] **Step 1: Write failing validation and stability tests**

Use hand-checked detection/star pairs to assert retained, gained, lost, stable-pair, and reassigned-pair counts. Reject duplicate, unsorted, or unsupported limits.

- [ ] **Step 2: Run focused test and verify RED**

Expected: import failure because `analyse_image2.py` does not exist.

- [ ] **Step 3: Implement the comparison driver**

Run each candidate in a separate `vlim_7p5`, `vlim_8p0`, or `vlim_8p5` directory, preserve failed candidate evidence, and write comparison-only JSON with no winner field.

- [ ] **Step 4: Run focused and full tests**

Expected: all tests pass.

### Task 4: Candidate data, documentation, and real-image verification

**Files:**
- Create: `data/stars_tycho2_mag85_v2.csv`
- Create: `docs/WIDE_SOLVER2.md`

**Interfaces:**
- Documents and supplies the v2 CLI and provenance.

- [ ] **Step 1: Build the 8.5 catalogue**

Run: `uv run --frozen python scripts/rebuild_catalogue2.py`.
Verify Tycho rows stop at 8.5, the supplement stops at V=2.0, identifiers are unique, and required columns are populated.

- [ ] **Step 2: Run v2 on the preserved Milky Way image**

Run the v2 driver to a unique `results/` directory and inspect all three candidate records, association stability, and unchanged historical reference checksums.

- [ ] **Step 3: Document commands and interpretation**

State that fitted residuals are not independent validation and that v2 reports rather than selects the limiting magnitude.

- [ ] **Step 4: Run required verification**

Run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-unique-name`. Run `git diff --check` and confirm v1 runtime files, frozen catalogue, and historical reference are unchanged.
