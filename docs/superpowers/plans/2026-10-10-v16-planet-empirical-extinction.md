# V16 Planet-Empirical Extinction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve v15 and deliver a self-contained v16 MMTO pipeline that stores clearly named planet-only nightly empirical extinction coefficients in shared SQLite and produces the airmass and local-noon diagnostics.

**Architecture:** Extend the existing planet-only plotter with an explicit transactional database writer and opt-in CLI flag. Freeze and clone v15 as v16, then add a versioned MMTO orchestrator whose final required stage invokes the plotter with database persistence enabled.

**Tech Stack:** Python 3.12, SQLite, SciPy Theil-Sen fitting, Matplotlib, Bash launchers, `unittest`, uv.

**Spec:** `docs/superpowers/specs/2026-10-10-v16-planet-empirical-extinction.md`

## Global Constraints

- Preserve v15 and every earlier runtime and launcher byte-for-byte.
- Develop the solver only in a complete self-contained `v16/` directory.
- Use planet photometry alone for the empirical coefficient; stellar products supply geometry only.
- Store immutable generations in shared `stars.sqlite`; never use them as solver input.
- Keep the standalone diagnostic read-only unless `--store-coefficients` is explicit.
- Do not overwrite existing output directories.
- Use TDD for every behavioral change and retain full audit evidence.

## Review Focus

- A database failure after figure generation must commit no partial coefficient generation.
- A repeated run must add history while latest views select one deterministic generation.
- Rejected fits must remain queryable but never appear in the latest-accepted view.
- V16 receipt selection must not treat v15 receipts as v16 completion.
- The v16 stage must use the verified manifest and shared database paths supplied by the pipeline.

---

### Task 1: Explicit coefficient names and SQLite persistence

**Files:**
- Modify: `scripts/plot_planet_only_airmass_correction.py`
- Modify: `test_plot_planet_only_airmass_correction.py`
- Modify: `docs/MMTO_NIGHTLY_EXTINCTION.md`

**Interfaces:**
- Produces: `write_planet_empirical_extinction_generation(database, manifest, output, fits_by_channel, source_audits, *, producer_version) -> str`
- Produces: CLI flag `--store-coefficients` and the two documented SQLite views.

- [ ] Write failing tests for explicit CSV field names, accepted/rejected database rows, immutable generations, latest views, atomic rollback, and default non-mutation.
- [ ] Run the focused tests and confirm failures identify missing schema/writer behavior.
- [ ] Rename coefficient fields and implement the transactional SQLite writer and opt-in CLI behavior.
- [ ] Run the focused planet-only tests to green.
- [ ] Update the scientific documentation and database schema description.

### Task 2: Freeze v15 and create the v16 runtime boundary

**Files:**
- Create: `docs/v15-runtime.json`
- Create: `v16/` as an independent copy of tracked v15 runtime files
- Create: `go16.sh`
- Create: `go_v0.16.0.sh`
- Create: `test_v16_boundary.py`
- Modify: root `AGENTS.md` if its boundary text is not already sufficient

**Interfaces:**
- Produces: solver version `0.16.0`, launcher `go16.sh`, and complete v16 source manifest.
- Consumes: frozen v15 tracked-file inventory and hashes.

- [ ] Write failing boundary tests for frozen v15 hashes, v16 package ownership, launcher routing, and version identity.
- [ ] Run the boundary tests and confirm they fail because v16 artifacts do not exist.
- [ ] Generate `docs/v15-runtime.json`, copy tracked v15 files to v16, update only version/package-local references, and rebuild the v16 source manifest.
- [ ] Add the two v16 solver launchers without changing prior launchers.
- [ ] Run v15/v16 boundary and launcher tests to green.

### Task 3: Integrate the required planet-only stage into the v16 MMTO pipeline

**Files:**
- Create: `scripts/run_mmto_photometry_pipeline_v16.py`
- Create: `go_mmto_photometry_v16.sh`
- Create: `test_run_mmto_photometry_pipeline_v16.py`
- Modify: `docs/MMTO_PHOTOMETRY_PIPELINE.md`

**Interfaces:**
- Consumes: `go16.sh` and the planet-only plotter CLI with `--store-coefficients`.
- Produces: v16 receipt selection and required `planet_empirical_extinction` stage/output.

- [ ] Write failing tests for v16-only receipt selection, launcher portability, stage arguments, output summary, and failure propagation.
- [ ] Run the focused tests and confirm they fail because v16 orchestration is absent.
- [ ] Clone the v15 orchestrator structure, update its version identity, and append the required planet-only stage using shared database and verified manifest.
- [ ] Add the portable shell launcher and documentation.
- [ ] Run all v16 pipeline tests to green while retaining v15 test behavior.

### Task 4: Real-data regeneration and repository verification

**Files:**
- Modify: `README.md`
- Modify: `docs/FEATURE_STATUS.md`
- Create: a new unique directory under `results/` for verification products

**Interfaces:**
- Consumes: completed v16 pipeline components and database views.
- Produces: inspectable R/G/B figures, coefficient rows in shared SQLite, and final verification evidence.

- [ ] Run the planet-only command on the real manifest with `--store-coefficients` and a new output directory.
- [ ] Query both SQLite views and reconcile counts/values against the generated CSVs.
- [ ] Render and inspect every new PDF page.
- [ ] Run `uv run --frozen python -m unittest discover -v` and the v16 package tests.
- [ ] Run `./demo.sh --output results/check-v16-planet-extinction-20261010` and the v16 MMTO demo/boundary checks.
- [ ] Request a whole-change code review and resolve all critical or important findings.
