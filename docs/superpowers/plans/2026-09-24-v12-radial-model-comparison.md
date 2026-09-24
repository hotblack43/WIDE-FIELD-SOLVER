# V12 Nested Radial Model Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a preserved v12 experimental runtime that determines whether one to five additional radial Barghini terms earn their degrees of freedom across every usable previously solved image, measures whether the selected model recruits already-detected edge sources into catalogue associations, and tests fixed-identity major/minor-planet residuals near the edge.

**Architecture:** Preserve v11 by copying it into an independent v12 package. Add the nested radial mapping to v12's Barghini model, keep the normal blind solver on the zero-extension model, and implement a separate saved-solution study pipeline. Gaussian fixed-association fits supply AICc/BIC and spatial validation; robust baseline/selected fits supply operational RMS and association-yield comparisons.

**Tech Stack:** Python 3.12, NumPy 2.4.4, SciPy 1.17.1, Matplotlib 3.11.1, `unittest`, existing CSV/JSON solution products, uv.

**Spec:** `docs/superpowers/specs/2026-09-24-v12-radial-model-comparison-design.md`

## Global Constraints

- V11 and every earlier runtime, launcher, catalogue, example, and reference product remain byte-for-byte unchanged.
- New runtime code and data stay local to this independent repository and v12 owns its catalogue, lockfile, ephemeris data, examples, and manifest.
- The normal v12 blind solver continues to use the inherited eight-parameter Barghini model; the extension is experimental and invoked only by the comparison command.
- All full-data fits use every fixed association; withholding exists only inside explicitly labelled spatial validation.
- The added correction enters forward/inverse coordinates and saved predictions; no cosmetic displacement is permitted.
- Every selected image and model order, including failures, appears in machine-readable output.
- Source detection is unchanged. Association-yield results describe newly associated existing detections, never newly detected sources.
- Planet comparisons hold detection, identity, and epoch fixed and never turn conditional residual changes into new blind-epoch claims.
- V12 source and sky plots allow 40 spatially distributed star labels by default; names remain display-only.
- No regression threshold may be relaxed to hide a failure.
- Do not create intermediate commits: repository instructions require the full unit suite and demo before any commit.

## Review Focus

- A high-order polynomial can remain finite at sampled stars but turn non-monotonic between them; test dense full-detector derivative validation.
- Duplicate source hashes can have newer failed or older higher-version records; test deterministic successful-record selection.
- AICc is invalid for inadequate sample size or non-positive RSS; test explicit undefined results without crashes.
- Cross-validation can accidentally leak held-out rows through initialisation or membership; test folds cover every row once and training inputs exclude the held-out indices.
- Identity swaps can look like increased association count; test gained, lost, common, and changed identities separately.
- Re-selecting a planet identity or epoch after changing the camera would bias the edge test; hold both fixed and use the exact bundled ephemeris.

---

### Task 1: Establish the independent v12 boundary

**Files:**
- Create: `test_v12_boundary.py`
- Create: `go12.sh`
- Create: `go_v0.12.0.sh`
- Create: `v12/` as a mechanical copy of tracked `v11/`
- Create: `v12/scripts/update_v12_manifest.py`
- Modify: v12-local version references only (`v12/pyproject.toml`, `v12/uv.lock`, `v12/point_star_barghini.py`, `v12/AGENTS.md`)
- Modify: `AGENTS.md` to record the new development boundary without freezing v12

**Interfaces:**
- Consumes: frozen v11 package and `docs/v11-runtime.json`.
- Produces: standalone `v12` import/runtime directory; `go12.sh` and `go_v0.12.0.sh`; development `v12/SOURCE_MANIFEST.json`.

- [ ] **Step 1: Write the failing boundary test**

Add tests asserting that v11 still matches `docs/v11-runtime.json`, v12 reports version `0.12.0`, both new launchers route to `v12/run.sh`, v12 has its own lock/catalogue/ephemeris/example files, and its manifest hashes every tracked v12 file except itself.

- [ ] **Step 2: Run the boundary test and verify RED**

Run: `uv run --frozen python -m unittest -v test_v12_boundary`

Expected: FAIL because `v12/`, `go12.sh`, and `go_v0.12.0.sh` do not exist.

- [ ] **Step 3: Copy the v11 package and make only mechanical version changes**

Copy tracked v11 files into v12, change `0.11.0` to `0.12.0` only in version-bearing v12 files, create executable launchers pointing at `v12/run.sh`, and add a deterministic manifest updater whose change list names the radial comparison experiment. Do not alter any v11 byte.

- [ ] **Step 4: Generate the v12 lockfile and manifest**

Run `uv lock --offline` inside `v12/`. Make the manifest updater enumerate tracked plus untracked non-ignored v12 files with `git ls-files --cached --others --exclude-standard`, then generate `v12/SOURCE_MANIFEST.json` without changing the index.

- [ ] **Step 5: Run the boundary test and verify GREEN**

Run: `uv run --frozen python -m unittest -v test_v12_boundary`

Expected: all v12 boundary tests pass and the v11 digest check reports no changed v11 files.

### Task 2: Implement the nested radial Barghini mapping

**Files:**
- Modify: `v12/barghini_model.py`
- Create: `v12/radial_model.py`
- Create: `v12/test_radial_model.py`

**Interfaces:**
- Consumes: `BarghiniParameters`, projection helpers, and baseline radial functions from `v12/barghini_model.py`.
- Produces: `extended_radial_u(r, parameters, scale, coefficients)`, `extended_radial_du_dr(...)`, `inverse_extended_radial_u(...)`, and `ExtendedBarghiniCamera` with `to_sky`, `project`, `serialise`, `radial_derivative_grid`, and `is_valid`.

- [ ] **Step 1: Write failing mapping tests**

Test that an empty coefficient vector is numerically identical to `radial_u`; coefficients `[c3, c5]` add exactly `c3*rho**3 + c5*rho**5`; the derivative matches central finite differences; forward/inverse projection round-trips detector points; and serialisation records powers, coefficients, units, scale, and monotonicity.

- [ ] **Step 2: Run the mapping tests and verify RED**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_model.RadialMappingTests`

Expected: FAIL because the extended functions and camera do not exist.

- [ ] **Step 3: Implement the minimal extended mapping and camera**

Add normalized odd-power evaluation and derivative functions to `barghini_model.py`. Implement numerical inversion with `scipy.optimize.brentq` on `[0, corner_radius]`, validating endpoint range and a 1025-point derivative grid. Implement `ExtendedBarghiniCamera` as a separate comparison camera so `BarghiniCamera` and the ordinary solver remain unchanged.

- [ ] **Step 4: Run mapping tests and verify GREEN**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_model.RadialMappingTests`

Expected: mapping tests pass.

- [ ] **Step 5: Write and run failing invalid-model tests**

Add tests whose coefficients create a derivative sign change between sparse sample radii, exceed the invertible corner domain, or contain NaN. Verify they fail until `is_valid` returns structured reasons `non_monotonic`, `inverse_domain`, and `non_finite_coefficients`.

- [ ] **Step 6: Implement validation and rerun the complete radial-model test file**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_model`

Expected: all radial mapping and invalid-model tests pass.

### Task 3: Implement fitting, information criteria, and spatial validation

**Files:**
- Modify: `v12/radial_model.py`
- Create: `v12/radial_statistics.py`
- Create: `v12/test_radial_statistics.py`

**Interfaces:**
- Consumes: `ExtendedBarghiniCamera`, `tangent_residuals_arcmin`, and `radial_soft_l1_residuals`.
- Produces: `fit_extended_camera(camera, xy, sky, *, robust, max_nfev) -> FitResult`; `information_criteria(rss, n, k) -> dict`; `spatial_folds(xy, centre, fold_count=8) -> ndarray`; `cross_validate_orders(...) -> (model_rows, fold_rows)`; `classify_order(...) -> str`.

- [ ] **Step 1: Write failing literal information-criterion tests**

Use hand-calculated RSS, `n`, and `k` literals to assert AIC, AICc, and BIC. Assert `None` plus a reason for zero RSS, non-finite RSS, and `n <= k + 1`. Test Akaike weights sum to one across valid models and exclude failed models.

- [ ] **Step 2: Run the statistical tests and verify RED**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_statistics.InformationCriterionTests`

Expected: FAIL because `radial_statistics.py` does not exist.

- [ ] **Step 3: Implement information criteria and weights**

Implement the exact formulas in the design with no hidden rounding. Return JSON-safe Python floats or `None` and explicit reason strings.

- [ ] **Step 4: Run information-criterion tests and verify GREEN**

Run the command from Step 2; expected PASS.

- [ ] **Step 5: Write failing fit and rank tests**

Generate a literal synthetic star grid from a known `M2` camera. Assert an OLS `M2` fit reduces RSS and recovers held-out coordinates relative to `M0`; assert the result records `k`, Jacobian rank/condition, evaluation count, minimum derivative, angular RMS, and pixel RMS. Add a degenerate collinear sample that reports rank failure instead of success.

- [ ] **Step 6: Implement Gaussian and robust fitting**

Fit the eight normalized baseline parameters plus `q` coefficient angles with `scipy.optimize.least_squares`. Gaussian mode returns raw tangent residual coordinates; robust mode applies the existing rotationally invariant soft-L1 transformation. Keep monotonicity as an explicit validity gate and record numerical Jacobian SVD diagnostics.

- [ ] **Step 7: Verify synthetic recovery GREEN**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_statistics.ExtendedFitTests`

Expected: synthetic recovery passes; degenerate geometry is labelled failed.

- [ ] **Step 8: Write failing fold and overfit tests**

Assert deterministic eight-fold assignments cover every row once, each fold is a contiguous annular wedge, and a fold fit never receives held-out indices. On synthetic baseline data, added terms must not meet the support rule; on known radial structure, the correct lower order must improve blocked validation; on noise constructed to affect only one spatial block, fitted RMS may improve while validation classification is `in_sample_only` or `worse_prediction`.

- [ ] **Step 9: Implement fold fitting, bootstrap interval, and classifications**

Use two radius-ranked bands and four contiguous angle-ranked blocks per band; pool held-out squared residuals so each star counts once. Resample fold blocks with a fixed NumPy seed for 10,000 paired bootstrap replicates. Implement the five decision labels and the smallest-order-within-two-AICc selection rule.

- [ ] **Step 10: Run the complete statistics test file**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_statistics`

Expected: all information, fitting, fold, bootstrap, and classification tests pass.

### Task 4: Discover saved solutions and compare stellar/planet edge yield

**Files:**
- Create: `v12/radial_study.py`
- Create: `v12/test_radial_study.py`

**Interfaces:**
- Consumes: paths to historical `result.json`, `star_coordinates.csv`, `dots/star_candidates.csv`, and local catalogue CSVs; fitting/statistical interfaces from Task 3.
- Produces: `discover_solutions(paths) -> (selected, inventory)`; `load_solution(record) -> SolutionData`; `catalogues_by_sha256(paths) -> dict`; `compare_associations(baseline, selected, detections, catalogue, gate) -> list[dict]`; `compare_planet_residuals(baseline, selected, candidates, gate) -> list[dict]`; `compare_solution(solution, config) -> StudyResult`.

- [ ] **Step 1: Write failing discovery tests**

Build temporary real JSON/CSV files for two checksums with duplicate successful versions, a newer failed rerun, a deterministic timestamp tie, a malformed record, propagated coordinates, and catalogue-coordinate fallback. Assert one selected record per source hash, exact ranking, every input in inventory, and explicit rejection reasons.

- [ ] **Step 2: Run discovery tests and verify RED**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_study.SolutionDiscoveryTests`

Expected: FAIL because discovery functions do not exist.

- [ ] **Step 3: Implement discovery and strict loading**

Recursively find result products, parse semantic versions without third-party packages, require successful saved cameras and at least 20 fitted rows, select coordinate columns per the design, and preserve every rejection. Derive source groups from detector shape plus normalized source-path family and export the exact group label.

- [ ] **Step 4: Verify discovery GREEN**

Run the command from Step 2; expected PASS.

- [ ] **Step 5: Write failing association-yield tests**

Use real `associate` calls on a controlled catalogue/detection geometry. Assert unchanged detection count, a formerly unmatched edge detection classified as `gained`, a disappearing match as `lost`, a different star for the same detection as `changed`, unchanged matches as `common`, and normalized radial bins. Assert a wrong catalogue checksum and a changed gate are rejected.

- [ ] **Step 6: Implement checksum-authoritative association comparison**

Resolve catalogues only by SHA-256, propagate the complete catalogue to the recorded fitted epoch with existing catalogue machinery, reuse the saved gate, and compare mappings keyed by detection ID and catalogue star ID. Retain baseline and selected residuals and radii for every outcome.

- [ ] **Step 7: Verify association tests GREEN**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_study.AssociationYieldTests`

Expected: all gain/loss/change/common and authority tests pass.

- [ ] **Step 8: Implement and test per-solution orchestration**

Write an integration test with one synthetic saved solution that runs `M0` through `M2`, selects an order, performs robust operational refits, and emits model, fold, and association rows even when one injected high order fails. Implement `compare_solution` and run `cd v12 && uv run --frozen python -m unittest -v test_radial_study`; expected PASS.

- [ ] **Step 9: Write failing fixed-planet edge tests**

Create candidate rows for a major planet and Ceres or Vesta with literal measured pixels and epochs. Assert identity, epoch, detection ID, and gate are unchanged; baseline and selected projections use `planet_vectors`; normalized radius is recorded; an improved residual can cross from outside to inside the saved gate; and a worsened candidate remains visible rather than being discarded.

- [ ] **Step 10: Implement planet residual comparison and verify GREEN**

Read `planet_candidates.csv` plus `planet_epoch.json`, parse candidate epochs with Astropy `Time`, project exact bundled ephemeris vectors through both robust cameras, and classify `improved`, `worsened`, `unchanged`, and gate crossings. Run the complete `test_radial_study` file; expected PASS.

### Task 5: Build the batch command, persistent outputs, and plots

**Files:**
- Create: `v12/scripts/compare_radial_models.py`
- Modify: `v12/radial_study.py`
- Modify: `v12/test_radial_study.py`
- Create: `v12/docs/RADIAL_MODEL_COMPARISON.md`
- Modify: `v12/docs/FEATURE_STATUS.md`

**Interfaces:**
- Consumes: one or more solution roots, v12 catalogue paths, output directory, worker count, maximum order, fold count, and deterministic seed.
- Produces: `solution_inventory.csv`, `model_comparison.csv`, `validation_folds.csv`, `association_yield.csv`, `planet_residual_comparison.csv`, `radial_model_study.json`, `summary.md`, and PNG plots.

- [ ] **Step 1: Write a failing end-to-end CLI test**

Run the command in-process against two synthetic solution directories, one valid and one malformed. Assert exit zero when at least one solution is analyzed; stable row ordering; required CSV columns; JSON configuration/provenance; a failure row for the malformed source; plots derived from numerical rows; wording that distinguishes detected from associated sources; and fixed-identity planet rows preserved whether improved or worsened.

- [ ] **Step 2: Run the CLI test and verify RED**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_study.RadialStudyCliTests`

Expected: FAIL because the script/output writer does not exist.

- [ ] **Step 3: Implement batch execution and atomic output publication**

Use a process pool with deterministic input/result sorting and bounded `--workers`. Write into a temporary sibling directory and rename only after all CSV/JSON/Markdown/PNG products close successfully. Continue after per-image failures. Refuse output paths that would overwrite an input or preserved repository asset.

- [ ] **Step 4: Implement aggregate statistics and plots**

Report raw image counts and group-cluster bootstrap intervals, decision/failure counts by order, median and quartile fitted/validation RMS change, and association outcomes by normalized radius. Plot radial profiles, fitted versus validation changes, delta AICc/BIC, and failure counts without moving any measured/predicted coordinate.

- [ ] **Step 5: Verify CLI GREEN and run all v12 radial tests**

Run: `cd v12 && uv run --frozen python -m unittest -v test_radial_model test_radial_statistics test_radial_study`

Expected: all radial study tests pass.

- [ ] **Step 6: Document invocation and interpretation**

Document exact commands, Gaussian/AICc assumptions, robust operational sensitivity, fixed-association versus association-yield questions, all failure classes, and the rule that no extension becomes the normal default from this experiment alone. Update feature status as implemented study machinery with real-data conclusions pending Task 6.

- [ ] **Step 7: Write a failing 40-label sky-plot regression and implement the v12 display change**

Add a v12 report test with at least 45 eligible catalogue labels and assert the sky overlay renders 40 distinct label texts by default. Change the v12-only `select_labels` default and `write_report_sky_overlay(..., maximum_labels=40)` without changing v11, then run the focused report and Barghini tests GREEN.

### Task 6: Run the complete historical study and record conclusions

**Files:**
- Create from batch output: `v12/docs/radial-model-study/model_comparison.csv`
- Create from batch output: `v12/docs/radial-model-study/association_yield.csv`
- Create from batch output: `v12/docs/radial-model-study/planet_residual_comparison.csv`
- Create from batch output: `v12/docs/radial-model-study/summary.json`
- Modify: `v12/docs/RADIAL_MODEL_COMPARISON.md`
- Modify: `v12/docs/FEATURE_STATUS.md`
- Modify: `v12/SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: all unique suitable solutions under `/home/pth/WORKSHOP/WIDE-FIELD-SOLVER/results` and exact v12 catalogue copies.
- Produces: complete batch evidence, a compact persistent numerical summary, and a recommendation about whether any added order is justified globally or for specific camera groups.

- [x] **Step 1: Run the corrected study over every discoverable historical result**

Run:

```sh
cd v12
uv run --frozen python scripts/compare_radial_models.py \
  /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/results \
  --catalogue data/stars_gaia_dr3_g75.csv \
  --catalogue data/stars_tycho2_mag75.csv \
  --output ../results/radial-model-study-v12-corrected \
  --max-order 5 --fold-count 8 --workers 8 --seed 120924
```

Expected: 432 selected unique sources unless the inventory changed; every selected source has six model rows and an explicit valid/failure state; the process continues after individual failures.

- [x] **Step 2: Audit completeness and numerical consistency**

Independently count unique source hashes, selected rows, per-order rows, validation membership, and association outcomes. Recompute representative RMS, AICc/BIC, Akaike weights, and gained/lost/changed counts from CSV columns and assert agreement with JSON summaries.

- [x] **Step 3: Record complete findings without hiding failures**

Copy the compact per-image model, association, and fixed-planet summaries plus aggregate JSON into `v12/docs/radial-model-study/`. Document model support by camera/source group, absolute and relative RMS changes, bootstrap intervals, failure/worse-prediction cases, edge association gains/losses/changes, major/minor-planet residual changes and gate crossings by radius, and whether the evidence warrants a later default-model proposal.

- [x] **Step 4: Refresh the v12 source manifest**

Run the deterministic v12 manifest updater after all tracked v12 files are present, then run the v12 boundary test to verify every digest and the unchanged v11 snapshot.

- [x] **Step 5: Run focused, complete, and mandated verification**

Run, in order:

```sh
cd v12 && uv run --frozen python -m unittest discover -v
cd .. && uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
git diff --check
git status --short
```

Expected: v12 and root suites pass, the preserved demo passes its regression checker, diff check reports no whitespace errors, and status lists only intentional v12/docs/launcher/boundary changes plus ignored study working products.
