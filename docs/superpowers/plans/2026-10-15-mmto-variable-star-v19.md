# MMTO Variable-Star V19 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent v0.19.0 MMTO runtime that preserves every v16 pipeline product and adds chronological nightly flux-averaged, extinction-corrected instrumental-magnitude time series for confirmed VSX variables with `5 < period < 30` days and catalogue magnitude `< 5.0` by default.

**Approved refinement (15 October 2026):** The implemented product averages
corrected relative flux by VSX object, MMTO observing night, and native channel,
then converts that mean flux back to one magnitude at the median contributing
UTC. It also has configurable exclusive lower/upper period limits (defaults 5
and 30 days) and an exclusive catalogue-magnitude limit (default 5.0). These
requirements supersede the initial per-exposure and `0 < period < 50` wording
retained in the original task sequence below as planning history.

**Approved sine-fit refinement (15 October 2026):** Each channel's nightly
points are fitted independently in magnitude space with the VSX period held
fixed. The fit solves mean, semi-amplitude, and brightest-light phase relative
to the star's earliest plotted UTC; curves and phase labels are added to the
PDF and exact parameters/statuses are exported as CSV.

**Architecture:** Clone the frozen v16 solver into v19 and change only its version identity. Keep the VSX association frozen and local inside v19, consume the existing nightly-extinction CSV rather than recomputing photometry, and insert one new plotting stage between the unchanged v16 nightly-extinction and planet stages.

**Tech Stack:** Python 3.12, `unittest`, CSV/JSON, Astropy coordinates/time, Astroquery CDS XMatch for the one-time catalogue build, Matplotlib multipage PDF, Bash launchers, `uv` lockfiles.

**Spec:** `docs/superpowers/specs/2026-10-15-mmto-variable-star-v19-design.md`

## Global Constraints

- Do not create a branch or worktree.
- Do not edit v16, v17, v18, their launchers, or existing result directories.
- V19 is based directly on frozen v16; it does not inherit the v18 acquisition/backlog subsystem.
- The added ordinate is exactly `m_corrected = m_machine - k_night,channel X`; never apply a distance correction, catalogue offset, phase fold, or cosmetic shift.
- Default selection is strictly `0 < period < 50.0` days and `observed_utc >= 2026-06-30T00:00:00Z`.
- All ordinary v16 pipeline plots, arguments, and behavior remain present and unchanged in v19.
- Runtime catalogue use is offline; network access is confined to the deliberate catalogue-build command.

## Review Focus

- NaN, infinite, zero, negative, and exactly-50-day periods must be audited and excluded at the default boundary; Task 2 tests each case.
- Naive or malformed observation times must fail explicitly instead of evading the March cutoff; Task 3 tests both cases.
- One local source matching multiple VSX OIDs must be ambiguous, while Tycho/Gaia IDs sharing one OID must make one panel; Tasks 2 and 3 test these separately.
- Existing nonempty output directories must never be overwritten; Task 3 tests the refusal before any output mutation.
- A catalogue large enough for multiple PDF pages must plot every eligible object exactly once; Task 3 tests page and star counts from a 13-object fixture.

---

### Task 1: Establish the Independent V19 Runtime Boundary

**Files:**
- Create: `v19/` as a clean copy of tracked v16 files, excluding `.venv`, caches, and generated products
- Create: `go19.sh`
- Create: `go_v0.19.0.sh`
- Create: `test_v19_runtime_boundary.py`
- Modify inside v19 only: `pyproject.toml`, `uv.lock`, `run.sh`, `point_star_barghini.py`, version assertions, `AGENTS.md`, `HANDOFF.md`, `README.md`, `docs/FEATURE_STATUS.md`, `scripts/update_v19_manifest.py`, `SOURCE_MANIFEST.json`

**Interfaces:**
- Produces: solver version `0.19.0`; launchers `go19.sh` and `go_v0.19.0.sh`; self-contained project `v19/` runnable through `uv run --project v19 --frozen`.

- [ ] **Step 1: Write the failing runtime-boundary tests**

  Add tests named `test_v19_launchers_report_0190`, `test_v19_manifest_is_complete_and_based_on_v16`, and `test_preserved_v16_v17_v18_bytes_match_preimplementation_snapshot`. Assert the v19 entry points use only `v19/`, the source manifest parent is `../docs/v16-runtime.json`, and no pre-existing preserved-version byte changes.

- [ ] **Step 2: Run the focused test and observe the missing-v19 failure**

  Run: `uv run --frozen python -m unittest -v test_v19_runtime_boundary`

  Expected: FAIL because v19 and its launchers do not exist.

- [ ] **Step 3: Clone and version the runtime**

  Copy the tracked v16 package without virtual environments or caches. Change active runtime identity to `0.19.0`, rename the manifest updater symbols and paths to v19, set `based_on_version` to `0.16.0`, preserve the dependency set, regenerate `v19/uv.lock`, and create both root launchers.

- [ ] **Step 4: Refresh and validate the v19 source manifest**

  Run: `uv run --project v19 --frozen python v19/scripts/update_v19_manifest.py`

  Expected: `v19/SOURCE_MANIFEST.json` includes every v19 source/data file except itself and names the frozen v16 snapshot as its parent.

- [ ] **Step 5: Run the boundary tests**

  Run: `uv run --frozen python -m unittest -v test_v19_runtime_boundary`

  Expected: PASS with unchanged before/after hashes for v16, v17, and v18.

### Task 2: Build and Freeze the Local VSX Cross-Match

**Files:**
- Create: `v19/scripts/build_vsx_crossmatch.py`
- Create: `v19/data/vsx_crossmatch.csv`
- Create: `v19/data/vsx_crossmatch.provenance.json`
- Create: `v19/test_vsx_crossmatch.py`
- Modify: `v19/data/README.md`

**Interfaces:**
- Consumes: `v19/data/stars_tycho2_mag75.csv`, `v19/data/stars_gaia_dr3_g75.csv`.
- Produces: `build_crossmatch(catalogue_paths: Sequence[Path], output_csv: Path, provenance_json: Path, match_radius_arcsec: float = 1.0) -> dict[str, object]` and a frozen CSV keyed by `(catalogue_sha256, star_id)` with VSX OID/name/flag/type/period, propagated J2000 coordinates, separation, candidate multiplicity, and selection status.

- [ ] **Step 1: Write failing catalogue tests**

  Test J2000 proper-motion propagation, exact 1.0-arcsecond acceptance, ambiguity for two distinct VSX OIDs, retention of suspected/constant/missing-period audit rows, and finite strictly positive period eligibility. Include NaN, infinity, zero, negative, and `50.0` fixtures.

- [ ] **Step 2: Run the focused tests and observe the missing-builder failure**

  Run: `uv run --project v19 --frozen python -m unittest -v v19.test_vsx_crossmatch`

  Expected: FAIL because `build_vsx_crossmatch.py` does not exist.

- [ ] **Step 3: Implement the deterministic builder**

  Query CDS XMatch against VizieR `B/vsx/vsx` only during this build, retain all returned candidates needed to prove uniqueness, assign explicit exclusion statuses, sort deterministically, and record query date, VSX catalogue version, endpoint, 1.0-arcsecond gate, input hashes, row counts, and output hash in provenance.

- [ ] **Step 4: Generate and inspect the frozen catalogue**

  Run: `uv run --project v19 --frozen python v19/scripts/build_vsx_crossmatch.py`

  Expected: both data files are written; eligible rows are confirmed variables with a unique VSX OID and finite positive period; catalogue generation does not touch the measurement database.

- [ ] **Step 5: Run the catalogue tests**

  Run: `uv run --project v19 --frozen python -m unittest -v v19.test_vsx_crossmatch`

  Expected: PASS.

### Task 3: Generate Auditable Chronological Variable-Star Products

**Files:**
- Create: `v19/scripts/plot_mmto_variable_stars.py`
- Create: `plot_mmto_variable_stars_v19.sh`
- Create: `v19/test_plot_mmto_variable_stars.py`

**Interfaces:**
- Consumes: `nightly-extinction/corrected_stellar_photometry.csv` and `v19/data/vsx_crossmatch.csv`.
- Produces: `generate_products(corrected_csv: Path, crossmatch_csv: Path, provenance_json: Path, output: Path, max_period_days: float = 50.0, start_utc: datetime = datetime(2026, 6, 30, tzinfo=UTC)) -> dict[str, object]`.
- Produces files: `variable_star_time_series.pdf`, `variable_star_measurements.csv`, `variable_star_selection_audit.csv`, `variable_star_measurement_audit.csv`, and `variable_star_summary.json`.

- [ ] **Step 1: Write failing selection and photometry tests**

  Assert strict period and flag gates, exact preservation of input `corrected_magnitude`, no use of zero point or distance fields, R/G/B retention, chronological per-channel ordering, rejection of malformed/naive UTC, and `before_start_utc` auditing for a March row.

- [ ] **Step 2: Write failing output tests**

  Assert 4-by-3 pages, inverted magnitude axes, one panel for two catalogue IDs sharing a VSX OID, 13 eligible objects across two PDF pages, schema-valid empty outputs, explanatory empty PDF, input/output hashes in JSON, and refusal to overwrite a nonempty directory.

- [ ] **Step 3: Run the focused tests and observe the missing-plotter failure**

  Run: `uv run --project v19 --frozen python -m unittest -v v19.test_plot_mmto_variable_stars`

  Expected: FAIL because the plotting module and launcher do not exist.

- [ ] **Step 4: Implement loading, selection, and audits**

  Validate required CSV columns and finite numeric values, join on `(catalogue_sha256, star_id)`, deduplicate panels by VSX OID, retain every input row in the measurement audit, and sort panels by `(period_days, vsx_name, vsx_oid)`.

- [ ] **Step 5: Implement PDF and sidecar writing**

  Use `matplotlib.backends.backend_pdf.PdfPages`; draw small R/G/B points against UTC without connecting separate channels or phase folding; invert each magnitude axis; include the shared legend and exact labels from the spec; write atomically into a previously absent or empty output directory.

- [ ] **Step 6: Implement the launcher and CLI**

  Add required `--nightly-calibration` and `--output` options plus `--crossmatch`, `--max-period-days` (default `50.0`), and `--start-utc` (default `2026-06-30T00:00:00Z`). Run exclusively through the frozen v19 project environment.

- [ ] **Step 7: Run the plotter tests**

  Run: `uv run --project v19 --frozen python -m unittest -v v19.test_plot_mmto_variable_stars`

  Expected: PASS.

### Task 4: Integrate the Added Stage Without Changing V16 Products

**Files:**
- Create: `scripts/run_mmto_photometry_pipeline_v19.py`
- Create: `go_mmto_photometry_v19.sh`
- Create: `test_run_mmto_photometry_pipeline_v19.py`

**Interfaces:**
- Consumes: Task 1 solver/launchers and Task 3 plotting launcher.
- Produces: v19 pipeline options `--variable-max-period-days FLOAT` and `--variable-start-utc ISO8601`; output key `variable_star_time_series`; stage order `stellar_lightcurves`, `nightly_extinction`, `variable_star_time_series`, `planet_photometry`, `planet_empirical_extinction`.

- [ ] **Step 1: Write failing v19 pipeline tests**

  Assert solver `0.19.0`/`go19.sh`, v19-only receipts, v16 newest-incomplete-night behavior, `--backfill-v19`, exact equality of the four inherited stage commands with v16, placement of the one added stage, propagation of `50.0` and the UTC boundary, failure propagation, summary output, portable launcher help, and automatic PDF listing.

- [ ] **Step 2: Run the focused tests and observe the missing-pipeline failure**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v19`

  Expected: FAIL because the v19 pipeline does not exist.

- [ ] **Step 3: Implement the v19 pipeline as a narrow v16 copy**

  Preserve the v16 planning, locking, processing, ordinary-stage commands, output refusal, and summary behavior. Change only the version identity/backfill spelling and insert the variable-star command after nightly extinction with both configurable values.

- [ ] **Step 4: Add the portable pipeline launcher**

  `go_mmto_photometry_v19.sh` resolves its repository path and executes the v19 pipeline through the root frozen environment without depending on the caller's working directory or inherited `VIRTUAL_ENV`.

- [ ] **Step 5: Run the pipeline tests**

  Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v19`

  Expected: PASS.

### Task 5: Refresh Manifests, Run Regressions, and Produce the Real Figure

**Files:**
- Modify inside v19 only: `README.md`, `HANDOFF.md`, `docs/FEATURE_STATUS.md`, `data/README.md`, `SOURCE_MANIFEST.json`
- Create under a fresh result path: v19 nightly-extinction and variable-star products

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented v19 commands, complete v19 manifest, verified current-data multipage figure and sidecars.

- [ ] **Step 1: Document the scientific quantity and controls**

  State the exact extinction formula, explicit absence of distance correction, strict period boundary, UTC cutoff and March exclusion, offline VSX provenance, chronological/non-phase-folded layout, and the fact that all ordinary v16 products are retained.

- [ ] **Step 2: Refresh the v19 manifest after all v19 edits**

  Run: `uv run --project v19 --frozen python v19/scripts/update_v19_manifest.py`

  Expected: a subsequent manifest refresh produces no diff.

- [ ] **Step 3: Run focused v19 suites and both v19 demos**

  Run the three new test modules, `./v19/demo.sh --output results/check-v19-milky-way`, and the packaged MMTO demo through `./go19.sh v19/examples/mmto/2026_09_19__02_20_01.fits.bz2 --results-dir results/check-v19-mmto`.

  Expected: all tests and both regressions pass without changing historical references.

- [ ] **Step 4: Run the required repository-wide verification**

  Run: `uv run --frozen python -m unittest discover -v`

  Run: `./demo.sh --output results/check-unique-name-v19`

  Expected: PASS; the demo writes only to the fresh named result directory.

- [ ] **Step 5: Generate current-data products through v19**

  Run the nightly-extinction command into a fresh immutable directory, then run `plot_mmto_variable_stars_v19.sh` with its default 50-day and 2026-06-30 UTC limits into a fresh output directory. Do not alter `results/stars.sqlite` during plotting.

  Expected: the PDF contains every eligible current-data star, March contributes zero plotted points and an audited exclusion, and the JSON counts agree with both CSVs.

- [ ] **Step 6: Inspect final diffs and preservation evidence**

  Run `git diff --check`, compare v16/v17/v18 tree hashes to the initial snapshot, inspect every new launcher permission, and confirm the changed path list contains no preserved runtime or existing result product.

