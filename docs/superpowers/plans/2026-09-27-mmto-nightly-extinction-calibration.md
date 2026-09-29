# MMTO Nightly Extinction Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only MMTO sidecar calibration that derives per-image stellar extinction fits, nightly per-channel median coefficients, catalogue-referenced stellar magnitudes, and nightly-calibrated planet plots.

**Architecture:** A pure numerical module owns selection, fitting, aggregation, sensitivities, and magnitude correction. A separate CLI owns manifest/database reads, audit tables, plots, and immutable output directories; the existing planet plotter consumes its small image-solution tables explicitly and never falls back to raw magnitudes in the nightly-calibrated product.

**Tech Stack:** Python 3.12, standard-library `sqlite3`/`csv`/`json`/`dataclasses`, NumPy, Matplotlib, Astropy where already used, Bash launchers, `unittest`, uv locked environments.

**Spec:** `docs/superpowers/specs/2026-09-27-mmto-nightly-extinction-calibration-design.md`

## Global Constraints

- Keep `stars.sqlite` read-only; write only a new sidecar output directory.
- Preserve root legacy and complete frozen v4 through v11/v8a runtimes and launchers.
- Use saved blind image-derived airmass; do not recompute stellar airmass from MMTO site/time metadata.
- Use stars only for `Z`, `k`, weights, nightly medians, and fixed-slope zero points; planets are downstream targets only.
- The adopted reference is channel-specific unweighted OLS with catalogue magnitude `< 4.0`, at least 10 clean observations per star/night, `X <= 5`, at least 30 stars, `Delta X >= 1.0`, and at least 10 accepted images/night.
- Weighted bright-star and magnitude `4.0 <= m < 5.0` solutions remain sensitivity products and cannot replace the reference result.
- Compute machine magnitude only as `-2.5 log10(count_rate_adu_per_s)` from positive unsaturated ordinary-aperture rates.
- Select the latest successful run per `(source_sha256, catalogue_sha256)` before photometric quality cuts.
- Missing calibration must produce an explicit exclusion; nightly-calibrated consumers never fall back to the legacy same-image fit or raw machine magnitude.
- Preserve all existing modified/untracked files and inspect overlap before every edit or stage operation.
- Before every commit run `uv run --frozen python -m unittest discover -v` and run `./demo.sh` into a fresh `mktemp`-derived output directory; never overwrite the existing `results/check-unique-name` evidence.

## Review Focus

- Conflicting or absent manifest times: fail the affected input explicitly; test in Task 3.
- A newer successful rerun with bad photometry: select it before quality cuts rather than reviving the older row; test in Task 3.
- Saturation in a different channel: retain a clean fitted channel while excluding only the saturated channel; test in Task 1.
- Partial nights, faint stars, and `X > 5`: retain audit rows but do not relax adopted gates; test in Tasks 1 and 4.
- Missing/mismatched sidecar keys for a planet: exclude the point without legacy/raw fallback; test in Task 5.

---

### Task 1: Pure measurement model and reference-star selection

**Files:**
- Create: `scripts/nightly_extinction.py`
- Create: `test_nightly_extinction.py`

**Interfaces:**
- Produces: `CalibrationConfig`, `StellarMeasurement`, `LineFit`, and `ImageFit` frozen dataclasses.
- Produces: `machine_magnitude(count_rate_adu_per_s: float) -> float`.
- Produces: `select_reference_star_ids(measurements: Sequence[StellarMeasurement], config: CalibrationConfig) -> frozenset[tuple[str, str]]`, keyed by `(catalogue_sha256, star_id)`.
- Produces: `fit_image_ols(measurements: Sequence[StellarMeasurement], reference_star_ids: AbstractSet[tuple[str, str]], config: CalibrationConfig, *, model: str = "reference_ols") -> ImageFit`.

- [ ] **Step 1: Write failing model and selection tests**

Add tests named `test_machine_magnitude_uses_count_rate_not_flux`, `test_reference_selection_requires_ten_clean_bright_observations`, and `test_channel_saturation_excludes_only_that_channel`. Assert the exact config defaults from the spec and that a magnitude `4.0` row is outside the strict `< 4.0` reference population.

- [ ] **Step 2: Run the focused tests and confirm the expected import/interface failures**

Run: `uv run --project v8a --frozen python -m unittest -v test_nightly_extinction`

Expected: FAIL because `scripts.nightly_extinction` or the named interfaces do not yet exist.

- [ ] **Step 3: Implement the dataclasses, finite-value checks, count-rate magnitude, and stable-star selection**

`CalibrationConfig` defaults must be `max_catalogue_magnitude=4.0`, `min_observations_per_star=10`, `max_reference_airmass=5.0`, `min_stars_per_image=30`, `min_airmass_span=1.0`, and `min_images_per_night=10`. Retain exclusion reasons separately from immutable valid `StellarMeasurement` objects.

- [ ] **Step 4: Write and run failing OLS tests**

Add `test_image_ols_recovers_known_intercept_and_slope` and `test_image_ols_reports_insufficient_count_and_airmass_span`. Use synthetic `delta_m = -6.0 + 0.24 X`; assert slope/intercept to 12 places and exact status strings.

Run: `uv run --project v8a --frozen python -m unittest -v test_nightly_extinction`

Expected: selection tests PASS; OLS tests FAIL because the fitter is incomplete.

- [ ] **Step 5: Implement `fit_image_ols` with covariance, RMS, residuals, counts, range, and fixed acceptance gates**

Use `numpy.linalg.lstsq` on `[1, X]`. The adopted fit includes only selected reference stars at `X <= 5`; return a structured insufficient result rather than reducing a gate.

- [ ] **Step 6: Run focused and global pre-commit verification**

Run:

```sh
uv run --project v8a --frozen python -m unittest -v test_nightly_extinction
uv run --frozen python -m unittest discover -v
task1_demo_root=$(mktemp -d /tmp/wfs-nightly-task1.XXXXXX)
./demo.sh --output "$task1_demo_root/demo"
```

Expected: all tests PASS; demo reports `Baseline PASS`.

- [ ] **Step 7: Commit Task 1 only**

```sh
git add scripts/nightly_extinction.py test_nightly_extinction.py
git commit -m "feat: add nightly extinction reference fits"
```

### Task 2: Night aggregation, fixed zero points, and sensitivity fits

**Files:**
- Modify: `scripts/nightly_extinction.py`
- Modify: `test_nightly_extinction.py`

**Interfaces:**
- Consumes: Task 1 dataclasses and `fit_image_ols`.
- Produces: `NightCoefficient`, `ImageZeroPoint`, and `NightCalibrationResult` frozen dataclasses.
- Produces: `calibrate_night(measurements: Sequence[StellarMeasurement], config: CalibrationConfig) -> NightCalibrationResult`.
- Produces: `correct_magnitude(machine_mag: float, zero_point_mag: float, extinction_mag_per_airmass: float, airmass: float) -> float`.
- Produces sensitivity results named `bright_weighted` and `faint_weighted`; `NightCalibrationResult.adopted_model` must remain `reference_ols`.

- [ ] **Step 1: Write failing aggregation and correction tests**

Add `test_nightly_median_tracks_image_extinction_while_fixed_zero_points_track_transparency`, `test_night_requires_ten_accepted_images_without_fallback`, and `test_unknown_intrinsic_object_is_corrected_from_stellar_solution`. Construct ten images with known varying `k_i`, independent `Z_i`, and a planet machine magnitude; assert the ordinary median and the correction formula exactly.

- [ ] **Step 2: Run tests and confirm aggregation interfaces fail**

Run: `uv run --project v8a --frozen python -m unittest -v test_nightly_extinction`

Expected: new tests FAIL on missing interfaces.

- [ ] **Step 3: Implement nightly median and fixed-slope zero-point refits**

Record per-image `k_i`, formal fit uncertainty, ordinary median, scaled MAD, range, count, and fixed-night-slope `Z_i`. Do not divide scaled MAD by square root of image count.

- [ ] **Step 4: Write failing sensitivity-isolation tests**

Add `test_weighted_and_faint_sensitivities_never_replace_reference`, `test_weight_floor_and_cap_prevent_single_star_domination`, and `test_full_airmass_fit_is_diagnostic_only`. Assert that changing sensitivity data cannot change adopted `k_night` or corrected magnitudes.

- [ ] **Step 5: Implement one deterministic repeatability-weight pass and both sensitivity fits**

Estimate per-star scatter from robust night-centred reference residuals; document and save the finite positive floor/cap. Fit weighted bright and weighted `4 <= m < 5` extensions once, with no iterative adoption logic.

- [ ] **Step 6: Run focused and global pre-commit verification**

Run:

```sh
uv run --project v8a --frozen python -m unittest -v test_nightly_extinction
uv run --frozen python -m unittest discover -v
task2_demo_root=$(mktemp -d /tmp/wfs-nightly-task2.XXXXXX)
./demo.sh --output "$task2_demo_root/demo"
```

Expected: all tests PASS; demo reports `Baseline PASS`.

- [ ] **Step 7: Commit Task 2 only**

```sh
git add scripts/nightly_extinction.py test_nightly_extinction.py
git commit -m "feat: aggregate nightly stellar extinction"
```

### Task 3: Read-only MMTO database and manifest loader

**Files:**
- Create: `scripts/calibrate_nightly_extinction.py`
- Create: `test_calibrate_nightly_extinction.py`

**Interfaces:**
- Consumes: Task 1 `StellarMeasurement`; `allsky_download.cadence.observing_night_date`; the canonical MMTO `Site` from `sources.json`.
- Produces: `ManifestEntry` and `LoadedCalibrationData` frozen dataclasses.
- Produces: `read_mmto_manifest(path: Path) -> dict[str, ManifestEntry]`, supporting the real downloader SQLite `downloads` table and the existing light-curve CSV form.
- Produces: `load_mmto_calibration_data(database: Path, manifest: Path) -> LoadedCalibrationData`.

- [ ] **Step 1: Write failing manifest-format tests**

Create temporary SQLite and CSV manifests. Add `test_sqlite_manifest_accepts_only_verified_mmto_skycam_rows`, `test_csv_manifest_retains_existing_hash_time_convention`, and `test_conflicting_hash_times_fail_explicitly`.

- [ ] **Step 2: Run the loader tests and confirm missing interfaces fail**

Run: `uv run --project v8a --frozen python -m unittest -v test_calibrate_nightly_extinction`

Expected: FAIL on missing module/interfaces.

- [ ] **Step 3: Implement manifest loading and Arizona local-noon night assignment**

For SQLite require `source_id='mmto'`, `camera_id='mmto-skycam'`, `download_status='downloaded'`, `validation_status='verified'`, nonempty SHA-256, and timezone-aware `observed_utc`. For CSV preserve hostname/path/hash checks from `plot_star_lightcurves.read_times`.

- [ ] **Step 4: Write failing database snapshot, deduplication, and audit tests**

Add fixtures for successful/failed/duplicate runs and `stellar_photometry.csv` measurements. Pin the Review Focus cases: latest success chosen before quality, missing manifest hash audited, clean R retained when G is saturated, malformed JSON audited, and database bytes unchanged after loading.

- [ ] **Step 5: Implement the read-only snapshot query and audit-row construction**

Open with URI `mode=ro`, set `PRAGMA query_only=ON`, begin one transaction, and roll it back after materializing data. Compute channel magnitudes from count rates; never use saved flux-based `R_mag/G_mag/B_mag` values.

- [ ] **Step 6: Run focused and global pre-commit verification**

Run:

```sh
uv run --project v8a --frozen python -m unittest -v test_calibrate_nightly_extinction
uv run --frozen python -m unittest discover -v
task3_demo_root=$(mktemp -d /tmp/wfs-nightly-task3.XXXXXX)
./demo.sh --output "$task3_demo_root/demo"
```

Expected: all tests PASS; demo reports `Baseline PASS`.

- [ ] **Step 7: Commit Task 3 only**

```sh
git add scripts/calibrate_nightly_extinction.py test_calibrate_nightly_extinction.py
git commit -m "feat: load MMTO extinction calibration data"
```

### Task 4: Immutable sidecar products, diagnostics, and launcher

**Files:**
- Modify: `scripts/calibrate_nightly_extinction.py`
- Modify: `test_calibrate_nightly_extinction.py`
- Create: `calibrate_mmto_extinction.sh`
- Create: `test_calibrate_mmto_extinction_launcher.py`

**Interfaces:**
- Consumes: `LoadedCalibrationData` and `calibrate_night`.
- Produces: `write_calibration_outputs(data: LoadedCalibrationData, output: Path, config: CalibrationConfig) -> dict[str, object]`.
- Produces the exact sidecar files named in the approved spec, including `image_zero_points.csv`, which is the planet consumer boundary.
- Produces CLI arguments `--database`, `--manifest`, `--output`, and fixed-default reporting; science thresholds may be exposed only as explicit advanced overrides recorded in provenance.

- [ ] **Step 1: Write failing output-schema and overwrite-safety tests**

Add `test_writer_creates_complete_sidecar_and_diagnostics`, `test_insufficient_night_keeps_audit_rows_without_corrected_values`, `test_faint_and_high_airmass_rows_are_audited_not_adopted`, and `test_nonempty_output_is_never_overwritten`. Assert deterministic CSV headers and manifest formula strings.

- [ ] **Step 2: Run output tests and confirm they fail before implementation**

Run: `uv run --project v8a --frozen python -m unittest -v test_calibrate_nightly_extinction`

Expected: loader tests PASS; new writer tests FAIL.

- [ ] **Step 3: Implement CSV/JSON writers and PNG/PDF diagnostics**

Write all rows in deterministic `(night, channel, utc_mid, source_sha256, star_id)` order. Plot `k_i`/`Z_i` versus UTC, nightly median/MAD, OLS-versus-sensitivity differences, residuals versus airmass, scatter versus magnitude, and calibrator counts.

- [ ] **Step 4: Write failing CLI and launcher tests**

Assert SQLite-manifest defaults, explicit overrides from another working directory, new timestamped output by default, no overwrite, and a console summary that distinguishes calibrated/insufficient nights.

- [ ] **Step 5: Implement `main(argv=None)` and `calibrate_mmto_extinction.sh`**

Default database to the same host-aware results location as MMTO light curves and default manifest to `raw_allsky_samples/manifest.sqlite` when using repository-local results. The launcher passes all user overrides without altering thresholds silently.

- [ ] **Step 6: Run focused and global pre-commit verification**

Run:

```sh
uv run --project v8a --frozen python -m unittest -v test_nightly_extinction test_calibrate_nightly_extinction test_calibrate_mmto_extinction_launcher
uv run --frozen python -m unittest discover -v
task4_demo_root=$(mktemp -d /tmp/wfs-nightly-task4.XXXXXX)
./demo.sh --output "$task4_demo_root/demo"
```

Expected: all tests PASS; demo reports `Baseline PASS`.

- [ ] **Step 7: Commit Task 4 only**

```sh
git add scripts/calibrate_nightly_extinction.py test_calibrate_nightly_extinction.py \
  calibrate_mmto_extinction.sh test_calibrate_mmto_extinction_launcher.py
git commit -m "feat: write MMTO extinction sidecar"
```

### Task 5: Consume nightly stellar calibration in planet photometry

**Files:**
- Modify: `scripts/plot_planet_photometry.py`
- Modify: `test_plot_planet_photometry.py`
- Modify: `plot_ALL_planets.sh`
- Modify: `test_plot_all_planets_launcher.py`

**Interfaces:**
- Consumes: `nightly_extinction_coefficients.csv` and `image_zero_points.csv` from Task 4.
- Produces: `load_nightly_image_calibrations(directory: Path) -> dict[tuple[str, str, str, str], dict[str, object]]`, keyed by `(source_sha256, catalogue_sha256, night, channel)`.
- Produces: `write_nightly_stellar_calibrated_distance_outputs(...)` and CLI mode `--nightly-stellar-calibrated-distance-corrected`, requiring `--nightly-calibration DIR`.
- Produces fields `nightly_extinction_night`, `nightly_extinction_mag_per_airmass`, `nightly_extinction_scaled_mad`, `nightly_zero_point_mag`, `nightly_stellar_calibrated_magnitude`, `nightly_stellar_calibrated_distance_magnitude`, `nightly_calibration_status`, and `nightly_calibration_source`.

- [ ] **Step 1: Re-read and preserve the current untracked planet files before editing**

Run `git status --short`, `sha256sum` each untracked target, inspect each complete file, and confirm existing focused tests pass. Do not reset, replace, or reconstruct these files from another version.

- [ ] **Step 2: Write failing sidecar-load and correction tests**

Add `test_nightly_loader_requires_unique_matching_image_channel`, `test_planet_uses_star_only_nightly_k_and_fixed_image_zero_point`, `test_missing_sidecar_match_has_no_legacy_or_raw_fallback`, and `test_distance_correction_is_applied_after_nightly_stellar_calibration`. Include a planet fixture with no intrinsic/catalogue magnitude.

- [ ] **Step 3: Run planet tests and confirm only the new cases fail**

Run: `uv run --project v8a --frozen python -m unittest -v test_plot_planet_photometry`

Expected: existing tests PASS; new nightly-sidecar tests FAIL.

- [ ] **Step 4: Implement the loader, join, corrected writer, figure, and CLI mode**

Add `catalogue_sha256` to loaded/exported planet provenance. Keep the legacy same-image calibrated mode available and distinctly named, but never invoke it as fallback from the nightly mode. Keep raw magnitude only as an audit column.

- [ ] **Step 5: Update the all-planets launcher test, then the launcher**

Add required `--nightly-calibration DIR`. Replace the third per-channel product in `plot_ALL_planets.sh` with nightly stellar-calibrated distance-corrected output while preserving raw and distance-only diagnostic products. Assert nine invocations total and explicit sidecar propagation for the nightly call.

- [ ] **Step 6: Run focused and global pre-commit verification**

Run:

```sh
uv run --project v8a --frozen python -m unittest -v \
  test_plot_planet_photometry test_plot_all_planets_launcher
uv run --frozen python -m unittest discover -v
task5_demo_root=$(mktemp -d /tmp/wfs-nightly-task5.XXXXXX)
./demo.sh --output "$task5_demo_root/demo"
```

Expected: all tests PASS; demo reports `Baseline PASS`.

- [ ] **Step 7: Inspect the complete diff before committing overlapping files**

Compare every edited planet/launcher file with the Step 1 hashes and complete-file inspection, and confirm all prior behavior/tests remain present. Stage only the four named files.

- [ ] **Step 8: Commit Task 5**

```sh
git add scripts/plot_planet_photometry.py test_plot_planet_photometry.py \
  plot_ALL_planets.sh test_plot_all_planets_launcher.py
git commit -m "feat: apply nightly extinction to planet photometry"
```

### Task 6: Documentation, real-data generation, and final scientific audit

**Files:**
- Create: `docs/MMTO_NIGHTLY_EXTINCTION.md`
- Modify: `REFERENCE.md`
- Modify: `scripts/MMTO_LIGHTCURVES.md`
- Modify: `docs/FEATURE_STATUS.md` if present at execution time
- Produce: new timestamped directories below `results/nightly-extinction/` and `results/planet-plots-all-*` (ignored scientific outputs, never committed)

**Interfaces:**
- Consumes: the completed calibration launcher, `results/stars.sqlite`, `raw_allsky_samples/manifest.sqlite`, and the completed planet launcher.
- Produces: operator instructions, formula/passband limitations, audit-field descriptions, and inspectable current MMTO products.

- [ ] **Step 1: Document the repeatable workflow and scientific limitations**

Include exact commands, sidecar file meanings, catalogue/channel mismatch, `X <= 5`, OLS authority, sensitivity-only weighting, incomplete-night behavior, read-only database guarantee, and the rule that planet magnitudes never train calibration.

- [ ] **Step 2: Run the calibration against the accumulated local MMTO data**

Run:

```sh
./calibrate_mmto_extinction.sh \
  --database results/stars.sqlite \
  --manifest raw_allsky_samples/manifest.sqlite \
  --output results/nightly-extinction/20260927-first-reference
```

Expected: successful nights produce R/G/B image fits, nightly medians, fixed zero points, corrected stellar rows, and diagnostics; incomplete nights remain explicitly insufficient.

- [ ] **Step 3: Audit numerical and visual outputs before planet plotting**

Check that adopted calibrators are `< 4`, `N >= 10`, `X <= 5`; accepted images have `N >= 30` and `Delta X >= 1`; nights have at least ten image fits; weighted/faint models never supply adopted fields. Inspect all channel `k(t)`/`Z(t)` plots and record material channel/night anomalies in the documentation.

- [ ] **Step 4: Generate nightly-corrected planet products**

Run:

```sh
./plot_ALL_planets.sh \
  --database results/stars.sqlite \
  --nightly-calibration results/nightly-extinction/20260927-first-reference \
  --output results/planet-plots-all-20260927-nightly
```

Expected: nightly-corrected planet CSV/PNG/PDF products use catalogue-referenced magnitude; missing calibration is audited, never plotted raw.

- [ ] **Step 5: Run final verification from a clean command record**

Run:

```sh
uv run --project v8a --frozen python -m unittest -v \
  test_nightly_extinction test_calibrate_nightly_extinction \
  test_calibrate_mmto_extinction_launcher test_plot_planet_photometry \
  test_plot_all_planets_launcher test_plot_star_lightcurves
uv run --frozen python -m unittest discover -v
final_demo_root=$(mktemp -d /tmp/wfs-nightly-final.XXXXXX)
./demo.sh --output "$final_demo_root/demo"
git diff --check
```

Expected: all tests PASS, demo reports `Baseline PASS`, no whitespace errors, and frozen-runtime tests remain unchanged.

- [ ] **Step 6: Commit documentation and any final focused corrections**

```sh
git add docs/MMTO_NIGHTLY_EXTINCTION.md REFERENCE.md scripts/MMTO_LIGHTCURVES.md
test ! -f docs/FEATURE_STATUS.md || git add docs/FEATURE_STATUS.md
git commit -m "docs: describe nightly extinction calibration"
```

- [ ] **Step 7: Final status and provenance audit**

Run `git status --short --branch` and `git log --oneline -8`. Confirm ignored generated results exist, `stars.sqlite` checksum/mtime is unchanged by the calibration run, no preserved version files changed, and all pre-existing unrelated working-tree changes are still present.
