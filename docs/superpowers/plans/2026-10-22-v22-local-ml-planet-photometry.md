# V22 Local and Machine-Learned Planet Photometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent v22 benchmark that selects the simplest validated stellar nuisance correction and applies it cautiously to relative planet photometry.

**Architecture:** Freeze v21, create an independent v22 runtime, and read existing MMTO measurements without changing the database. Separate modules load auditable measurements, construct leakage-safe same-image stellar context, freeze night/star splits, compare local and tabular models, then apply a selected model only if its untouched pseudo-planet test passes.

**Tech Stack:** Python 3.12, NumPy 2.4.4, SciPy 1.17.1, scikit-learn 1.9.1, Matplotlib 3.11.1, SQLite, `unittest`, Bash, uv.

**Spec:** `docs/superpowers/specs/2026-10-22-v22-local-ml-planet-photometry-design.md`

## Global Constraints

- Keep v21 and every earlier runtime byte-for-byte unchanged after recording the v21 boundary.
- Keep blind astrometry, the image-derived photometric zenith, and post-fit metadata separation unchanged.
- Train correction models only on unsaturated ordinary-aperture stellar rows.
- Never use planet measurements, target identity, observing-night identity, sky coordinates, future data, or the target's current magnitude as model features.
- Use raw v21 and v21 `k * X` photometry only as controls; never silently substitute them for an unavailable v22 correction.
- The first benchmark opens the results database and MMTO manifest read-only and runs without network access.
- Preserve any already-finished v21 work in its own commit before recording the v21 boundary; never mix those changes into a v22 implementation commit.
- The fixed selection order is local ensemble, random forest, gradient boosting, then small neural network; the first method passing every validation gate is tested once, and test failure yields `model_unavailable` without trying another method.
- Preserve raw measurements and give every planet-channel row an explicit correction status.

## Review Focus

- A target row leaking into its exposure summary would erase real variability; Task 3 tests exact target exclusion.
- Stars seen on both held-out and training nights could leak identity baselines; Task 3 tests that pseudo-planet identities are absent from model fitting.
- Historical v21 rows lack saved aperture-background values; Task 2 tests that unavailable fields remain missing and never become guessed zeros.
- Sparse or unusual planet positions could trigger unsafe tree extrapolation; Tasks 4 and 5 test support checks and `out_of_domain` status.
- A failed Horizons request must not discard completed photometry; Task 5 tests offline output with unavailable distance normalization.

---

### Task 1: Freeze v21 and establish the independent v22 boundary

**Files:**
- Create: `docs/v21-runtime.json`
- Create: `scripts/prepare_v22_boundary.py`
- Create: `v22/` from the final v21 runtime, excluding `.venv` and `__pycache__`
- Create: `go22.sh`, `go_v0.22.0.sh`, `go_mmto_photometry_v22.sh`
- Create: `test_v22_runtime_boundary.py`
- Modify: `AGENTS.md`, `docs/FEATURE_STATUS.md`
- Modify: `v22/pyproject.toml`, `v22/uv.lock`, `v22/README.md`, `v22/SOURCE_MANIFEST.json`, `v22/scripts/update_v22_manifest.py`

**Interfaces:**
- Produces: solver version `0.22.0`, launchers pinned to `v22/`, a complete v21 boundary hash, and a v22 environment containing `scikit-learn==1.9.1`.

- [ ] **Step 1: Write the failing boundary tests**

```python
def test_v22_is_independent_and_v21_is_frozen():
    assert launcher_version("go22.sh") == "0.22.0"
    assert runtime_hashes("v21") == json_load("docs/v21-runtime.json")["sha256"]

def test_v22_manifest_and_lock_are_complete():
    assert manifest_files("v22") == runtime_files("v22")
    assert locked_version("scikit-learn", "v22/uv.lock") == "1.9.1"
```

- [ ] **Step 2: Run `uv run --frozen python -m unittest -v test_v22_runtime_boundary.py` and verify it fails because the boundary does not exist.**
- [ ] **Step 3: Implement `snapshot_runtime(root: Path, version: str, root_files: tuple[str, ...]) -> dict` in `scripts/prepare_v22_boundary.py`, snapshot the final v21 bytes, copy the runtime, and update only v22 identities and dependency metadata.**
- [ ] **Step 4: Add the three launchers and document that v22 reuses the archive/database but counts only `0.22.0` receipts as v22 solver work.**
- [ ] **Step 5: Run `uv lock --project v22`, regenerate `v22/SOURCE_MANIFEST.json`, and rerun the boundary test to PASS.**
- [ ] **Step 6: Commit only the v22 boundary and documentation with `git commit -m "feat: establish v22 runtime boundary"`.**

### Task 2: Load an auditable read-only stellar and planet data set

**Files:**
- Create: `v22/mmto_differential_data.py`
- Create: `v22/test_mmto_differential_data.py`

**Interfaces:**
- Produces: immutable `RunRecord`, `StellarMeasurement`, `PlanetMeasurement`, and `MeasurementSet` dataclasses.
- Produces: `load_v21_control(directory: Path) -> V21Control`, using `calibration_manifest.json`, `corrected_stellar_photometry.csv`, and the adopted rows in `nightly_extinction_coefficients.csv`.
- Produces: `load_measurements(database: Path, manifest: Path, *, input_solver_version: str = "0.21.0", run_ids: frozenset[str] | None = None) -> MeasurementSet`; the benchmark passes `V21Control.selected_run_ids` so database growth cannot change the population.
- Produces: `write_input_audit(data: MeasurementSet, output: Path) -> None`.

- [ ] **Step 1: Write failing fixture tests for latest-success selection, exact run-ID replay, unique joins, ordinary-aperture filtering, saturation auditing, and read-only database/manifest use.**

```python
def test_loader_keeps_missing_historical_background_missing():
    row = load_fixture().stellar[0]
    assert row.aperture_background_adu is None
    assert "aperture_background_adu" not in row.deployable_features()

def test_non_unique_detection_join_fails_closed():
    with self.assertRaisesRegex(ValueError, "non-unique detection join"):
        load_measurements(duplicate_fixture_db, fixture_manifest)

def test_v21_control_must_describe_the_same_runs():
    with self.assertRaisesRegex(ValueError, "control run mismatch"):
        require_matching_runs(load_v21_control(stale_control_directory), current_measurements)
```

- [ ] **Step 2: Run `uv run --project v22 --frozen python -m unittest -v v22.test_mmto_differential_data` and verify the loader tests fail.**
- [ ] **Step 3: Implement strict joins across `runs`, `stellar_photometry.csv`, `source_photometry.csv`, `star_coordinates.csv`, `dots/star_candidates.csv`, and `dots/detection.json`; join Gaia BP/RP from the catalogue named by each run's catalogue hash.**
- [ ] **Step 4: Implement the v21-control loader, require its selected run IDs to match the benchmark population, and retain only its recorded adopted model.**
- [ ] **Step 5: Load planet rows from `identified_source_photometry.csv` but keep them in a separate tuple that no training API accepts.**
- [ ] **Step 6: Write `input_runs.csv` and `measurement_audit.csv` with every exclusion reason and hashes of both SQLite inputs; prove file hashes and row counts are stable across repeated loads.**
- [ ] **Step 7: Rerun the focused tests to PASS.**
- [ ] **Step 8: Commit with `git commit -m "feat: load v22 differential photometry inputs"`.**

### Task 3: Build leakage-safe context features and frozen splits

**Files:**
- Create: `v22/mmto_differential_features.py`
- Create: `v22/test_mmto_differential_features.py`
- Create: `v22/config/differential_photometry.json`

**Interfaces:**
- Consumes: `MeasurementSet` and `V21Control` from Task 2.
- Produces: `SplitAssignment(night_role, star_role, spatial_block)` and `FeatureTable`.
- Produces: `assign_splits(data: MeasurementSet, *, seed: int = 2201) -> tuple[SplitAssignment, ...]`.
- Produces: `build_feature_table(data: MeasurementSet, control: V21Control, splits: Sequence[SplitAssignment], config: Mapping[str, object]) -> FeatureTable`.
- Produces: `inject_signals(table: FeatureTable, *, seed: int = 2202) -> InjectedFeatureTable`.

- [ ] **Step 1: Write failing split tests for independent deterministic 60/20/20 train/validation/test assignments of whole nights and star identities; validation-star identities never enter training, and test-star identities enter neither training nor validation.**
- [ ] **Step 2: Write failing feature tests proving the target is excluded from all aggregates, comparison residuals use training-night star baselines, and target magnitude/count rate is absent from `deployable_feature_names`.**

```python
def test_target_is_not_its_own_weather_station():
    table = build_fixture_features(target_delta_mag=9.0)
    assert table.target.local_median_256_px == 0.2
    assert "machine_magnitude" not in table.deployable_feature_names
```

- [ ] **Step 3: Define the training target as raw machine magnitude minus that star/channel's training-night median; centre validation/test target series only for metric calculation, never as a feature.**
- [ ] **Step 4: Implement normalized position, radius, azimuth sine/cosine, blind airmass, shape, area, peak-SNR, aperture-radius, exposure, and missing flags; do not synthesize unavailable background fields.**
- [ ] **Step 5: Implement other-star exposure summaries plus robust medians, MADs, and counts at fixed 128, 256, and 512 pixel radii, requiring 12 local or 30 exposure-wide comparison stars.**
- [ ] **Step 6: Implement colour-aware diagnostic features separately from the colour-free deployable feature matrix.**
- [ ] **Step 7: Inject constant, trend, sinusoidal, and isolated-change signals after context construction.**
- [ ] **Step 8: Write `fold_assignments.csv` and `feature_manifest.json`, then rerun focused tests to PASS.**
- [ ] **Step 9: Commit with `git commit -m "feat: build leakage-safe v22 features"`.**

### Task 4: Compare models and enforce simplest-passing selection

**Files:**
- Create: `v22/mmto_differential_models.py`
- Create: `v22/mmto_differential_metrics.py`
- Create: `v22/test_mmto_differential_models.py`
- Create: `v22/test_mmto_differential_metrics.py`

**Interfaces:**
- Consumes: `FeatureTable` and `InjectedFeatureTable` from Task 3.
- Produces: `ValidationResult(name, metrics, gate_status, fitted_pipeline)` without final-test metrics.
- Produces: `fit_and_validate_candidates(table: FeatureTable, config: Mapping[str, object]) -> tuple[ValidationResult, ...]`.
- Produces: `select_simplest_passing(results: Sequence[ValidationResult]) -> ValidationResult | None`.
- Produces: `confirm_on_test(selected: ValidationResult, table: FeatureTable, config: Mapping[str, object]) -> ConfirmedModel | None`, which evaluates exactly one selected candidate exactly once.

- [ ] **Step 1: Write failing local-ensemble tests: use the smallest of 128/256/512 pixels containing at least 12 neighbours, otherwise the exposure median with at least 30 stars, otherwise return `insufficient_local_stars`.**
- [ ] **Step 2: Implement model adapters and tune only with whole-night grouped inner folds: random forest uses 300 trees, `max_features=0.7`, and `min_samples_leaf` in `{8,20}`; histogram gradient boosting uses 300 iterations, learning rate 0.05, L2 1.0, and leaf count in `{15,31}`; MLP uses hidden layers in `{(32,),(32,16)}`, alpha in `{1e-4,1e-3}`, 500 iterations, and early stopping. Fit median imputation inside each fold for random forest/MLP and standardization inside each MLP fold.**
- [ ] **Step 3: Write failing gate tests for at least 5% MAE and robust-scatter improvement over both controls in every channel, positive 95% bootstrap improvement, no greater than 2% degradation in eligible planet-like strata, and median injected-signal attenuation below 5%. For every available diagnostic feature whose control slope is significant, require the corrected absolute robust slope to be at least 5% smaller than both controls; when both controls are consistent with zero, require the corrected 95% interval to include zero. Mark `out_of_domain` outside either the 0.5--99.5% univariate training envelope or the 99.5% training nearest-neighbour distance.**
- [ ] **Step 4: Implement 2,000 target-group bootstrap resamples, residual-trend reports for every available diagnostic feature, and empirical 90% prediction intervals from grouped validation residuals.**
- [ ] **Step 5: Write and pass the fixed-order selection test.**

```python
def test_simplest_passing_model_wins_without_test_reselection():
    results = [failed("local"), passed("random_forest"), passed("gradient_boosting")]
    assert select_simplest_passing(results).name == "random_forest"
    assert confirm_on_test(results[1], failing_test_table, config) is None
    assert final_test_evaluation_count() == 1
```

- [ ] **Step 6: Run both focused suites to PASS and commit with `git commit -m "feat: select simplest validated correction"`.**

### Task 5: Run the benchmark and apply a confirmed model to planets

**Files:**
- Create: `v22/mmto_differential_benchmark.py`
- Create: `v22/mmto_planet_relative_photometry.py`
- Create: `v22/test_mmto_differential_benchmark.py`
- Create: `v22/test_mmto_planet_relative_photometry.py`
- Create: `scripts/run_v22_photometry_benchmark.py`
- Create: `run_v22_photometry_benchmark.sh`

**Interfaces:**
- Produces: `run_benchmark(database: Path, manifest: Path, v21_control: Path, output: Path, config: Path, *, run_ids: Path | None = None) -> BenchmarkSummary`.
- Produces: `apply_to_planets(model: ConfirmedModel | None, planets: Sequence[PlanetMeasurement], context: FeatureTable) -> tuple[CorrectedPlanetMeasurement, ...]`.
- Produces: all CSV, JSON, model-hash, and PDF products named in the spec.

- [ ] **Step 1: Write failing end-to-end fixture tests for a known spatial/time nuisance field, one deliberately failed gate, stable output hashes, and refusal to overwrite a nonempty output directory.**
- [ ] **Step 2: Implement the CLI and summary writer so validation selects one candidate, the untouched test only confirms or rejects it, and rejection suppresses corrected planet values while retaining raw rows.**
- [ ] **Step 3: Write failing planet tests for `corrected`, `insufficient_local_stars`, `out_of_domain`, `invalid_measurement`, and `model_unavailable`; assert raw and v21-control values remain present for every status.**
- [ ] **Step 4: Implement planet application using stellar-only context and serialize the confirmed preprocessing/model objects with SHA-256 provenance.**
- [ ] **Step 5: Render `residual_diagnostics.pdf`, `model_comparison.pdf`, `signal_recovery.pdf`, and `planet_relative_lightcurves.pdf`, with raw, v21 control, and v22 values visibly distinguished.**
- [ ] **Step 6: Keep observer-distance normalization optional and separate; when cached ephemeris is absent, write `distance_unavailable` without a network request or loss of photometry.**
- [ ] **Step 7: Run focused tests to PASS and commit with `git commit -m "feat: benchmark and apply v22 planet correction"`.**

### Task 6: Integrate the v22 pipeline, verify preservation, and run the real benchmark

**Files:**
- Create: `scripts/run_mmto_photometry_pipeline_v22.py`
- Create: `test_run_mmto_photometry_pipeline_v22.py`
- Modify: `go_mmto_photometry_v22.sh`
- Modify: `v22/README.md`, `v22/HANDOFF.md`, `v22/SOURCE_MANIFEST.json`
- Modify: `docs/FEATURE_STATUS.md`
- Create: `docs/V22_DIFFERENTIAL_PHOTOMETRY.md`

**Interfaces:**
- Consumes: the benchmark CLI from Task 5 after ordinary v22 solving/post-processing.
- Produces: a pipeline summary that records benchmark gates, selected method, correction availability, and every figure path.

- [ ] **Step 1: Write failing orchestration tests asserting the benchmark runs after raw stellar/planet products, receives read-only input paths, and a failed scientific gate does not fail the pipeline operationally.**
- [ ] **Step 2: Implement the v22 stage command and final figure listing without changing the v21 pipeline.**
- [ ] **Step 3: Run all v22-focused tests and `git diff --check`.**
- [ ] **Step 4: Regenerate `v22/SOURCE_MANIFEST.json`, rerun both v21 and v22 boundary tests, and prove every frozen runtime hash still matches.**
- [ ] **Step 5: Run `uv run --frozen python -m unittest discover -v` and require PASS.**
- [ ] **Step 6: Run the root demo and `v22/demo.sh` into new unique output directories and require their regression checks to PASS.**
- [ ] **Step 7: Run the benchmark read-only against `results/stars.sqlite` and `raw_allsky_samples/manifest.sqlite`; inspect all four PDFs and the gate decision before accepting a planet correction.**
- [ ] **Step 8: Document the observed result without changing thresholds, commit the integration, and leave bulk acquisition off unless separately requested.**
