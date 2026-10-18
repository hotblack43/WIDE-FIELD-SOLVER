# V21 MMTO Header-Time Reprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent v21 runtime that reprocesses downloaded MMTO FITS files, fetches only required missing backlog files, uses authoritative header midpoints, and produces post-blind site/time, transparency, sidereal-map, and secondary planet validation products.

**Architecture:** Freeze committed v20, copy it to v21, and keep the solver blind.  A v21 orchestration layer stores FITS-header observations in a sidecar table in the existing manifest, appends v21 receipts to the existing results database, and runs separate post-fit analysis stages.  Version-specific numerical modules implement the constrained nightly grey-offset model and sidereal comparisons without changing frozen shared v20 code.

**Tech Stack:** Python 3.12, NumPy, SciPy, Astropy, Matplotlib, SQLite, `unittest`, Bash, uv.

**Spec:** `docs/superpowers/specs/2026-10-18-v21-mmto-reprocessing.md`

## Global Constraints

- Preserve v20 bytes and record them in `docs/v20-runtime.json` before v21 development.
- Never use MMTO site/time metadata in blind stellar, refraction, photometric-zenith, or planet fitting.
- Scientific MMTO time comes only from validated FITS header fields; midpoint is start plus half the FITS exposure duration.
- Reuse `results/stars.sqlite` and `raw_allsky_samples/manifest.sqlite` append-only; preserve old rows.
- Retain the per-invocation image cap and one-night-at-a-time remote listing.
- Preserve all detected sources, actual measured positions, and numerical residuals.
- Run the full root unit suite and unique-output demo before completion.

## Review Focus

- Old and new MMTO header generations must reject contradictory clocks rather than fall back to filenames; covered in Task 2.
- V16--v20 receipts must not suppress v21 reprocessing, while any v21 receipt must; covered in Task 3.
- Site/time must remain unavailable to all blind stages, including the secondary planet search; covered in Tasks 3 and 4.
- The `a_s`, `k`, and `Z_i` fit must enforce identifiability and reject deficient rank/leverage; covered in Task 5.
- Sidereal maps must not pair the same night, interpolate insufficient samples, or move measured coordinates; covered in Task 6.

---

### Task 1: Freeze v20 and scaffold the independent v21 runtime

**Files:**
- Create: `docs/v20-runtime.json`
- Create: `scripts/prepare_v21_boundary.py`
- Create: `v21/` as a byte-for-byte copy of committed `v20/`, then update only v21 identities
- Create: `go21.sh`, `go_v0.21.0.sh`, `go_mmto_photometry_v21.sh`
- Create: `test_v21_runtime_boundary.py`
- Modify: `AGENTS.md`, `README.md`, `docs/FEATURE_STATUS.md`

**Interfaces:**
- Produces: solver version `0.21.0`, launchers pinned to `v21/`, and a complete v21 `SOURCE_MANIFEST.json`.

- [ ] Write boundary tests that fail because v20 has no frozen snapshot and v21 does not exist.
- [ ] Run `uv run --frozen python -m unittest -v test_v21_runtime_boundary.py` and verify the expected failures.
- [ ] Restore temporary v20 production edits, preserving `docs/FOR_LATER.md` and the user's `improvements_note.txt`; generate the v20 snapshot from committed bytes.
- [ ] Copy v20 to v21, update version-local names and manifests, and add the three v21 launchers.
- [ ] Re-run the boundary tests and verify they pass.

### Task 2: Parse and persist authoritative FITS-header observations

**Files:**
- Create: `v21/mmto_time.py`
- Create: `v21/mmto_observations.py`
- Create: `v21/test_mmto_time.py`
- Create: `test_mmto_observations_v21.py`

**Interfaces:**
- Produces: `read_mmto_observation(path: Path) -> MMTOObservation`.
- Produces: `record_observation(connection, source_sha256, remote_url, discovery_utc, observation)` and read APIs keyed by checksum.

- [ ] Write failing tests for old local headers, new UTC headers, compressed FITS, midpoint calculation, contradictory fields, missing exposure, and filename independence.
- [ ] Run the focused tests and verify each new behavior fails for the intended reason.
- [ ] Implement the two header schemas with explicit consistency tolerances and no recognised-MMTO filename fallback.
- [ ] Write failing sidecar-table tests proving old manifest timestamps remain preserved and header provenance is queryable by checksum.
- [ ] Implement transactional schema creation, conflict detection, and idempotent persistence.
- [ ] Run both focused suites and verify they pass.

### Task 3: Implement reuse-first bounded v21 acquisition and processing

**Files:**
- Create: `scripts/run_mmto_photometry_pipeline_v21.py`
- Create: `test_run_mmto_photometry_pipeline_v21.py`
- Modify: `go_mmto_photometry_v21.sh`

**Interfaces:**
- Consumes: `read_mmto_observation` and the v21 observation sidecar API.
- Produces: a capped acquisition plan, v21-only receipt filtering, validated reused/downloaded inputs, v21 receipts, and a pipeline summary.

- [ ] Write failing tests for local-first selection, v20-receipt reprocessing, v21-receipt skipping, one-night remote listing, cap enforcement, download-only-when-missing, and cursor advancement only after durable receipts.
- [ ] Verify the tests fail against the absent v21 orchestrator.
- [ ] Port the v20 planner with `0.21.0` receipt semantics and parse/persist the header before every solve.
- [ ] Force `--blind-planets` in pipeline solver commands and test that no site/time arguments reach `go21.sh`.
- [ ] Run focused orchestration tests and verify they pass.

### Task 4: Add separate known-site/time and secondary planet validation

**Files:**
- Create: `v21/mmto_validation.py`
- Create: `v21/test_mmto_validation.py`
- Create: `scripts/validate_mmto_site_time_v21.py`
- Create: `test_validate_mmto_site_time_v21.py`
- Modify: `scripts/run_mmto_photometry_pipeline_v21.py`

**Interfaces:**
- Consumes: successful v21 database products plus authoritative observation sidecars.
- Produces: `mmto_site_time_validation.csv`, `mmto_airmass_validation.csv`, `mmto_planet_epoch_validation.csv`, JSON provenance, and labelled diagnostic figures.

- [ ] Write failing numerical tests for predicted zenith, known-latitude residual, metadata airmass, stellar epoch difference, and planet comparison that leaves candidates unchanged.
- [ ] Implement pure validation calculations using Astropy after fits are fixed.
- [ ] Write failing integration tests proving only successful v21 runs are loaded and source fits/database rows are not rewritten.
- [ ] Implement the read-only CLI and add it as a post-processing stage.
- [ ] Run focused validation tests and verify they pass.

### Task 5: Fit per-exposure grey transparency terms

**Files:**
- Create: `v21/mmto_nightly_extinction.py`
- Create: `v21/test_mmto_nightly_extinction.py`
- Create: `scripts/calibrate_nightly_extinction_v21.py`
- Create: `calibrate_mmto_extinction_v21.sh`
- Create: `test_calibrate_nightly_extinction_v21.py`
- Modify: `scripts/run_mmto_photometry_pipeline_v21.py`

**Interfaces:**
- Produces: robust constrained `m(s,i)=a_s+kX(s,i)+Z_i` fits and v21 calibration tables compatible with downstream joins.

- [ ] Write failing synthetic tests recovering a shared slope, star intercepts, and injected zero-mean image offsets with one severe outlier.
- [ ] Add failing tests for the sum-to-zero constraint, deficient rank/leverage, fixed sample membership, and uncertainty/status reporting.
- [ ] Implement the sparse soft-L1 fit and per-image absolute/relative zero-point records.
- [ ] Write failing CLI-output tests for formula/provenance, corrected magnitudes subtracting `kX+Z_i`, and grey-transparency figures.
- [ ] Implement v21 read-only loading restricted to successful v21 runs and write the new products.
- [ ] Run focused numerical and CLI tests and verify they pass.

### Task 6: Generate same-sidereal-time differential transmission maps

**Files:**
- Create: `v21/mmto_sidereal_transmission.py`
- Create: `v21/test_mmto_sidereal_transmission.py`
- Create: `scripts/map_mmto_sidereal_transmission_v21.py`
- Create: `test_map_mmto_sidereal_transmission_v21.py`
- Modify: `scripts/run_mmto_photometry_pipeline_v21.py`

**Interfaces:**
- Consumes: successful v21 stellar photometry/coordinates, header midpoints, known longitude, and v21 transparency products.
- Produces: pair audit/summary CSVs, per-star differential rows at measured pixels, a manifest, and labelled map figures.

- [ ] Write failing tests for apparent-sidereal-time wraparound, distinct-night pairing, tolerance boundaries, and deterministic one-to-one pair choice.
- [ ] Implement pure pair selection using Astropy sidereal time.
- [ ] Write failing tests for same-star magnitude differences, pair-wide grey centring, faithful measured coordinates, channel separation, and insufficient coverage.
- [ ] Implement differential rows and non-interpolated measured-point maps with explicit sample counts/status.
- [ ] Add the stage after v21 nightly calibration and run focused tests to green.

### Task 7: Integrate, document, verify, and prepare bounded execution

**Files:**
- Modify: `README.md`, `docs/FEATURE_STATUS.md`, `v21/README.md`, `v21/HANDOFF.md`, `v21/SOURCE_MANIFEST.json`
- Create: `docs/V21_MMTO_HEADER_TIME.md`
- Modify: relevant v21/report documentation only; do not alter frozen v20 files

**Interfaces:**
- Produces: inspectable v21 dry-run plan and documented output/provenance paths suitable for local or Monster2 execution.

- [ ] Run all v21-focused tests and `git diff --check`.
- [ ] Run `uv run --frozen python -m unittest discover -v` and record every failure if any.
- [ ] Run `./demo.sh --output results/check-unique-name` without overwriting historical evidence.
- [ ] Run `./go_mmto_photometry_v21.sh --dry-run` and inspect that local files are selected before remote gaps, no files are downloaded, and no state advances.
- [ ] Verify v20 snapshot hashes, regenerate the v21 source manifest deliberately, and rerun boundary tests.
- [ ] Document Monster2 invocation only after verifying its existing synchronization/host conventions; do not start bulk processing until the local implementation and dry-run are verified.
