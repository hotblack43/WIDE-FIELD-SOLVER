# Suppress Same-Sidereal Map Listing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop individual same-sidereal transmission map paths from flooding the end of successful v23 MMTO runs.

**Architecture:** Add a v23-specific final figure-listing function that partitions same-sidereal map figures from all other figures. List ordinary figures normally and replace the omitted map paths with one count-and-directory summary line.

**Tech Stack:** Python 3.12, pathlib, unittest

**Spec:** `docs/superpowers/specs/2026-11-05-suppress-sidereal-map-listing-design.md`

## Global Constraints

- Modify active v23 only; do not change frozen pipeline versions.
- Preserve all generated same-sidereal map files and manifest entries.
- Continue listing every non-sidereal PDF and PNG.
- Do not create a git commit unless requested.

## Review Focus

- Nested files below `same-sidereal-transmission/` are all suppressed.
- A directory with no maps does not emit a misleading suppression line.
- Non-sidereal PDF and PNG paths remain listed.
- The headline count represents listed figures, not suppressed maps.
- Terminal and pipeline-log output remain identical.

---

### Task 1: V23 final figure filtering

**Files:**
- Modify: `test_run_mmto_photometry_pipeline_v23.py`
- Modify: `scripts/run_mmto_photometry_pipeline_v23.py`
- Modify: `docs/MMTO_PHOTOMETRY_PIPELINE.md`
- Modify: `v23/README.md`

**Interfaces:**
- Produces: `_list_v23_figures(output: Path, log: TextIO) -> None`
- Consumes: completed v23 pipeline output directory.

- [ ] Add a regression test creating ordinary figures and nested same-sidereal maps; assert ordinary paths appear in stdout and log, map paths do not, and one map-count summary appears.
- [ ] Run the new test and confirm it fails because `_list_v23_figures` does not exist.
- [ ] Implement `_list_v23_figures` and call it at successful v23 completion.
- [ ] Document the compact final listing without changing saved products.
- [ ] Run the focused v23 pipeline tests and confirm they pass.
- [ ] Run `git diff --check`.
