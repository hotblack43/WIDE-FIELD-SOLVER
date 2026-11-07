# V23 Variable-Star Phase Curves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v23's chronological variable-star PDF with phase-folded R/G/B light curves.

**Architecture:** Reuse the existing per-star earliest UTC and VSX period to transform every nightly point into phase `[0, 1)`. Keep the existing magnitude values and sine fitting, but render the scatter and fitted curves on a phase axis and publish the renamed PDF with updated metadata.

**Tech Stack:** Python 3.12, NumPy, Matplotlib, unittest, shell launchers

**Spec:** `docs/superpowers/specs/2026-11-05-v23-variable-star-phase-curves-design.md`

## Global Constraints

- Modify active v23 only; do not change frozen earlier versions.
- Do not alter historical result directories or existing user data.
- Preserve all numerical magnitude and fixed-period sine-fit CSV values.
- Do not create a git commit unless requested.

## Review Focus

- A timestamp exactly one or more periods after the reference wraps to phase zero.
- Negative elapsed time is impossible for the selected reference but phase conversion remains modulo-safe.
- Sparse stars still render without requiring a successful sine fit.
- Empty selections still produce a readable one-page PDF under the new name.
- Multipage selections retain every selected star.

---

### Task 1: Phase-folded plot and renamed product

**Files:**
- Modify: `v23/test_plot_mmto_variable_stars.py`
- Modify: `v23/scripts/plot_mmto_variable_stars.py`

**Interfaces:**
- Produces: `phase_for_observation(observed_utc, reference_utc, period_days) -> float`
- Produces: `make_phase_curve_page(...) -> matplotlib.figure.Figure`
- Produces: `variable_star_phase_curves.pdf`

- [ ] Write tests for phase wrapping, plotted x coordinates, phase-axis labeling, PDF naming, old-PDF absence, empty output, and page count.
- [ ] Run the focused test module and confirm failures identify the missing phase behavior.
- [ ] Implement the phase transform, phase-domain scatter and sine curves, renamed PDF, metadata, and terminal output.
- [ ] Run the focused test module and confirm it passes.

### Task 2: Documentation and regression verification

**Files:**
- Modify: `v23/README.md`
- Modify: `v23/docs/FEATURE_STATUS.md`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `docs/MMTO_PHOTOMETRY_PIPELINE.md`

**Interfaces:**
- Documents: phase-zero convention, new output name, unchanged numerical processing.

- [ ] Replace current v23 time-series descriptions with the phase-folded convention without rewriting frozen-version history.
- [ ] Run the v23 variable-star tests, the full required unittest suite, and the required demo command.
- [ ] Generate a fresh disposable fixture product and visually inspect the rendered phase PDF.
