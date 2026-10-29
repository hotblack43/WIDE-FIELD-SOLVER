# Find Planet OpenOrb v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `go_find_planet_openorb_v1.sh`, which exports the pinned controlled MMTO moving-object measurements as anonymous astrometry and uses pinned native OpenOrb 1.3.0 for statistical ranging, differential correction, covariance, and held-out ephemerides.

**Architecture:** A new `find_planet_openorb_v1/` runtime owns controlled extraction, saved-camera inversion, `.mpc3` export, OpenOrb subprocess orchestration, output parsing, evaluation, reports, and seals.  OpenOrb is built from its pinned official release into a repository-local ignored vendor directory; the wrapper uses its native executable exclusively and runs identity-neutral two-body target dynamics with deterministic random sampling.

**Tech Stack:** Python 3.12, Astropy 7.2, NumPy 2.4, Matplotlib 3.11, SQLite, Bash, GNU Make/GCC/GFortran, OpenOrb 1.3.0 native CLI, DE441, `unittest`, uv.

**Spec:** `docs/superpowers/specs/2026-10-29-find-planet-openorb-v1-design.md`

## Global Constraints

- Start from intact `main` in a new worktree.  Do not merge or cherry-pick the stopped generic fitter, its reports, or its incomplete runtime; cherry-pick only this design and plan documentation.
- Preserve every existing launcher, `v4/` through `v23/`, historical reference, database, raw image, runtime manifest, stopped branch, and stopped run directory.
- Create only the new `go_find_planet_openorb_*_v1.sh` launchers, `find_planet_openorb_v1/` runtime, approved root/status documentation, and fresh ignored output directories.
- Pin OpenOrb tag `v1.3.0`, commit `945178476f016dae8f3981b54a937f61de81360f`; never search `$PATH` for another OpenOrb executable.
- Keep OpenOrb GPL source/binaries in a repository-local ignored vendor directory with a build/license receipt; do not copy them into preserved solver packages.
- Pin and checksum `OBSCODE.dat`, `TAI-UTC.dat`, `ET-UT.dat`, and the locally built DE441 OpenOrb ephemeris.  Normal scientific runs are offline.
- The answer-key selector is controlled and explicit.  After selection, the fitter receives no object identity, known position, known distance, known element, Horizons quantity, or identity-derived setting.
- Use OpenOrb `.mpc3` with individual isotropic uncertainties `max(60 arcsec, saved stellar-only RMS)` and observatory code `696` only after the site-position/parallax guard passes.
- Withhold every fifth chronological usable observing night before writing the fit input.  Withheld rows never enter ranging or LSL.
- OpenOrb is the sole orbit engine.  No SciPy/custom orbit fit or fallback may be reachable from the launcher.
- Every OpenOrb invocation uses `--fixran`, an explicit config, an explicit local data directory, an explicit native executable, and a controlled working directory.
- Anonymous target dynamics are OpenOrb `2-body` for every unknown track.  All planetary perturbers are uniformly disabled; DE441 is used only for Sun/Earth observer geometry and time transformations.
- Primary ranging requests 5,000 accepted samples with 5,000,000 trials, three automatic-ranging iterations, and a 60-minute limit.  Each uncertainty sensitivity requests 2,000 samples, 2,000,000 trials, three iterations, and a 30-minute limit.
- A run interrupted or capped before its requested accepted sample count is `search_incomplete` and never receives a success seal.
- Before every commit, run the task-specific new-runtime tests plus the repository-required `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-unique-name`; satisfy clean-worktree ignored runtime evidence without modifying its hashes.

## Review Focus

- OpenOrb may exist on `$PATH`, but the launcher must still use only the receipt-hashed local executable; Task 1 tests a malicious PATH executable.
- `.mpc3` is fixed-width and easy to shift silently; Task 3 tests every important column and validates generated observations through the native OpenOrb parser.
- A withheld night could leak through a combined input or retry path; Tasks 3 and 7 test exact run-ID disjointness across every OpenOrb command transcript.
- DE441 contains known planets even when target dynamics are two-body; Task 4 tests the exact config and upstream call path and rejects every enabled perturber.
- OpenOrb can exit zero without reaching the requested sample count; Tasks 4 and 7 parse completion evidence and label such runs `search_incomplete` without a success seal.

---

## File structure

- `go_find_planet_openorb_setup_v1.sh`: pinned native build/data setup.
- `go_find_planet_openorb_v1.sh`: stable controlled scientific launcher.
- `find_planet_openorb_v1/pyproject.toml`, `uv.lock`: independent wrapper runtime.
- `find_planet_openorb_v1/openorb-sources.json`: upstream URLs, release/commit, archive/data hashes, license metadata.
- `find_planet_openorb_v1/config/*.conf`: immutable primary and sensitivity templates.
- `find_planet_openorb_v1/find_planet_openorb/provenance.py`: hashing, read-only inputs, fresh output, receipts.
- `.../extract_controlled.py`, `barghini.py`, `types.py`: exact controlled measurement boundary.
- `.../observations.py`, `mpc3.py`: split, anonymous coordinate export, and fixed-width validation.
- `.../openorb_runtime.py`: local executable/data verification and subprocess lifecycle.
- `.../openorb_parse.py`: ranging, LSL, covariance, residual, and ephemeris parsers.
- `.../evaluate.py`: baselines, held-out scores, covariance/family gates, status.
- `.../preregister.py`: synthetic-injection gates created before real inputs are accessible.
- `.../report.py`, `seal.py`, `controlled_cli.py`: products, figures, immutable seal, orchestration.
- `find_planet_openorb_v1/tests/`: unit, integration, leakage, preservation, and synthetic tests.

### Task 1: Independent runtime, pinned native setup, and preservation boundary

**Files:**
- Create: `go_find_planet_openorb_setup_v1.sh`
- Create: `go_find_planet_openorb_v1.sh`
- Create: `find_planet_openorb_v1/pyproject.toml`
- Create: `find_planet_openorb_v1/uv.lock`
- Create: `find_planet_openorb_v1/openorb-sources.json`
- Create: `find_planet_openorb_v1/find_planet_openorb/__init__.py`
- Create: `find_planet_openorb_v1/find_planet_openorb/provenance.py`
- Create: `find_planet_openorb_v1/tests/test_runtime_boundary.py`

**Interfaces:**
- Produces: `find_planet_openorb.__version__ == "1.0.0"`; `sha256_file(path: Path) -> str`; `open_sqlite_read_only(path: Path) -> sqlite3.Connection`; `new_output_directory(root: Path, run_id: str) -> Path`; `OpenOrbInstallation`; `verify_installation(vendor_root: Path, sources_manifest: Path) -> OpenOrbInstallation`.

- [ ] **Step 1: Write failing runtime/setup boundary tests**

Add tests named `test_existing_output_is_refused`, `test_database_is_read_only`, `test_setup_pins_release_commit_and_license`, `test_scientific_launcher_uses_only_receipt_hashed_local_binary`, `test_path_oorb_is_never_executed`, and `test_frozen_or_stopped_launchers_are_not_targets`.  Execute launchers with fake `git`, `make`, and `oorb` programs to assert exact routing rather than grepping shell source.

- [ ] **Step 2: Run Task 1 tests and verify RED**

Run: `uv run --project v23 --frozen python -m unittest discover -s find_planet_openorb_v1/tests -p 'test_runtime_boundary.py' -v`

Expected: import/file failures because the new runtime and launchers do not exist.

- [ ] **Step 3: Implement the independent wrapper runtime and guards**

Pin Python `>=3.12,<3.13`, Astropy `7.2.0`, NumPy `2.4.4`, and Matplotlib `3.11.1`.  `verify_installation` must verify executable, config/data, build receipt, exact OpenOrb commit, and every recorded SHA before returning paths; it must not consult `$PATH`.

- [ ] **Step 4: Implement pinned setup and stable launcher**

The setup script downloads only manifest-declared official artifacts, verifies hashes before extraction, builds OpenOrb with GNU Fortran into `find_planet_openorb_v1/.vendor/openorb-1.3.0`, runs upstream tests, builds/tests DE441, and atomically writes build/data receipts.  The scientific launcher unsets `VIRTUAL_ENV`, uses `uv --frozen`, and defaults only its results root.

- [ ] **Step 5: Freeze dependencies and run Task 1 tests**

Run `uv lock --project find_planet_openorb_v1`, then the Task 1 command under the new project.

Expected: all Task 1 tests pass; no existing lockfile changes.

- [ ] **Step 6: Run required repository regressions and commit**

Commit: `feat: start pinned OpenOrb planet-finding runtime`

### Task 2: Exact controlled extraction and saved-camera inversion

**Files:**
- Create: `find_planet_openorb_v1/find_planet_openorb/types.py`
- Create: `find_planet_openorb_v1/find_planet_openorb/extract_controlled.py`
- Create: `find_planet_openorb_v1/find_planet_openorb/barghini.py`
- Create: `find_planet_openorb_v1/tests/test_extract_and_camera.py`
- Create: `find_planet_openorb_v1/tests/fixtures/controlled_audit.csv`
- Create: `find_planet_openorb_v1/tests/fixtures/runs.sql`

**Interfaces:**
- Consumes: Task 1 read-only/hash utilities.
- Produces: `SelectedCentroid`; `CameraReceipt`; `AnonymousDirection`; `select_answer_key_rows(...)`; `load_exact_receipts(...)`; `camera_to_icrs_unit(...)`; `anonymous_direction_rows(...)`; `write_answer_key_audit(...)`.

- [ ] **Step 1: Write failing extraction/camera tests**

Test exact audit hash, Mars-only controlled selection, complete rejected-row audit, both `saturated` and pinned `saturation_known/channel_saturated` schemas, exact run-ID receipt with matching source SHA, missing/failed/duplicate/malformed rejection, identity-free output fields, detector parity, integrated derefraction exactly once, unused corners beyond radial angle pi, and the two real receipt edge cases found during prototype preflight.

- [ ] **Step 2: Run Task 2 tests and verify RED**

Expected: imports fail for the new modules.

- [ ] **Step 3: Reimplement the audited extraction and saved Barghini equations locally**

Use frozen dataclasses.  Do not import the stopped prototype or any `v*/` runtime.  Atomic answer-key output remains separate from anonymous rows.

- [ ] **Step 4: Run Task 2 tests, repository regressions, and commit**

Commit: `feat: export exact anonymous MMTO directions`

### Task 3: Whole-night split and OpenOrb `.mpc3` observations

**Files:**
- Create: `find_planet_openorb_v1/find_planet_openorb/observations.py`
- Create: `find_planet_openorb_v1/find_planet_openorb/mpc3.py`
- Create: `find_planet_openorb_v1/tests/test_mpc3.py`

**Interfaces:**
- Consumes: `AnonymousDirection`.
- Produces: `AnonymousObservation`; `NightSplit`; `directions_to_observations(directions) -> tuple[AnonymousObservation, ...]`; `split_nights(observations, modulus=5) -> NightSplit`; `write_mpc3(path, observations, designation, obscode="696") -> None`; `parse_mpc3_records(path) -> tuple[Mpc3Record, ...]`; `validate_mpc3_with_openorb(installation, path) -> Mpc3Validation`.

- [ ] **Step 1: Write failing split/format tests**

Assert UTC midpoint preservation, ICRS RA/Dec conversion across wrap/poles, sigma floor `60 arcsec`, exact 132-column two-record observation layout, neutral designation, code 696, individual RA/Dec uncertainty fields, every fifth night wholly withheld, fit/withheld run-ID disjointness, and no identity/prediction terms in anonymous CSV or `.mpc3`.

- [ ] **Step 2: Run Task 3 tests and verify RED**

Expected: imports fail for `observations`/`mpc3`.

- [ ] **Step 3: Implement anonymous observations, split, writer, and local parser**

Match the pinned OpenOrb `Observations_class.f90` column contract; use UTC calendar fields and enough angular precision to stay below 0.01 arcsec export error.

- [ ] **Step 4: Add native parser round-trip integration test**

Use the receipt-hashed native executable to convert/parse a generated fixture and assert epoch, direction, code, designation, and both uncertainties.  Mark absence of a verified vendor installation as a clear integration prerequisite, never a silent pass in production verification.

- [ ] **Step 5: Run Task 3 tests, repository regressions, and commit**

Commit: `feat: write anonymous OpenOrb astrometry`

### Task 4: Identity-neutral OpenOrb execution and completion audit

**Files:**
- Create: `find_planet_openorb_v1/config/primary.conf`
- Create: `find_planet_openorb_v1/config/half_sigma.conf`
- Create: `find_planet_openorb_v1/config/double_sigma.conf`
- Create: `find_planet_openorb_v1/find_planet_openorb/openorb_runtime.py`
- Create: `find_planet_openorb_v1/tests/test_openorb_runtime.py`

**Interfaces:**
- Consumes: `OpenOrbInstallation`, fit `.mpc3`.
- Produces: `OpenOrbRunSpec`; `OpenOrbRunReceipt`; `audit_config(path, expected_budget) -> ConfigAudit`; `run_openorb(spec, installation, output) -> OpenOrbRunReceipt`; `run_ranging(...)`; `run_lsl(...)`; `run_ephemeris(...)`.

- [ ] **Step 1: Write failing config/subprocess tests**

Assert exact primary/sensitivity budgets, `dynamical_model: 2-body`, every perturber false, deterministic `--fixran`, explicit executable/config/input/output paths, controlled `OORB_DATA`, offline environment, timeout/SIGINT receipt, stdout/stderr capture, nonzero-exit failure, accepted-sample count audit, and zero-exit incomplete ranging classified `search_incomplete`.

- [ ] **Step 2: Write leakage-path test against pinned upstream source**

Pin the audited OpenOrb source files/hash that implement the two-body propagation branch.  Assert the selected config cannot enter n-body perturber calls; reject a changed upstream source hash until reviewed.  This proves identity-neutral configuration/code routing without patching OpenOrb.

- [ ] **Step 3: Run Task 4 tests and verify RED**

Expected: missing configs/runtime module.

- [ ] **Step 4: Implement config audit and shell-free process lifecycle**

Use `subprocess.Popen` with an argument vector, process group, monotonic timeout, SIGTERM grace then SIGKILL, atomic receipt, and no `shell=True`.  Preserve every raw file even for non-convergence/interruption; write no success marker here.

- [ ] **Step 5: Run Task 4 tests, repository regressions, and commit**

Commit: `feat: run deterministic identity-neutral OpenOrb jobs`

### Task 5: Parse authoritative OpenOrb orbit products

**Files:**
- Create: `find_planet_openorb_v1/find_planet_openorb/openorb_parse.py`
- Create: `find_planet_openorb_v1/tests/test_openorb_parse.py`
- Create: `find_planet_openorb_v1/tests/fixtures/openorb/`

**Interfaces:**
- Consumes: raw OpenOrb ranging/LSL/residual/ephemeris products.
- Produces: `RangingSample`; `NominalOrbit`; `CovarianceResult`; `ResidualRow`; `EphemerisRow`; `parse_ranging(path)`; `parse_lsl(path)`; `parse_residuals(path)`; `parse_ephemeris(path)`; `covariance_support(covariance, max_condition=1e12)`.

- [ ] **Step 1: Capture official sample outputs as attributed fixtures**

Generate fixtures only with the pinned executable and upstream sample input; record command, upstream file hash, executable hash, and license/source attribution beside them.

- [ ] **Step 2: Write failing parser tests**

Test Cartesian/Keplerian units and epochs, sample weights, full six-by-six covariance, positive eigenvalue/condition gate, singular/missing covariance rejection, residual signs, RA wrap, ephemeris time/code, truncated rows, nonfinite values, and format-version mismatch.

- [ ] **Step 3: Implement strict versioned parsers**

Reject rather than guess when required headers/columns differ.  Parsed tables retain raw line numbers and source hashes.

- [ ] **Step 4: Run Task 5 tests, repository regressions, and commit**

Commit: `feat: parse OpenOrb orbit evidence`

### Task 6: Synthetic preregistration and family diagnostics

**Files:**
- Create: `find_planet_openorb_v1/find_planet_openorb/preregister.py`
- Create: `find_planet_openorb_v1/tests/test_synthetic_openorb.py`

**Interfaces:**
- Consumes: Tasks 3–5 interfaces.
- Produces: `SyntheticCase`; `PreregisteredGates`; `run_synthetic_suite(installation, output, seed) -> PreregisteredGates`; `verify_preregistered_gates(path, source_hashes) -> PreregisteredGates`.

- [ ] **Step 1: Write failing synthetic/preregistration tests**

Generate identity-free topocentric arcs at the real night cadence for at least inner, main-belt, and outer bound orbits plus noise/outlier cases.  Assert OpenOrb recovers held-out directions within declared coverage, identical fixed-random runs reproduce parsed samples, gates contain no real-audit/database hash, and gates cannot be regenerated after real inputs are opened.

- [ ] **Step 2: Implement synthetic generation and preregistration lifecycle**

The suite derives only the 95th-percentile held-out median recovery limit.  Fixed gates remain: covariance condition `1e12`, family weight `5%`, family held-out delta chi-square `25`, and predictive improvement `25` against each baseline.

- [ ] **Step 3: Run native synthetic suite twice**

Expected: both runs produce identical scientific hashes and a sealed `preregistered_gates.json`; all recovery/coverage assertions pass before any real controlled input is supplied.

- [ ] **Step 4: Run Task 6 tests, repository regressions, and commit**

Commit: `test: preregister OpenOrb recovery gates`

### Task 7: Held-out evaluation, baselines, and scientific status

**Files:**
- Create: `find_planet_openorb_v1/find_planet_openorb/evaluate.py`
- Create: `find_planet_openorb_v1/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `NightSplit`, parsed OpenOrb products, preregistered gates.
- Produces: `BaselineModel`; `PredictionScore`; `OrbitFamily`; `EvaluationResult`; `fit_fixed_direction(train)`; `fit_angular_velocity(train)`; `score_predictions(...)`; `cluster_families(...)`; `evaluate_openorb(...)`.

- [ ] **Step 1: Write failing evaluation tests**

Assert baselines see training rows only; orbit/baselines score identical withheld run IDs and sigmas; scores contain median/RMS/p90/weighted chi-square; predictive requires delta chi-square at least 25 against both and the synthetic median gate; covariance failures yield unresolved; a qualifying secondary family yields multimodal; primary sensitivity cannot be replaced by half/double sigma; incomplete sample budget dominates all scientific statuses.

- [ ] **Step 2: Run Task 7 tests and verify RED**

Expected: import failure for `evaluate`.

- [ ] **Step 3: Implement evaluation without orbit fitting**

This module may fit only the two simple sky baselines.  It consumes OpenOrb orbits/ephemerides and must contain no custom propagation, ranging, or orbital optimizer.

- [ ] **Step 4: Run Task 7 tests, repository regressions, and commit**

Commit: `feat: evaluate held-out OpenOrb predictions`

### Task 8: Atomic products, figures, seal, and controlled CLI

**Files:**
- Create: `find_planet_openorb_v1/find_planet_openorb/report.py`
- Create: `find_planet_openorb_v1/find_planet_openorb/seal.py`
- Create: `find_planet_openorb_v1/find_planet_openorb/controlled_cli.py`
- Create: `find_planet_openorb_v1/tests/test_report_seal_cli.py`

**Interfaces:**
- Consumes: all prior interfaces.
- Produces: `write_report(...) -> tuple[Path, ...]`; `seal_output(...) -> Path`; `verify_seal(...) -> SealVerification`; `main(argv=None) -> int`.

- [ ] **Step 1: Write failing report/seal/CLI tests**

Assert fresh-output refusal; missing/unverified installation failure; separate answer-key and anonymous inputs; exact commands/configs/raw products retained; required CSV/JSON and three figures; plot backing data equal exported measurements/residuals; unresolved/multimodal/incomplete visible; residual scale ×1; every product hashed; mutation fails verification; SIGINT leaves an interruption receipt and no seal; scientific non-success exits zero only after a complete evidence package.

- [ ] **Step 2: Run Task 8 tests and verify RED**

Expected: missing report/seal/CLI modules.

- [ ] **Step 3: Implement atomic reports and immutable seal**

Write temporary files only inside the fresh run directory, fsync and replace, close all plots before sealing, and verify the new seal before returning success.

- [ ] **Step 4: Implement CLI orchestration**

Order: verify installation/data/gates and real inputs; create fresh output; controlled selection; anonymous split/export/native validation; primary ranging/LSL/ephemeris; sensitivities; evaluation; report; seal.  Print stage progress and accepted-sample counts so a long native run is observable.

- [ ] **Step 5: Run Task 8 tests, repository regressions, and commit**

Commit: `feat: report and seal professional OpenOrb fits`

### Task 9: Native setup, real controlled run, preservation audit, and documentation

**Files:**
- Create: `find_planet_openorb_v1/source-manifest.json`
- Create: `find_planet_openorb_v1/README.md`
- Create: `find_planet_openorb_v1/tests/test_source_manifest.py`
- Modify: `README.md`
- Modify: `docs/FEATURE_STATUS.md`
- Generate ignored: `find_planet_openorb_v1/.vendor/openorb-1.3.0/`
- Generate ignored: `results/find-planet-openorb-v1/<UTC-run-id>/`

**Interfaces:**
- Consumes: completed runtime and pinned official sources.
- Produces: verified local OpenOrb installation, source manifest, first sealed real `Object A` evidence package.

- [ ] **Step 1: Write failing exact source-manifest test**

Require every project-authored runtime `.py`, launcher, lockfile, config, source manifest, and declared local data descriptor exactly once with role/hash; exclude `.vendor`, generated results, stopped prototype, and frozen solvers.

- [ ] **Step 2: Run setup with approved network access**

Run `./go_find_planet_openorb_setup_v1.sh`; verify official archive/data hashes, GNU Fortran build, upstream tests, DE441 test, build/data receipts, and exact local executable path.  Never use or install a system-wide binary.

- [ ] **Step 3: Run all new-runtime and native integration tests**

Run: `uv run --project find_planet_openorb_v1 --frozen python -m unittest discover -s find_planet_openorb_v1/tests -v`

Expected: all unit, leakage, parser, synthetic, determinism, seal, and native integration tests pass.

- [ ] **Step 4: Capture protected pre-run hashes from intact main**

Hash every `docs/*-runtime.json`, existing root `go*.sh`, `results/stars.sqlite`, `raw_allsky_samples/manifest.sqlite`, and the pinned audit into a temporary file outside the repository.

- [ ] **Step 5: Run the real controlled OpenOrb experiment**

Run `./go_find_planet_openorb_v1.sh --audit <pinned-audit> --database results/stars.sqlite`.  Do not supply or reveal an object identity to OpenOrb.  Require declared sample budgets, progress output, held-out scoring, and verified seal.

- [ ] **Step 6: Inspect all figures and tables**

Open all three PNGs.  Verify measured data against backing CSVs, whole-night partition display, unshifted ×1 residuals, orbit-family/covariance consistency, raw OpenOrb evidence, and honest status.  Do not compare with Mars in this task.

- [ ] **Step 7: Repeat and compare protected hashes**

Expected: exact equality; only new OpenOrb vendor cache and fresh result directory were generated.

- [ ] **Step 8: Document scope, commands, OpenOrb citation/license, interpretation, and limitations**

State controlled/non-blind selection, anonymous engine boundary, OpenOrb 1.3.0, identity-neutral two-body dynamics, held-out gates, statuses, raw evidence, and future OrbFit validator.  Preserve all claims about frozen solver versions.

- [ ] **Step 9: Run final required regressions and scope audit**

Run both repository commands, full new-runtime suite, `git diff --check`, `git status --short --branch`, `git diff --name-status`, deletion scan, and protected hash comparison.

- [ ] **Step 10: Commit**

Commit: `docs: record controlled OpenOrb planet experiment`

The scientific result remains ignored but inspectable.  No known-object
comparison begins until this anonymous OpenOrb evidence package is sealed.
