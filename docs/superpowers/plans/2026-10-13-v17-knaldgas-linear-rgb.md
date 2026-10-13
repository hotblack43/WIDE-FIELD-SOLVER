# V17 KNALDGAS Linear-RGB Solver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the independent v17 KNALDGAS runtime and launchers so Peter can select linear KNALDGAS FITS files and receive reports that show every identified star while labelling bright Bayer stars first.

**Architecture:** Freeze the current tested v16 runtime, mechanically fork it into a self-contained v17 package, then make KNALDGAS-only display changes inside v17. Astrometry continues on one linear luminance image and photometry continues independently on native R, G and B planes; only post-fit naming, annotation selection and report rendering change.

**Tech Stack:** Bash, Python 3.12, NumPy, Astropy FITS, Matplotlib, adjustText, unittest, uv.

**Spec:** `docs/superpowers/specs/2026-10-13-v17-knaldgas-linear-rgb.md`

## Global Constraints

- Use numbered runtime directories and launchers only; do not create a Git branch or worktree.
- Preserve v16 and every earlier package after recording `docs/v16-runtime.json`.
- V17 is version `0.17.0` and imports runtime code/data only from `v17/`.
- Input KNALDGAS FITS remains linear; no display transform may enter detection, astrometry or photometry.
- Existing `/media/pth/Sandisk8TB/KNALDGAS/FITS_RGB_MMTO/` and v16 results are read-only.
- New validation results go under `/media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17/`.
- Names remain post-fit, display-only metadata and never seed or select the blind solve.
- Maintain a maximum of 40 text labels while displaying every catalogue-associated star.
- Do not relax regression thresholds or alter measured/predicted coordinates cosmetically.

## Review Focus

- A quoted wildcard matching no files must reject the whole request before any solver run starts; Task 2 tests it.
- Mixed valid FITS and unsupported/nonexistent arguments must not produce a partial batch; Task 2 tests it.
- SIMBAD/network failure must preserve the solved report using cached ordinary aliases without printing long Gaia IDs; Task 3 tests it.
- A bright broad or saturated associated source must remain label-eligible while its photometry quality flags remain unchanged; Tasks 3 and 5 test it.
- Fewer than 40 ordinary aliases must yield an honest smaller labelled count while retaining the full identified-marker count; Task 4 tests it.

---

### Task 1: Freeze v16 and create the independent v17 boundary

**Files:**
- Create: `docs/v16-runtime.json`
- Create: `v17/` from tracked/current v16 sources, excluding `.venv/` and `__pycache__/`
- Create: `v17/scripts/update_v17_manifest.py`
- Create: `v17/SOURCE_MANIFEST.json`
- Create: `test_v17_boundary.py`
- Modify: `AGENTS.md`
- Modify: `v17/pyproject.toml`
- Modify: `v17/uv.lock`
- Modify: version-bearing files copied into `v17/`

**Interfaces:**
- Consumes: current tested v16 files and launchers as the immutable parent snapshot.
- Produces: independent `v17/` package at version `0.17.0`; `docs/v16-runtime.json`; deterministic `v17/SOURCE_MANIFEST.json`.

- [ ] **Step 1: Write the failing v17 boundary tests**

Add `V17BoundaryTests` asserting that the v16 snapshot matches every recorded byte, v17 reports `0.17.0`, v17 owns its lock/catalogue/ephemeris files, and its source manifest covers every v17 file except itself.

- [ ] **Step 2: Run the boundary test and verify RED**

Run: `uv run --frozen python -m unittest -v test_v17_boundary.py`

Expected: FAIL because `docs/v16-runtime.json`, `v17/`, and the v17 launchers do not exist.

- [ ] **Step 3: Record and fork the runtime**

Create the v16 snapshot from exact current bytes; copy v16 to v17 without generated environments/caches; change package/runtime version strings to `0.17.0`; create the deterministic v17 manifest updater with parent snapshot `../docs/v16-runtime.json`; update the root version-boundary documentation.

- [ ] **Step 4: Run boundary tests and verify GREEN**

Run: `uv run --frozen python -m unittest -v test_v17_boundary.py test_v16_boundary.py`

Expected: both boundary suites PASS and every v16 hash remains fixed.

- [ ] **Step 5: Commit the boundary**

Commit only the snapshot, v17 package, boundary test and boundary documentation with message `feat: establish independent v17 runtime`.

### Task 2: Add selectable KNALDGAS v17 launchers

**Files:**
- Create: `go17.sh`
- Create: `go_v0.17.0.sh`
- Create: `go_fits_v17.sh`
- Create: `test_go_fits_v17.py`
- Modify: `test_v17_boundary.py`

**Interfaces:**
- Consumes: `v17/run.sh` and v17 version identity from Task 1.
- Produces: `go17.sh IMAGE [options]`; `go_v0.17.0.sh IMAGE [options]`; `go_fits_v17.sh IMAGE_OR_PATTERN... [--results-dir DIR]` with atomic preflight expansion.

- [ ] **Step 1: Write failing launcher tests**

Port the v16 designated-FITS tests to v17 and add a mixed-input preflight case. Assert direct `.fits`/`.fits.bz2`, multiple CLI arguments, and quoted wildcards invoke v17 once per resolved image; assert no-match or one invalid argument invokes it zero times and returns nonzero.

- [ ] **Step 2: Run launcher tests and verify RED**

Run: `uv run --frozen python -m unittest -v test_go_fits_v17.py`

Expected: FAIL because the v17 launchers are absent.

- [ ] **Step 3: Implement the launchers**

Make `go17.sh` and `go_v0.17.0.sh` exec only `v17/run.sh`. Implement `go_fits_v17.sh` from the tested v16 wrapper, changing only v17 identity and help text to name KNALDGAS linear RGB FITS; expand and validate the complete batch before starting any solve.

- [ ] **Step 4: Run launcher and boundary tests and verify GREEN**

Run: `uv run --frozen python -m unittest -v test_go_fits_v17.py test_v17_boundary.py`

Expected: all tests PASS.

- [ ] **Step 5: Commit the launchers**

Commit the three launchers and tests with message `feat: add selectable KNALDGAS v17 launchers`.

### Task 3: Select bright Bayer labels after the blind fit

**Files:**
- Modify: `v17/point_star_names.py`
- Modify: `v17/point_star_barghini.py`
- Modify: `v17/test_point_star_names.py`
- Modify: `v17/test_point_star_barghini.py`

**Interfaces:**
- Produces: `bayer_label_key(display_name: str) -> tuple[int, str] | None`; `select_labels(rows, count=40, *, names=None)` returning display candidates in Bayer-round then magnitude order; `labelled_stars.json` with `identified_count`, `labelled_count`, `identified_stars`, and `stars`.
- Consumes: post-fit association rows and `resolve_names(...)`; no fit-stage inputs.

- [ ] **Step 1: Write failing Bayer parsing and selection tests**

Assert Unicode alpha including numbered components parses before beta/gamma; all alpha candidates sort by magnitude before all beta candidates; accurately associated `broad_blob` rows remain eligible; poor residuals are excluded; non-Bayer named stars fill after Bayer names; unresolved Gaia identifiers consume no text-label slot.

- [ ] **Step 2: Run selection tests and verify RED**

Run: `cd v17 && uv run --frozen python -m unittest -v test_point_star_names.py test_point_star_barghini.py`

Expected: new tests FAIL because Bayer keys, name-aware ordering and broad-source eligibility are absent.

- [ ] **Step 3: Implement post-fit naming and label selection**

Define the fixed Bayer Greek order in `point_star_names.py`. In `annotate_stars`, form the accurate association set, resolve aliases for the brightest `max(160, 4*count)` candidates only after fitting, select at most `count` ordinary aliases with Bayer-round priority, and retain every association position in the JSON marker list. On lookup failure, keep cached/local names and omit unresolved Gaia text.

- [ ] **Step 4: Run selection tests and verify GREEN**

Run: `cd v17 && uv run --frozen python -m unittest -v test_point_star_names.py test_point_star_barghini.py`

Expected: all name and selection tests PASS.

- [ ] **Step 5: Commit the selection policy**

Commit v17 name/selection code and tests with message `feat: prioritize Bayer labels for KNALDGAS reports`.

### Task 4: Show all identified stars and honest label counts

**Files:**
- Modify: `v17/point_star_report.py`
- Modify: `v17/test_point_star_report.py`
- Modify: `v17/point_star_barghini.py`

**Interfaces:**
- Consumes: Task 3 `labelled_stars.json` fields.
- Produces: overlay with one small marker per identified star, ring/text for labelled stars only, and explicit identified/labelled counts in title/legend.

- [ ] **Step 1: Write failing report-marker tests**

Construct 55 identified positions and 45 label candidates. Assert the rendered axes contain all 55 measured marker coordinates, exactly 40 text labels, legends containing `55 identified` and `40 labelled`, no printed Gaia numeric ID, and zero post-layout conflicts. Add the fewer-than-40-alias case and assert its truthful label count.

- [ ] **Step 2: Run report tests and verify RED**

Run: `cd v17 && uv run --frozen python -m unittest -v test_point_star_report.py`

Expected: new tests FAIL because the current report draws only selected labelled stars.

- [ ] **Step 3: Implement separate marker and label rendering**

Plot `identified_stars` as a faint scatter layer at their unchanged measured coordinates. Plot labelled stars with the existing rings, text and collision solver. Update the standalone annotation title, report legend and JSON selection description without changing any coordinate field.

- [ ] **Step 4: Run report and FITS-overlay tests and verify GREEN**

Run: `cd v17 && uv run --frozen python -m unittest -v test_point_star_report.py test_point_star_plotting.py test_point_star_fits.py test_point_star_fits_ds9.py`

Expected: all tests PASS; label layout reports no conflicts in its controlled fixtures.

- [ ] **Step 5: Commit the report rendering**

Commit v17 report code and tests with message `feat: distinguish identified and labelled stars`.

### Task 5: Document KNALDGAS and preserve the linear science path

**Files:**
- Create: `v17/docs/KNALDGAS.md`
- Modify: `v17/README.md`
- Modify: `v17/docs/FEATURE_STATUS.md`
- Modify: `v17/test_point_star_image.py`
- Modify: `v17/test_point_star_science.py`
- Modify: `v17/SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: v17 FITS loader, luminance detection path, per-channel `measure_photometry`, launchers from Task 2.
- Produces: documented KNALDGAS command examples and regressions proving gamma is report-only.

- [ ] **Step 1: Strengthen the inherited science-path characterization**

Add a synthetic linear RGB FITS test with deliberately unequal channel values. Assert detection receives `0.2126R + 0.7152G + 0.0722B`, per-channel photometry receives the unchanged R/G/B arrays at the shared measured coordinates, report rendering does not mutate them, and a broad/saturated label decision does not alter saturation flags or photometry rows.

- [ ] **Step 2: Run science-path tests and verify the inherited behavior**

Run: `cd v17 && uv run --frozen python -m unittest -v test_point_star_image.py test_point_star_detection.py test_point_star_science.py test_point_star_photometry.py`

Expected: the characterization passes because v17 deliberately inherits the already-tested linear science path. If it exposes a gap, add a focused failing test before the smallest production fix; do not alter working science code merely to force a RED phase.

- [ ] **Step 3: Add v17 provenance and documentation without changing science arrays**

Keep native arrays immutable, record the linear KNALDGAS provenance in reports, and document the exact commands:

```bash
./go17.sh /media/pth/Sandisk8TB/KNALDGAS/FITS_RGB_MMTO/R6m2/example_RGB.fits.bz2 \
  --results-dir /media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17

./go_fits_v17.sh '/media/pth/Sandisk8TB/KNALDGAS/FITS_RGB_MMTO/R6m2/*_RGB.fits.bz2' \
  --results-dir /media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17
```

- [ ] **Step 4: Run v17 science tests and verify GREEN**

Run: `cd v17 && uv run --frozen python -m unittest discover -v`

Expected: the complete v17 suite PASS.

- [ ] **Step 5: Refresh manifest and commit**

Run the deterministic v17 manifest updater, rerun `test_v17_boundary.py`, then commit documentation, tests, any minimal wiring and manifest with message `docs: define KNALDGAS v17 workflow`.

### Task 6: Validate a real selected KNALDGAS image and the repository

**Files:**
- Create outside repository: `/media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17/...`
- Modify only if a regression fails: the v17 file owning that behavior, with a new failing test first.

**Interfaces:**
- Consumes: completed v17 launchers/runtime and the existing representative linear FITS.
- Produces: v17 annotated PNG, report PDF, result JSON, photometry CSV and database receipt in the new v17 results tree.

- [ ] **Step 1: Run the representative input through v17**

Run `go_fits_v17.sh` on `20261012_214858_ISO100_30.000s_RGB.fits.bz2` with the dedicated v17 results directory.

Expected: one new v17 run; input checksum unchanged; no v16 result modified.

- [ ] **Step 2: Compare v16 and v17 science results**

Assert association count `542`, RMS `0.3608139051159004 px` within floating-point serialization tolerance, matching measured star coordinates, and matching native R/G/B photometry rows. Annotation membership/order may differ.

- [ ] **Step 3: Render and inspect every PDF page**

Use `pdftoppm` in `tmp/pdfs/`; inspect all pages. Assert the first page visibly shows the rich sky, all identified-star markers, Bayer-priority labels, explicit identified/labelled counts and the display-only stretch statement; remove temporary renders afterward.

- [ ] **Step 4: Run required repository verification**

Run:

```bash
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-v17-knaldgas-20261013
./v17/demo.sh --output results/check-v17-package-knaldgas-20261013
git diff --check
```

Expected: all tests and both demos PASS; diff check is clean.

- [ ] **Step 5: Commit validation evidence that belongs in the repository**

Update v17 feature status with numerical/visual validation facts, refresh the v17 manifest, rerun boundary tests, and commit with message `test: validate v17 on KNALDGAS linear RGB`.
