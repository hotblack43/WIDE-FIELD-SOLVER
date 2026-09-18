# Gaia Comparison Implementation Plan

> Execute inline using the executing-plans workflow; user authorised the same-image experiment.

**Goal:** Build a Gaia-compatible local CSV and run the requested independent
Tycho/Gaia comparison with paired spatial resampling.
**Architecture:** A catalogue builder adapts public Gaia records into the existing
Catalogue interface. A separate experimental driver calls the unchanged solver
and profiles resampled fixed associations; it does not seed the full solves.
**Tech stack:** Existing Python/NumPy/SciPy/Astropy, standard-library HTTP/CSV.
**Spec:** ../specs/2026-09-14-gaia-comparison.md

## Constraints

Version 0.4.0; no dependency changes; keep historical data, default Tycho catalogue
and numerical thresholds. Native Gaia reference epochs and exact IDs. No metadata
in solving. 32 paired spatial subsamples, seed 20260914, retained fraction 0.8.

## Tasks

- [x] Catalogue adapter: tests in test_gaia_catalogue.py for exact IDs, epoch/PM
  mapping, missing motions and propagation-aware bright-star deduplication.
  Implement point_star_gaia.py and scripts/build_gaia_catalogue.py; write seven
  solver columns plus raw-data/provenance sidecars with guarded new outputs.
  Fetch full public Gaia data and verify returned count against COUNT(*).
- [x] Comparison experiment: test same-block membership for different star sets,
  deterministic sampling, shared-star scoring and uncertainty/failure reporting
  in test_catalogue_comparison.py. Implement point_star_catalogue_comparison.py
  and scripts/compare_catalogues.py. Call run independently for both catalogues,
  then fit_epoch on each retained sample; save per-replicate camera/epoch records.
- [x] Run actual image comparison and 32 samples. Inspect plots and distributions,
  record numerical findings and limits in docs/GAIA_V04.md. Update version and
  feature inventory, preserving explicit unfinished goals.
- [x] Run full unit suite and unchanged demo; review and commit isolated result.


Verification: 70 tests passed; the preserved demo passed at 3653 associations and
0.397892 px RMS without threshold changes. The first final-suite run exposed only
the integration fixture's stale 0.3.0 version assertion; updating it to 0.4.0
restored the suite. Both fresh blind solves and all 32 paired spatial resamples
completed. Numeric results are preserved in docs/GAIA_V04_RESULTS.json. A separate
review verified exact Gaia values, counts, checksums and sampling/metadata
boundaries; its covariance-wording finding was corrected. Only marginal errors,
not full covariance matrices, are fetched. Original runtime and older worktrees
remain preserved, with the clarified GOAL.md checkpointed separately.
