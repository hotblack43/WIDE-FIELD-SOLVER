# Stellar-Calibrated Planet Photometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert each complete planet count-rate measurement to a stellar-calibrated, extinction-corrected, distance-normalized magnitude using the independently saved stellar solution from the same image.

**Architecture:** Extend the read-only plotting script, without changing the frozen v11 runtime or databases. Read the saved per-channel stellar regression and the matched planet's measured altitude, apply the saved relation at that airmass, combine measurement uncertainty with stellar-fit scatter, and omit incomplete rows with an audited reason.

**Tech Stack:** Python standard library, SQLite, NumPy, Astropy, Matplotlib, unittest.

**Spec:** [GOAL.md](../../../GOAL.md), especially “Photometry and colour”, “Supporting physical-zenith constraint”, and the metadata-validation boundary.

## Global Constraints

- Keep v11 and all preserved runtimes unchanged.
- Read databases and retained source images without modifying them.
- Use the saved star fit from the same run and native channel; do not pool camera zero points.
- Label passband limitations and provisional stellar solutions honestly.
- Plot only rows with complete count rate, stellar fit, altitude, distances, and uncertainty.
- Do not use metadata to alter the blind fit; this is downstream photometric analysis only.

## Review Focus

- Missing or malformed stellar fit: exclude the planet row with an explicit reason.
- Missing or sub-horizon planet altitude: exclude rather than invent an airmass.
- Multiple planet matches: join by both planet name and detection ID.
- Channel mismatch: use only the requested channel's saved fit.
- Uncertainty: combine native measurement uncertainty and the saved stellar residual RMS in quadrature.

---

### Task 1: Calibrated magnitude calculation

**Files:**
- Modify: `scripts/plot_planet_photometry.py`
- Test: `test_plot_planet_photometry.py`

**Interfaces:**
- Consumes: machine magnitude, stellar intercept, extinction coefficient, measured altitude, and distance pair.
- Produces: `_kasten_young_airmass(altitude_deg)` and `_stellar_calibrated_distance_magnitude(...)`.

- [x] **Step 1: Write failing unit tests** for the saved regression sign, airmass term, distance term, and invalid altitude.
- [x] **Step 2: Run the focused tests and confirm failure.**
- [x] **Step 3: Implement the two pure calculation helpers.**
- [x] **Step 4: Run the focused tests and confirm they pass.**

### Task 2: Load same-image stellar solutions and planet altitudes

**Files:**
- Modify: `scripts/plot_planet_photometry.py`
- Test: `test_plot_planet_photometry.py`

**Interfaces:**
- Consumes: read-only `photometry_summary.json` and `planet_epoch.json` products keyed by run ID.
- Produces: per-row calibration fields, measured altitude, and explicit availability status.

- [x] **Step 1: Add an integration fixture** with a channel-specific stellar fit and a planet match containing measured altitude.
- [x] **Step 2: Run the focused test and confirm failure.**
- [x] **Step 3: Parse and join the saved records without changing detection selection.**
- [x] **Step 4: Add missing-fit, wrong-channel, and missing-altitude exclusion tests and make them pass.**

### Task 3: Export and plot complete calibrated rows

**Files:**
- Modify: `scripts/plot_planet_photometry.py`
- Test: `test_plot_planet_photometry.py`

**Interfaces:**
- Consumes: loaded planet rows plus existing distance and aperture-uncertainty lookups.
- Produces: `planet_stellar_calibrated_distance_measurements.csv`, audited summary JSON, PNG, and PDF.

- [x] **Step 1: Write a failing output test** checking the calibrated value, total uncertainty, filenames, axis label, and incomplete-row audit.
- [x] **Step 2: Run the focused test and confirm failure.**
- [x] **Step 3: Implement export, uncertainty propagation, and the colour/marker/group-line plot.**
- [x] **Step 4: Run the complete plot test module and correct regressions.**

### Task 4: Regenerate and verify

**Files:**
- Modify: the already scheduled 04:00 batch command, if needed, so it requests the calibrated product.
- Create: `results/planet-lightcurves-20260925-stellar-calibrated/` outputs.

**Interfaces:**
- Consumes: accumulated results database and newly implemented plot mode.
- Produces: a presently inspectable plot and a scheduled repeat after new MMTO processing.

- [x] **Step 1: Run the plot-specific tests and the repository unit suite.**
- [x] **Step 2: Generate the current calibrated plot and inspect its numerical summary.**
- [x] **Step 3: Inspect the PNG for legibility and label/legend collisions.**
- [x] **Step 4: Verify the 04:00 job invokes the calibrated plot and report exact output paths and exclusions.**
