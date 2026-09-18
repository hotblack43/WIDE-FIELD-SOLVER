# v9 Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze v8/v8a and deliver a clone-runnable v0.9.0 containing their combined features with an unobtrusive zenith marker.

**Architecture:** Copy only the tracked self-contained v8a package into v9, then change its version/package boundary in place. Keep all scientific numerics unchanged; restrict the behavior edit to the valid-zenith overlay annotation. Record immutable checksums for the two parent runtimes and a complete manifest for v9.

**Tech Stack:** Bash launchers, Python 3.12, unittest, NumPy, Matplotlib, Astropy, uv.

**Spec:** `docs/superpowers/specs/2026-09-18-v9-consolidation-design.md`

## Global Constraints

- Do not create a branch or worktree; the user explicitly authorized implementation on current `main`.
- Do not modify any file beneath `v8/` or `v8a/`, nor their established launchers.
- Keep every detected source eligible for association and astrometric fitting.
- Do not change fitted coordinates, model parameters, residuals, or regression thresholds.
- Keep v9 self-contained and runnable from a normal clone.

---

### Task 1: Freeze parents and specify the v9 boundary

**Files:**
- Create: `docs/v8-runtime.json`
- Create: `docs/v8a-runtime.json`
- Modify: `test_preserved_versions.py`
- Create: `test_v9_launchers.py`

**Interfaces:**
- Consumes: tracked v8/v8a files and established launchers.
- Produces: checksum-enforced parent boundaries and executable v9 launcher expectations.

- [x] Write preservation and v9 launcher/version tests before creating v9.
- [x] Run them and confirm failure because v8/v8a runtime records and v9 are absent.
- [x] Generate exact parent checksums and the v9 package/launchers from tracked v8a files.
- [x] Run the focused tests and confirm they pass.

### Task 2: Remove the valid zenith's on-image label

**Files:**
- Modify: `v9/test_point_star_report.py`
- Modify: `v9/point_star_report.py`

**Interfaces:**
- Consumes: saved zenith vector/status and fitted Barghini camera.
- Produces: unchanged red-X position and legend handle with no attached annotation.

- [x] Extend the real overlay test to require no axes text beginning with `Zenith (`.
- [x] Run the focused v9 test and confirm the inherited annotation makes it fail.
- [x] Remove only the valid-marker annotation call.
- [x] Run the focused report tests and confirm the marker, legend, and warning cases pass.

### Task 3: Finalize package identity, manifests, and user documentation

**Files:**
- Modify: `v9/point_star_barghini.py`
- Modify: `v9/pyproject.toml`
- Modify: `v9/uv.lock`
- Modify: `v9/run.sh`
- Modify: `v9/AGENTS.md`
- Modify: `v9/README.md`
- Modify: `v9/docs/FEATURE_STATUS.md`
- Modify: `v9/SOURCE_MANIFEST.json`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/CONSOLIDATION.md`

**Interfaces:**
- Consumes: v9 source and tests after Task 2.
- Produces: consistent v0.9.0 identity, documented feature boundary, and complete hash inventory.

- [x] Replace only v8a package identity references with v9/v0.9.0 equivalents.
- [x] Document inherited features and the zenith-label presentation change.
- [x] Regenerate v9 manifest hashes after all package changes.
- [x] Run launcher, preservation, and manifest tests.

### Task 4: Full verification and review

**Files:**
- Verify: all changed and created paths.

**Interfaces:**
- Consumes: completed v9 runtime.
- Produces: fresh test/demo evidence and an independently reviewed diff.

- [x] Run `uv run --frozen python -m unittest discover -v` at repository root.
- [x] Run `uv run --project v9 --frozen python -m unittest discover -v` in v9.
- [x] Run `./demo.sh --output results/check-unique-name`.
- [x] Run the relevant v9 launcher/version smoke tests.
- [x] Review the full diff, verify v8/v8a checksums, and obtain code review.
