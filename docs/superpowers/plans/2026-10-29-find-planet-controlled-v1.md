# Find Planet Controlled v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `go_find_planet_controlled_v1.sh`, which converts the pinned MMTO Mars answer-key associations into a sealed anonymous `Object A` line-of-sight dataset, fits bound heliocentric orbit families without using Mars predictions, evaluates whole-night held-out predictions, and writes uncertainty-aware figures and tables.

**Architecture:** A new, self-contained `find_planet_v1/` runtime reads the pinned audit and exact run receipts read-only, inverts each saved authoritative Barghini camera to an inertial direction, constructs MMTO/Earth observer states through an Earth-only ERFA path, and performs systematic-ranging plus robust differential correction.  Reporting and sealing are downstream of the identity-free fitter; the answer-key selection record remains separate from the anonymous fit input.

**Tech Stack:** Python 3.12, NumPy 2.4.4, SciPy 1.17.1, Astropy 7.2.0/ERFA, Matplotlib 3.11.1, SQLite, `unittest`, Bash, uv.

**Spec:** `docs/superpowers/specs/2026-10-29-find-planet-v1-design.md`

## Global Constraints

- Create only the new `find_planet_v1/` runtime, `go_find_planet_controlled_v1.sh`, controlled-v1 documentation and fresh generated output directories; do not delete, rename, overwrite or repoint any existing file that works now.
- Never modify `go.sh`, `go4.sh` through `go23.sh`, their version-specific aliases, any `go_mmto_*` launcher, `v4/` through `v23/`, historical examples/references, raw MMTO files, `results/stars.sqlite`, `raw_allsky_samples/manifest.sqlite`, or any `docs/*-runtime.json` manifest.
- Read canonical databases and MMTO inputs read-only.  Every generated run uses a new `results/find-planet-v1/<UTC-run-id>/` directory and refuses an existing output path.
- The controlled selection is explicitly non-blind.  The identity-free fitter must receive no planet name, predicted coordinate, known distance, known element or Horizons quantity.
- The v1 reference audit is `results/photometry-runs/v23-20261027T050447Z/planet-empirical-extinction/B/planet_only_airmass_correction_audit.csv`, SHA-256 `e0f445e044382369aa4a468a53900b1192cd7859389b9c388dd00c8633be6924`.
- Use the exact `run_id` in each selected audit row.  Do not substitute a newer receipt for the same image.
- Convert verified exposure midpoint UTC to TDB.  Obtain heliocentric Earth state only through ERFA `epv00`; the controlled fitter runtime contains no general planetary kernel.
- Fit a heliocentric Cartesian state, propagate with Sun-only two-body dynamics, include topocentric MMTO position and iterative one-way light time, and compute two-dimensional tangent-plane residuals.
- Primary directional uncertainty is isotropic `max(1 arcmin, saved stellar-only fit RMS)`; half- and double-sigma runs are sensitivity checks only.
- Withhold every fifth chronological usable observing night before fitting.  Evaluate the orbit, fixed-direction baseline and constant-angular-velocity baseline on exactly the same held-out nights.
- Retain and export every selected measurement and every weight/exclusion reason.  Never move centroids or plotted measured positions.
- Report unresolved/rank-deficient elements honestly.  Optimizer completion alone is not scientific success.
- Keep `find_planet_v1/uv.lock` committed.
- Before any commit run the task-specific tests; before completion also run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-unique-name`.

## Review Focus

- A selected audit row whose run receipt is missing, duplicated, failed or has a different source SHA must stop extraction with an audited error, never fall back to another run.  Task 2 tests this.
- Camera parameters near the detector edge or with integrated-refraction metadata must invert measured pixels without using predicted planet coordinates and must round-trip within the numeric tolerance.  Task 3 tests this.
- UTC/TDB and topocentric observer-state mistakes can mimic orbital curvature; Task 4 compares ERFA/Astropy transformations at multiple epochs and verifies no general ephemeris call.
- Short-arc ranging may yield multiple or rank-deficient bound solutions; Tasks 6 and 7 retain distinct minima and emit unresolved intervals instead of selecting by Mars likeness.
- A run interrupted after products begin must not leave an apparently valid seal or overwrite an earlier run; Task 8 tests atomic sealing and existing-output refusal.

---

## File structure

- `go_find_planet_controlled_v1.sh`: stable root entry point for the controlled experiment.
- `find_planet_v1/pyproject.toml`, `find_planet_v1/uv.lock`: independent pinned runtime.
- `find_planet_v1/source-manifest.json`: hashes and roles for runtime source/data files.
- `find_planet_v1/find_planet/__init__.py`: package version only.
- `find_planet_v1/find_planet/types.py`: immutable observation, observer-state, orbit-state, fit and score dataclasses.
- `find_planet_v1/find_planet/provenance.py`: hashing, read-only SQLite opening, source-manifest and output-path guards.
- `find_planet_v1/find_planet/extract_controlled.py`: pinned answer-key selection, exact-receipt lookup and anonymous table creation.
- `find_planet_v1/find_planet/barghini.py`: local, documented inverse of the saved Barghini camera model.
- `find_planet_v1/find_planet/observer.py`: UTC/TDB conversion, ERFA Earth state and MMTO topocentre.
- `find_planet_v1/find_planet/geometry.py`: unit-vector, tangent-plane and light-time geometry.
- `find_planet_v1/find_planet/dynamics.py`: Sun-only propagation and state/element conversion.
- `find_planet_v1/find_planet/ranging.py`: deterministic admissible systematic-ranging seeds.
- `find_planet_v1/find_planet/fitting.py`: robust differential correction and orbit-family clustering.
- `find_planet_v1/find_planet/evaluate.py`: night split, baselines, held-out scores, covariance and bootstrap.
- `find_planet_v1/find_planet/report.py`: CSV/JSON products and required plots.
- `find_planet_v1/find_planet/seal.py`: immutable manifest and seal verification.
- `find_planet_v1/find_planet/controlled_cli.py`: orchestration and exit/status semantics.
- `find_planet_v1/tests/`: focused unit, integration, leakage and synthetic-orbit tests.
- `find_planet_v1/README.md`: scientific scope, commands, output interpretation and limitations.

### Task 1: Independent runtime, preservation guard and launcher

**Files:**
- Create: `find_planet_v1/pyproject.toml`
- Create: `find_planet_v1/uv.lock`
- Create: `find_planet_v1/find_planet/__init__.py`
- Create: `find_planet_v1/find_planet/provenance.py`
- Create: `find_planet_v1/tests/test_runtime_boundary.py`
- Create: `go_find_planet_controlled_v1.sh`

**Interfaces:**
- Produces: `find_planet.__version__ == "1.0.0"`; `sha256_file(path: Path) -> str`; `open_sqlite_read_only(path: Path) -> sqlite3.Connection`; `new_output_directory(results_root: Path, run_id: str) -> Path`; launcher forwarding arguments to `python -m find_planet.controlled_cli` under the independent frozen project.

- [ ] **Step 1: Write failing runtime-boundary tests**

Add tests named `test_database_is_opened_read_only`, `test_existing_output_directory_is_refused`, `test_launcher_uses_find_planet_v1_frozen_project`, and `test_frozen_runtime_paths_are_not_launcher_targets`.  Assert a write through the returned SQLite connection fails, an existing output raises `FileExistsError`, and the launcher contains `uv run --project "$repo/find_planet_v1" --frozen` without references to `v23/run.sh` or another existing launcher.

- [ ] **Step 2: Run the boundary tests and verify failure**

Run: `uv run --project v23 --frozen python -m unittest find_planet_v1/tests/test_runtime_boundary.py -v`

Expected: import/file failures because the runtime and launcher do not exist.

- [ ] **Step 3: Create the minimal runtime and preservation utilities**

Pin Python `>=3.12,<3.13` and the four dependencies listed in the plan header.  Implement the produced interfaces.  `new_output_directory` must call `Path.mkdir(parents=True, exist_ok=False)`.  The launcher must use `set -euo pipefail`, unset `VIRTUAL_ENV`, and default only its results root to `results/find-planet-v1`.

- [ ] **Step 4: Generate and freeze the independent lockfile**

Run: `uv lock --project find_planet_v1`

Expected: `find_planet_v1/uv.lock` exists and resolves only the new project; no existing lockfile changes.

- [ ] **Step 5: Run the boundary tests under the new frozen runtime**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_runtime_boundary.py -v`

Expected: all Task 1 tests pass.

- [ ] **Step 6: Check the preservation boundary**

Run: `git status --short` and `git diff --name-only`

Expected: no deletion and no modified path under any existing `v*/`, existing `go*.sh`, database/raw-data path or `docs/*-runtime.json`; only Task 1 paths plus the approved design/plan are new.

- [ ] **Step 7: Commit Task 1**

```bash
git add go_find_planet_controlled_v1.sh find_planet_v1/pyproject.toml \
  find_planet_v1/uv.lock find_planet_v1/find_planet/__init__.py \
  find_planet_v1/find_planet/provenance.py \
  find_planet_v1/tests/test_runtime_boundary.py
git commit -m "feat: start independent find-planet v1 runtime"
```

### Task 2: Pinned answer-key extraction and anonymous observation audit

**Files:**
- Create: `find_planet_v1/find_planet/types.py`
- Create: `find_planet_v1/find_planet/extract_controlled.py`
- Create: `find_planet_v1/tests/test_extract_controlled.py`
- Create: `find_planet_v1/tests/fixtures/controlled_audit.csv`
- Create: `find_planet_v1/tests/fixtures/runs.sql`

**Interfaces:**
- Consumes: `sha256_file`, `open_sqlite_read_only` from Task 1.
- Produces: `CameraReceipt`; `SelectedCentroid`; `select_answer_key_rows(audit_path: Path, expected_sha256: str, object_name: str = "Mars") -> tuple[list[SelectedCentroid], list[dict[str, str]]]`; `load_exact_receipts(database: Path, rows: Sequence[SelectedCentroid]) -> dict[str, CameraReceipt]`; `write_answer_key_audit(path: Path, audit_rows: Sequence[Mapping[str, str]]) -> None`.

- [ ] **Step 1: Write failing extraction tests**

Test exact audit-hash enforcement, Mars-only selection, one B-channel row per source SHA, stable chronological ordering, preservation of rejected rows/reasons, exact `run_id` lookup, source-SHA equality and rejection of missing/failed/duplicate receipts.  Assert no produced `SelectedCentroid` field contains the strings `planet`, `predicted`, `distance`, `Mars` or `Horizons`.

- [ ] **Step 2: Run extraction tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_extract_controlled.py -v`

Expected: import failure for `extract_controlled`.

- [ ] **Step 3: Implement immutable types and answer-key extraction**

Use frozen dataclasses.  Read CSV by header name, require all fields used by the reference schema, and return a complete audit row for every input row.  Open SQLite with URI `mode=ro`; query only `runs` by the exact row `run_id`; require `exit_code=0`, matching `source_sha256`, and a parseable saved `camera` object in `result_json`.

- [ ] **Step 4: Run extraction tests**

Run: same as Step 2.

Expected: all Task 2 tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add find_planet_v1/find_planet/types.py \
  find_planet_v1/find_planet/extract_controlled.py \
  find_planet_v1/tests/test_extract_controlled.py \
  find_planet_v1/tests/fixtures
git commit -m "feat: extract sealed anonymous MMTO centroids"
```

### Task 3: Barghini centroid inversion without answer-key coordinates

**Files:**
- Create: `find_planet_v1/find_planet/barghini.py`
- Create: `find_planet_v1/tests/test_barghini.py`

**Interfaces:**
- Consumes: `CameraReceipt`, `SelectedCentroid` from Task 2.
- Produces: `camera_to_icrs_unit(camera: CameraReceipt, x_px: float, y_px: float) -> np.ndarray`; `icrs_unit_to_camera(camera: CameraReceipt, unit: np.ndarray) -> np.ndarray`; `anonymous_direction_rows(centroids, receipts) -> list[AnonymousDirection]`.

- [ ] **Step 1: Write failing camera tests**

Add round-trip tests at the centre, four cardinal radii and four near-edge positions using saved-style Barghini parameters.  Assert pixel round-trip error below `1e-6 px`, output vectors have unit norm within `1e-12`, mirrored parity is honoured, invalid/non-monotonic cameras fail, and changing any fixture `predicted_x_px/predicted_y_px` value cannot change the measured direction.

- [ ] **Step 2: Run camera tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_barghini.py -v`

Expected: import failure for `barghini`.

- [ ] **Step 3: Implement the saved Barghini forward/inverse equations locally**

Document the equation/parameter mapping and detector parity.  Use only saved camera parameters, rotation, shape and measured centroid.  Preserve integrated-refraction metadata in the audit but do not perform a second refraction correction.

- [ ] **Step 4: Run camera tests**

Run: same as Step 2.

Expected: all Task 3 tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add find_planet_v1/find_planet/barghini.py \
  find_planet_v1/tests/test_barghini.py
git commit -m "feat: recover inertial rays from measured centroids"
```

### Task 4: TDB epochs and Earth-only topocentric observer states

**Files:**
- Create: `find_planet_v1/find_planet/observer.py`
- Create: `find_planet_v1/tests/test_observer.py`

**Interfaces:**
- Consumes: `AnonymousDirection` from Task 3.
- Produces: `utc_midpoint_to_tdb_jd(value: str) -> float`; `earth_heliocentric_state_epv00(jd_tdb: float) -> tuple[np.ndarray, np.ndarray]` in au and au/day; `mmto_heliocentric_state(jd_tdb: float) -> ObserverState`; `build_observations(directions: Sequence[AnonymousDirection]) -> list[Observation]`.

- [ ] **Step 1: Write failing time/observer tests**

Use three epochs across the reference date span.  Assert UTC-to-TDB values against Astropy `Time`, Earth heliocentric states against direct `erfa.epv00` calls to `1e-12 au`, and MMTO geocentric magnitude near one Earth radius.  Patch `astropy.coordinates.get_body`, `solar_system_ephemeris.set` and `astroquery` entry points to raise, then prove all produced interfaces still work.

- [ ] **Step 2: Run observer tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_observer.py -v`

Expected: import failure for `observer`.

- [ ] **Step 3: Implement the Earth-only observer path**

Use fixed MMTO geodetic longitude `-110.8841666667 deg`, latitude `31.6866666667 deg`, elevation `2616 m`; record north/east conventions.  Call ERFA `epv00` directly for Earth and use Astropy only for time/Earth rotation/topocentric transformation.

- [ ] **Step 4: Run observer tests**

Run: same as Step 2.

Expected: all Task 4 tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add find_planet_v1/find_planet/observer.py \
  find_planet_v1/tests/test_observer.py
git commit -m "feat: add Earth-only MMTO observer states"
```

### Task 5: Orbit dynamics, elements, light time and tangent-plane residuals

**Files:**
- Create: `find_planet_v1/find_planet/geometry.py`
- Create: `find_planet_v1/find_planet/dynamics.py`
- Create: `find_planet_v1/tests/test_dynamics.py`
- Create: `find_planet_v1/tests/test_geometry.py`

**Interfaces:**
- Consumes: `Observation`, `ObserverState`, `HeliocentricState` from Tasks 2–4.
- Produces: `propagate_two_body(state: HeliocentricState, target_jd_tdb: np.ndarray) -> np.ndarray`; `state_to_elements(state: HeliocentricState) -> OrbitalElements`; `predict_topocentric_unit(state, observations, light_time=True) -> np.ndarray`; `tangent_residuals_arcmin(measured: np.ndarray, predicted: np.ndarray) -> np.ndarray`.

- [ ] **Step 1: Write failing dynamics and geometry tests**

Test circular and eccentric synthetic states, forward/backward propagation reversibility, conserved energy/angular momentum, element round trips away from singular cases, explicit singular flags for circular/equatorial cases, light-time convergence and tangent residual signs across RA wrap and near the pole.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_dynamics.py find_planet_v1/tests/test_geometry.py -v`

Expected: imports fail for the two new modules.

- [ ] **Step 3: Implement Sun-only universal-variable propagation and geometry**

Use IAU Gaussian gravitational constant/solar `GM` in explicit au/day units.  Iterate emission time until below `1e-10 day` or fail after a declared maximum.  Return flags instead of arbitrary angles for undefined orbital elements.

- [ ] **Step 4: Run dynamics and geometry tests**

Run: same as Step 2.

Expected: all Task 5 tests pass.

- [ ] **Step 5: Commit Task 5**

```bash
git add find_planet_v1/find_planet/geometry.py \
  find_planet_v1/find_planet/dynamics.py \
  find_planet_v1/tests/test_dynamics.py \
  find_planet_v1/tests/test_geometry.py
git commit -m "feat: add topocentric two-body orbit model"
```

### Task 6: Deterministic systematic ranging and robust orbit families

**Files:**
- Create: `find_planet_v1/find_planet/ranging.py`
- Create: `find_planet_v1/find_planet/fitting.py`
- Create: `find_planet_v1/tests/test_orbit_fit.py`

**Interfaces:**
- Consumes: observation/dynamics/geometry interfaces from Tasks 4–5.
- Produces: `systematic_range_seeds(observations: Sequence[Observation], config: RangingConfig) -> list[HeliocentricState]`; `fit_orbit_families(observations: Sequence[Observation], seeds: Sequence[HeliocentricState], config: FitConfig) -> OrbitFitResult`.

- [ ] **Step 1: Write failing synthetic-fit tests**

Generate noiseless and noisy topocentric observations at the real 34-night cadence from two distinct bound synthetic orbits.  Assert deterministic seeds, rejection of unbound/collision states, recovery of noiseless directions, robust improvement with injected outliers, retention of two distinct compatible minima in a deliberately short/degenerate arc, and complete per-observation final weights/reasons.

- [ ] **Step 2: Run orbit-fit tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_orbit_fit.py -v`

Expected: imports fail for `ranging`/`fitting`.

- [ ] **Step 3: Implement systematic ranging**

Use the spec's `0.02–100 au` logarithmic distance grid, discard seeds outside bound `q>=0.05 au`, `Q<=50 au`, and derive range-rate candidates from the admissible bound interval.  Record every tested/rejected seed and reason.

- [ ] **Step 4: Implement robust differential correction and family clustering**

Use SciPy `least_squares(loss="soft_l1")` on scaled tangent residuals.  Cluster converged states by statistically distinguishable state/prediction distance rather than element labels; never rank using a known planet state.

- [ ] **Step 5: Run orbit-fit tests**

Run: same as Step 2.

Expected: all Task 6 tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add find_planet_v1/find_planet/ranging.py \
  find_planet_v1/find_planet/fitting.py \
  find_planet_v1/tests/test_orbit_fit.py
git commit -m "feat: fit anonymous bound orbit families"
```

### Task 7: Whole-night holdout, baselines and honest uncertainty

**Files:**
- Create: `find_planet_v1/find_planet/evaluate.py`
- Create: `find_planet_v1/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `Observation`, `OrbitFitResult` and prediction interfaces.
- Produces: `split_nights(observations, modulus: int = 5) -> NightSplit`; `fit_fixed_direction(train) -> BaselineModel`; `fit_angular_velocity(train) -> BaselineModel`; `score_predictions(model, observations) -> PredictionScore`; `local_covariance(fit) -> CovarianceResult`; `bootstrap_nights(train, fit_config, replicates: int, seed: int) -> BootstrapResult`; `evaluate_controlled(...) -> EvaluationResult`.

- [ ] **Step 1: Write failing evaluation tests**

Assert every fifth chronological night is withheld, no night is split, baselines see training rows only, all models use identical held-out rows/weights, score fields contain median/RMS/p90/chi-square, rank-deficient Jacobians produce unresolved covariance flags, night bootstrap is deterministic, and half/double-sigma sensitivity results cannot replace the primary fit.

- [ ] **Step 2: Run evaluation tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_evaluate.py -v`

Expected: import failure for `evaluate`.

- [ ] **Step 3: Implement split, baselines, scores and uncertainty**

Fit the fixed direction as the weighted mean unit vector and angular velocity as weighted linear tangent coordinates about the median training epoch.  Bootstrap whole nights with a fixed recorded seed.  Mark scientific status predictive only when the orbit improves held-out chi-square over both baselines and the uncertainty calculation is supported.

- [ ] **Step 4: Run evaluation tests**

Run: same as Step 2.

Expected: all Task 7 tests pass.

- [ ] **Step 5: Commit Task 7**

```bash
git add find_planet_v1/find_planet/evaluate.py \
  find_planet_v1/tests/test_evaluate.py
git commit -m "feat: evaluate held-out orbit predictions"
```

### Task 8: Products, figures, immutable seal and controlled CLI

**Files:**
- Create: `find_planet_v1/find_planet/report.py`
- Create: `find_planet_v1/find_planet/seal.py`
- Create: `find_planet_v1/find_planet/controlled_cli.py`
- Create: `find_planet_v1/tests/test_report_and_seal.py`
- Create: `find_planet_v1/tests/test_controlled_cli.py`

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: `write_controlled_report(output: Path, extraction, fit, evaluation) -> list[Path]`; `seal_output(output: Path, product_paths: Sequence[Path], inputs: Mapping[str, str]) -> Path`; `verify_seal(path: Path) -> SealVerification`; `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing reporting/seal tests**

Assert all required CSV/JSON products and three figures are written; plot data equal exported numerical rows; measured coordinates are unchanged; axes include frame/epoch/units; residual magnification is absent or explicitly labelled; an unresolved fit remains visibly unresolved; sealing hashes every product; post-seal mutation fails verification; an interrupted report has no seal; an existing output path is refused.

- [ ] **Step 2: Write failing CLI tests**

Use fixtures and a reduced deterministic grid.  Assert `--help`, required input validation, fresh output creation, separate `answer_key_selection.csv` and anonymous `observations.csv`, status JSON on scientific non-identifiability, nonzero exit on operational errors, and no planet/prediction fields in the fit-input manifest.

- [ ] **Step 3: Run reporting/CLI tests and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_report_and_seal.py find_planet_v1/tests/test_controlled_cli.py -v`

Expected: imports fail for report/seal/CLI modules.

- [ ] **Step 4: Implement machine-readable products and figures**

Write the spec's `orbit_sky_track.png`, `orbit_residuals.png`, `heliocentric_orbit.png`, observation/audit/candidate/element/covariance/bootstrap CSVs and `fit_summary.json`.  Use atomic temporary-file replacement inside the new run directory only; do not modify inputs.

- [ ] **Step 5: Implement seal and CLI orchestration**

Seal only after all products are closed and verified.  Include input hashes, exact run IDs, package/source manifest, command arguments, dependency lock hash, coordinate/time conventions and status.  Scientific unresolved status exits zero with an explicit status; corrupt input or incomplete output exits nonzero without a seal.

- [ ] **Step 6: Run reporting/CLI tests**

Run: same as Step 3.

Expected: all Task 8 tests pass.

- [ ] **Step 7: Commit Task 8**

```bash
git add find_planet_v1/find_planet/report.py \
  find_planet_v1/find_planet/seal.py \
  find_planet_v1/find_planet/controlled_cli.py \
  find_planet_v1/tests/test_report_and_seal.py \
  find_planet_v1/tests/test_controlled_cli.py
git commit -m "feat: report and seal controlled orbit fits"
```

### Task 9: Source manifest, real controlled run, documentation and repository regression

**Files:**
- Create: `find_planet_v1/source-manifest.json`
- Create: `find_planet_v1/README.md`
- Create: `find_planet_v1/tests/test_source_manifest.py`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `README.md`
- Generate new: `results/find-planet-v1/<UTC-run-id>/...` (ignored scientific output; never replace an existing directory)

**Interfaces:**
- Consumes: completed controlled CLI and all source files.
- Produces: verified manifest and first real controlled `Object A` evidence package.

- [ ] **Step 1: Write failing manifest test**

Assert every runtime `.py`, launcher, lockfile and declared local data file is present exactly once with SHA-256 and role; reject missing, extra or changed runtime files.  Explicitly exclude generated results and frozen solver files from the new manifest.

- [ ] **Step 2: Run manifest test and verify failure**

Run: `uv run --project find_planet_v1 --frozen python -m unittest find_planet_v1/tests/test_source_manifest.py -v`

Expected: failure because the manifest is absent.

- [ ] **Step 3: Create the manifest and user documentation**

Document the controlled/non-blind selection, command, scientific statuses, output interpretation, Earth-only/Sun-only assumptions, held-out baselines, uncertainty limitations and the promise that existing solver families remain untouched.  Update root status/docs without changing claims about frozen versions.

- [ ] **Step 4: Run all new-family tests**

Run: `uv run --project find_planet_v1 --frozen python -m unittest discover -s find_planet_v1/tests -v`

Expected: all new-family tests pass.

- [ ] **Step 5: Capture preservation hashes before the real run**

Run read-only hashes for every `docs/*-runtime.json`, existing root `go*.sh`, `results/stars.sqlite`, `raw_allsky_samples/manifest.sqlite` and the pinned audit into a temporary comparison file outside the repository output tree.

Expected: a complete pre-run preservation inventory; do not hash all raw images or generated results.

- [ ] **Step 6: Run the controlled experiment into a fresh directory**

Run:

```bash
./go_find_planet_controlled_v1.sh \
  --audit results/photometry-runs/v23-20261027T050447Z/planet-empirical-extinction/B/planet_only_airmass_correction_audit.csv \
  --database results/stars.sqlite
```

Expected: terminal prints the new concrete run directory, scientific status and seal verification; it does not claim Mars before a future comparison stage.

- [ ] **Step 7: Inspect every controlled figure and validate tables**

Open all three PNGs.  Confirm measured points match exported observations, fit/withheld nights are visually distinct, uncertainty is visible, residuals are not cosmetically shifted, and the orbit family/degeneracy agrees with `candidate_orbits.csv` and `fit_summary.json`.

- [ ] **Step 8: Verify preservation hashes after the real run**

Repeat Step 5 and compare inventories.

Expected: every protected hash is identical; only a new `results/find-planet-v1/<UTC-run-id>/` tree was generated.

- [ ] **Step 9: Run required repository regressions**

Run:

```bash
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Expected: both commands pass without relaxed thresholds.

- [ ] **Step 10: Inspect final working-tree scope**

Run: `git status --short --branch`, `git diff --stat`, `git diff --name-status` and compare all modified paths with this plan's allowlist.

Expected: no deletion, no database/raw-image change, no frozen runtime/launcher/manifest change, and no unrelated user change overwritten.

- [ ] **Step 11: Commit Task 9**

```bash
git add find_planet_v1/source-manifest.json find_planet_v1/README.md \
  find_planet_v1/tests/test_source_manifest.py README.md docs/FEATURE_STATUS.md \
  docs/superpowers/specs/2026-10-29-find-planet-v1-design.md \
  docs/superpowers/plans/2026-10-29-find-planet-controlled-v1.md
git commit -m "docs: record controlled planet-finding experiment"
```

The generated scientific run remains an inspectable result and is not used to
rewrite historical reference products.  Planning for
`go_find_planet_blind_v1.sh` begins only after this controlled implementation
and its preservation audit are complete.
