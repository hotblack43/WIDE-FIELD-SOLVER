# V23 Recent Planet Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v23 acquire unseen remote images before cached leftovers and show recent uncalibrated planet measurements honestly on its main time plot.

**Architecture:** Adjust only the v23 acquisition planner, then extend the shared planet writer behind an opt-in flag used only by the v23 launcher. Corrected and uncorrected measurements remain separate in data products and plot styling.

**Tech Stack:** Python 3.12, unittest, Matplotlib, Bash, SQLite.

**Spec:** `docs/superpowers/specs/2026-10-23-v23-recent-planet-visibility-design.md`

## Global Constraints

- Do not modify frozen v21 runtime behavior.
- Preserve the one-night request boundary and the user-provided image cap.
- Do not relax extinction regression thresholds.
- Open points are distance-corrected only and must never be represented as extinction-corrected.
- Preserve unrelated working-tree changes, including `v23/SOURCE_MANIFEST.json`.

## Review Focus

- Empty current observing night must not prevent scanning the persistent cursor.
- A verified local candidate on the cursor night must not outrank an unseen remote candidate.
- Default plotting behavior must remain strict and omit uncalibrated points.
- Opt-in uncalibrated points must have metadata-time identities and usable photometry.
- The v23 launcher must pass the manifest and opt-in flag; preserved launchers must not.

---

### Task 1: Remote-first v23 acquisition

**Files:**
- Create: `test_run_mmto_photometry_pipeline_v23.py`
- Modify: `scripts/run_mmto_photometry_pipeline_v23.py`

**Interfaces:**
- Consumes: existing `build_acquisition_plan(...) -> AcquisitionPlan`.
- Produces: the same interface with remote cursor candidates selected before local backlog.

- [ ] Write focused tests for cursor-before-local and unseen-before-cached selection.
- [ ] Run them and verify they fail against the present local-first planner.
- [ ] Reorder the v23 planner and prioritize candidates with no verified download.
- [ ] Run the focused tests and the preserved v21 acquisition tests.

### Task 2: Honest recent points on the v23 plot

**Files:**
- Modify: `test_plot_planet_photometry.py`
- Modify: `scripts/plot_planet_photometry.py`
- Modify: `plot_ALL_planets.sh`
- Modify: `v23/plot_ALL_planets_v23.sh`
- Modify: `scripts/run_mmto_photometry_pipeline_v23.py`

**Interfaces:**
- Consumes: verified-manifest planet loader and nightly calibration sidecar.
- Produces: an opt-in `include_uncalibrated` plotting path, separate CSV, summary counts, and open unconnected symbols.

- [ ] Write tests proving strict default omission and opt-in distance-only export/plot styling.
- [ ] Run them and verify the opt-in test fails for missing behavior.
- [ ] Add the opt-in writer and plot support without changing the strict default.
- [ ] Wire only the v23 launcher/pipeline to the manifest-backed opt-in path.
- [ ] Run focused plotting and pipeline tests.

### Task 3: Documentation, manifest, and verification

**Files:**
- Modify: `docs/FEATURE_STATUS.md`
- Modify deliberately: `v23/SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: completed code and test changes.
- Produces: documented numerical/selection behavior and an updated v23 source manifest.

- [ ] Document the acquisition priority and the distinction between corrected and open distance-only points.
- [ ] Update the v23 manifest deliberately while preserving existing changes.
- [ ] Run the repository unit suite and the required unique-name demo.
- [ ] Run a bounded v23 dry-run or controlled reproduction proving the cursor is listed before local backlog.
- [ ] Render the changed planet PDF and visually verify labels, open symbols, axis direction, and no symbol/legend overlap.
