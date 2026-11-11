# V24 Camera-Installation Visible-Sky Mask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behaviour change and superpowers:verification-before-completion before claiming success.

**Goal:** Build, approve, and enforce an immutable MMTO detector-coordinate visible-sky mask so fixed foreground pixels cannot contribute detections, fits, photometry, or astronomical absence evidence.

**Architecture:** A read-only calibration builder combines representative HDR FITS frames into a reviewable draft. After Peter approves the boundary, v24 loads the frozen binary mask through an installation manifest, intersects it with finite-pixel and dynamic-footprint validity at decode time, and preserves the three mask layers through detection, photometry, planet/lunar handling, reports, and the bounded MMTO pipeline.

**Tech Stack:** Python 3.12, NumPy, SciPy, Astropy FITS, Pillow/Matplotlib, existing v23 solver and `unittest` infrastructure, shell launchers, append-only JSON/JSONL provenance.

**Spec:** `docs/superpowers/specs/2026-11-11-v24-visible-sky-mask-design.md`

## Global Constraints

- Freeze v23 exactly and develop only in a new self-contained v24 runtime and v24 launchers.
- Use original MMTO FITS data for calibration; previews are review products only.
- Pixel 255 is usable visible sky and pixel 0 is excluded; no other values, resizing, registration, or interpolation are permitted.
- Detector `(x, y)` is array `[y, x]`, with `(0, 0)` at the top left of existing solver products.
- Apply the five-pixel safety margin by expanding the excluded region after the reviewed boundary is fixed.
- A draft mask cannot be selected by a production launcher. Peter's approval of the actual review overlay is a hard stage boundary.
- Preserve all source centroids and model predictions. The mask may reject pixels and measurements but must never shift them.
- Keep fixed-mask, dynamic-footprint, and nonfinite exclusions distinct in saved evidence and status reasons.
- Installation identity is operator-managed and append-only. A moved, rotated, or replaced camera requires a new identifier and mask.
- Preserve unrelated working-tree changes and the historical reference products.

## Review Focus

- The mask must cover the southwest building silhouette containing the September Venus predictions and the opposing low-horizon structure containing the November predictions.
- Thin poles, antennae, camera housing, and the exterior of the optical field must be excluded without eroding ordinary sky unnecessarily.
- Bright/cloudy/twilight frames must not move the fixed boundary.
- No signal behind the boundary may leak through convolution, connected components, partial apertures, targeted recovery, or negative-evidence code.
- A generic solver invocation without mask configuration must preserve the v23 numerical path.

---

### Task 1: Freeze v23 and establish the v24 runtime boundary

**Files:**
- Create: `docs/v23-runtime.json`
- Create: `scripts/prepare_v24_boundary.py`
- Create: `test_v24_runtime_boundary.py`
- Create: `v24/` as a clean copy of tracked v23 runtime files
- Create: `go24.sh`
- Create: `go_v0.24.0.sh`
- Create: `go_mmto_photometry_v24.sh`
- Create: `scripts/run_mmto_photometry_pipeline_v24.py`
- Create: `v24/scripts/update_v24_manifest.py`
- Create/refresh: `v24/SOURCE_MANIFEST.json`
- Modify: `AGENTS.md`

**Interfaces:**
- `prepare_v24_boundary.py` verifies the committed v23 file list and SHA-256 values.
- v24 launchers select only v24 source and environment paths and report solver version `0.24.0`.

- [ ] **Step 1: Write failing boundary tests**

Assert that all v23 files and launchers match `docs/v23-runtime.json`, v24 has no imports from v23, and the v24 launchers point only at v24 entry points.

- [ ] **Step 2: Run the boundary test and verify the expected failure**

Run: `uv run --frozen python -m unittest -v test_v24_runtime_boundary.py`

Expected: FAIL because the v24 boundary and runtime do not yet exist.

- [ ] **Step 3: Generate the immutable v23 boundary and mechanically copy tracked runtime files**

Exclude `.venv`, `__pycache__`, generated examples, and other untracked products. Rename v23-specific version strings, scripts, launchers, tests, and manifest tooling without changing numerical behaviour.

- [ ] **Step 4: Update the version policy**

Record v23 as frozen at the v24 boundary and v24 as the only development location for the visible-sky mask.

- [ ] **Step 5: Run the boundary and no-mask parity tests**

Run: `uv run --frozen python -m unittest -v test_v24_runtime_boundary.py v24.test_point_star_barghini`

Expected: PASS, with no numerical changes in an unmasked solve.

- [ ] **Step 6: Commit the version boundary**

Commit: `chore: establish v24 visible-sky-mask runtime`

### Task 2: Build the temporal-consensus draft and review products

**Files:**
- Create: `v24/scripts/build_visible_sky_mask.py`
- Create: `v24/test_visible_sky_mask_builder.py`
- Create: `v24/data/sky_masks/README.md`
- Create: `v24/examples/mmto/visible_sky_mask_review/selection.json`
- Create: `v24/examples/mmto/visible_sky_mask_review/mmto_installation_2026a.draft.png`
- Create: `v24/examples/mmto/visible_sky_mask_review/temporal_reference.png`
- Create: `v24/examples/mmto/visible_sky_mask_review/boundary_review.png`
- Create: `v24/examples/mmto/visible_sky_mask_review/boundary_review_inverted.png`

**Interfaces:**
- `build_visible_sky_mask.py propose --sources <json> --output <dir>` reads FITS frames and writes only draft/review artifacts.
- The command refuses to overwrite an existing directory or emit an approved production manifest.
- `selection.json` records source path, source SHA-256, observation coverage, normalization, consensus thresholds, and generation-code SHA-256.

- [ ] **Step 1: Write failing builder tests**

Test deterministic representative-frame selection, native FITS reads, robust per-frame normalization, temporal median/edge/source-density accumulation, binary draft output, coordinate convention, and overwrite refusal.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_mask_builder.py`

Expected: FAIL because the builder does not exist.

- [ ] **Step 3: Implement the proposal builder**

Use one or more representative images per observing date across September--November, retaining darkness/twilight and cloud diversity. Derive a fixed boundary from temporal intensity, edge persistence, and existing source-density evidence; do not inspect planet positions while forming it.

- [ ] **Step 4: Generate the MMTO proposal**

Run the builder against the archived native FITS images and write all review products under `v24/examples/mmto/visible_sky_mask_review/`.

- [ ] **Step 5: Validate the draft scientifically and mechanically**

Confirm exact `1422 x 1411` array shape, binary values, fixed-structure exclusion, ordinary-star retention immediately inside the boundary, and agreement across representative dates. Overlay, but do not use as construction inputs, the September and November Venus detector predictions to verify that both lie behind the proposed foreground boundary.

- [ ] **Step 6: Stop for Peter's visual approval**

Present `boundary_review.png`, `boundary_review_inverted.png`, and the draft mask. Do not create an approved production manifest or enable a launcher until Peter approves or corrects this exact outline.

- [ ] **Step 7: Commit and push the review stage**

Commit: `feat: add reviewable MMTO visible-sky mask draft`

Push the review commit to the requested GitHub branch so the exact evidence under review is preserved.

### Task 3: Freeze the approved installation mask and provenance

**Files:**
- Create: `v24/point_star_visible_sky.py`
- Create: `v24/test_point_star_visible_sky.py`
- Create after approval: `v24/data/sky_masks/mmto_installation_2026a.png`
- Create after approval: `v24/data/sky_masks/mmto_installation_2026a.json`
- Modify: `v24/examples/mmto/visible_sky_mask_review/selection.json`

**Interfaces:**
- `VisibleSkyMask.load(manifest_path, *, installation_id, instrument, detector_shape, plane_layout, orientation)` validates identity, binary pixels, checksum, shape, and orientation.
- `VisibleSkyMask.combine(dynamic_mask, finite_mask) -> MaskLayers` returns immutable static, dynamic, finite, and combined masks plus pixel counts.
- Production manifest includes Peter's approval date and the SHA-256 of the reviewed draft.

- [ ] **Step 1: Write failing manifest and loader tests**

Cover valid load plus non-binary, wrong-shape, wrong-checksum, wrong-instrument, wrong-plane-layout, wrong-orientation, and wrong-installation rejection.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_visible_sky.py`

Expected: FAIL because the loader does not exist.

- [ ] **Step 3: Apply approved corrections and safety margin**

Modify only the reviewed boundary, expand excluded foreground inward by five pixels, and write a new immutable production artifact without overwriting the draft.

- [ ] **Step 4: Implement strict loading and layer combination**

Fail closed for configured MMTO runs. Keep the optional generic no-mask path as `not_configured` and byte/numerically equivalent to v23.

- [ ] **Step 5: Run focused tests and record final checksums**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_visible_sky.py test_visible_sky_mask_builder.py`

Expected: PASS.

- [ ] **Step 6: Commit the approved calibration**

Commit: `feat: freeze MMTO camera-installation sky mask`

### Task 4: Enforce the mask in detection and astrometric fitting

**Files:**
- Modify: `v24/analyse_image.py`
- Modify: `v24/point_star_barghini.py`
- Modify: `v24/point_star_image.py`
- Modify: `v24/point_star_detection.py`
- Modify: `v24/point_star_footprint.py`
- Modify: `v24/point_star_diagnostics.py`
- Modify: `v24/point_star_storage.py`
- Modify: `v24/test_point_star_image.py`
- Modify: `v24/test_point_star_detection.py`
- Modify: `v24/test_point_star_barghini.py`
- Create: `v24/test_visible_sky_mask_integration.py`

**Interfaces:**
- Add CLI options `--visible-sky-mask-manifest` and `--camera-installation-id`.
- `ScientificImage` carries distinct finite/static mask context while preserving the existing v23 channel arrays.
- `DetectionAudit` saves static, dynamic, and combined counts and a compressed combined mask.

- [ ] **Step 1: Write failing detection-boundary tests**

Place bright, broad, large, and saturated synthetic sources behind the static mask, immediately outside it, and straddling it. Assert excluded signals produce no eligible detection and do not change background/noise or neighbouring centroids.

- [ ] **Step 2: Run the tests and verify the expected failures**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_mask_integration.py test_point_star_detection.py`

- [ ] **Step 3: Load and combine masks before detection**

Use robust valid-pixel fill only for numerical convolution input; enforce combined eligibility for thresholds, local maxima, component support, centroiding, and final candidate admission.

- [ ] **Step 4: Block excluded candidates from association and fit inputs**

Assert that every associated/fitted detection has support within the combined mask. Do not alter centroid coordinates or plotted predictions.

- [ ] **Step 5: Save mask-layer evidence**

Write the static manifest reference, layer counts, compressed combined mask, and mask-specific rejection counts into the run output.

- [ ] **Step 6: Run focused detection and astrometry tests**

Run: `cd v24 && uv run --frozen python -m unittest -v test_visible_sky_mask_integration.py test_point_star_detection.py test_point_star_barghini.py`

Expected: PASS, including no-mask parity.

- [ ] **Step 7: Commit detection integration**

Commit: `feat: exclude fixed foreground before source detection`

### Task 5: Propagate layer-aware exclusion through photometry and astronomical evidence

**Files:**
- Modify: `v24/point_star_photometry.py`
- Modify: `v24/point_star_science.py`
- Modify: `v24/point_star_planets.py`
- Modify: `v24/point_star_planet_nondetections.py`
- Modify: `v24/point_star_planet_refinement.py`
- Modify: `v24/point_star_lunar.py`
- Modify: `v24/mmto_planet_relative_photometry.py`
- Modify: `v24/test_point_star_photometry.py`
- Modify: `v24/test_point_star_planets.py`
- Modify: `v24/test_planet_nondetections.py`
- Modify: `v24/test_point_star_lunar.py`
- Modify: `v24/test_mmto_planet_relative_photometry.py`

**Interfaces:**
- A static-mask aperture/annulus overlap yields a retained unusable row with `aperture_or_annulus_intersects_visible_sky_mask`.
- A statically masked planet prediction yields `masked_obstruction`, contributes neutral negative evidence, and cannot enter targeted recovery.
- Dynamic-footprint and nonfinite exclusions retain their v23 statuses and precedence.

- [ ] **Step 1: Write failing photometry overlap tests**

Cover aperture-only, annulus-only, static, dynamic, and nonfinite intersections; assert partial apertures are not rescaled and reason codes remain distinct.

- [ ] **Step 2: Write failing planet and lunar tests**

Assert `masked_obstruction` is persisted, gives zero absence penalty, bypasses targeted recovery, and prevents a boundary-truncated lunar candidate from establishing presence or absence.

- [ ] **Step 3: Run the focused tests and verify they fail**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_photometry.py test_point_star_planets.py test_planet_nondetections.py test_point_star_lunar.py`

- [ ] **Step 4: Implement layer-aware measurement eligibility**

Carry the exact saved mask identity into downstream metadata-time photometry. Never reconstruct or relearn the mask from a current frame.

- [ ] **Step 5: Implement neutral masked astronomical evidence**

Apply the existing below-horizon, off-detector, noninvertible, and dynamic-footprint precedence before the new static obstruction status.

- [ ] **Step 6: Run the focused science tests**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_photometry.py test_point_star_science.py test_point_star_planets.py test_planet_nondetections.py test_point_star_lunar.py test_mmto_planet_relative_photometry.py`

Expected: PASS.

- [ ] **Step 7: Commit science integration**

Commit: `feat: propagate foreground mask through photometry evidence`

### Task 6: Add installation assignments and require the mask in MMTO v24

**Files:**
- Modify: `scripts/run_mmto_photometry_pipeline_v24.py`
- Create: `scripts/mmto_camera_installations.py`
- Create: `test_mmto_camera_installations.py`
- Create: `test_run_mmto_photometry_pipeline_v24.py`
- Modify: `go_mmto_photometry_v24.sh`
- Modify: `v24/mmto_observations.py`
- Modify: `v24/point_star_database.py`

**Interfaces:**
- Append-only installation records identify active hardware and mask manifest.
- Append-only `source_sha256 -> installation_id` assignments control solve-time selection.
- The MMTO launcher refuses unassigned input or any mask identity/shape/checksum/orientation mismatch.
- Only successful v24 receipts count as completed v24 analyses.

- [ ] **Step 1: Write failing assignment and planner tests**

Test immutable assignment, conflicting reassignment rejection, audited historical migration, future active-installation assignment, moved-camera reset, unassigned-input refusal, and v23-receipt reprocessing.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run --frozen python -m unittest -v test_mmto_camera_installations.py test_run_mmto_photometry_pipeline_v24.py`

- [ ] **Step 3: Implement append-only installation storage**

Validate FITS identity and source hash before assignment. Do not infer installation from dates, filenames, site metadata, or an astrometric solution.

- [ ] **Step 4: Audit and assign the stable September--November archive population**

Persist the measured skyline-consistency evidence for the 927 sampled images. Audit any additional historical frame before assigning it.

- [ ] **Step 5: Enforce the mask in the v24 launcher**

Pass the immutable manifest and installation ID into every solver invocation, save them in receipts/database rows, and reject a production run with draft or absent calibration.

- [ ] **Step 6: Run focused pipeline tests and a bounded dry run**

Run: `uv run --frozen python -m unittest -v test_mmto_camera_installations.py test_run_mmto_photometry_pipeline_v24.py`

Run: `./go_mmto_photometry_v24.sh --dry-run --max-images 2`

Expected: PASS; selected frames report one validated installation and approved mask.

- [ ] **Step 7: Commit pipeline integration**

Commit: `feat: bind MMTO v24 runs to camera installation mask`

### Task 7: Add investigator-facing evidence and documentation

**Files:**
- Modify: `v24/point_star_plotting.py`
- Modify: `v24/point_star_report.py`
- Modify: `v24/point_star_fits.py`
- Modify: `v24/test_point_star_plotting.py`
- Modify: `v24/test_point_star_report.py`
- Modify: `v24/test_point_star_fits.py`
- Modify: `v24/docs/FEATURE_STATUS.md`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `v24/README.md`
- Modify: `v24/HANDOFF.md`

**Interfaces:**
- Produce `analysis/dots/visible_sky_mask.png` with excluded pixels shaded and the exact approved boundary drawn.
- Reports record installation ID, mask ID/checksum, layer pixel counts, usable fraction, and mask-specific detection/photometry/planet counts.
- FITS/CSV/JSON products retain enough mask metadata to reproduce eligibility decisions.

- [ ] **Step 1: Write failing product tests**

Assert exact overlay geometry, unchanged marker coordinates, manifest identity in report/FITS outputs, and all required mask-layer counters.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_plotting.py test_point_star_report.py test_point_star_fits.py`

- [ ] **Step 3: Implement the overlay and report evidence**

Use normal-intensity image rendering; never alter source positions or numerical residuals. Clearly distinguish static foreground from dynamic footprint.

- [ ] **Step 4: Document numerical and operational changes**

Record calibration provenance, reset procedure, new status/reason codes, MMTO reprocessing rule, and bounded comparison with v23 results.

- [ ] **Step 5: Run focused product tests**

Run: `cd v24 && uv run --frozen python -m unittest -v test_point_star_plotting.py test_point_star_report.py test_point_star_fits.py`

Expected: PASS.

- [ ] **Step 6: Commit evidence and documentation**

Commit: `docs: document v24 visible-sky mask evidence`

### Task 8: Full verification, review, integration, and GitHub push

**Files:**
- Refresh: `v24/SOURCE_MANIFEST.json`
- Modify if required: `v24/scripts/update_v24_manifest.py`
- Create: fresh v24 demo output under `results/`

- [ ] **Step 1: Refresh and verify the v24 source manifest**

Run only the v24 manifest updater, inspect the diff, and verify no frozen runtime changed.

- [ ] **Step 2: Run v24 focused and complete tests**

Run: `cd v24 && uv run --frozen python -m unittest discover -v`

Run: `./go_v0.24.0.sh --output results/v24-visible-sky-mask-check`

Expected: PASS with new mask artifacts and no relaxed thresholds.

- [ ] **Step 3: Run repository-required verification**

Run: `uv run --frozen python -m unittest discover -v`

Run: `./demo.sh --output results/check-unique-name`

Expected: PASS.

- [ ] **Step 4: Check every preserved runtime boundary**

Run the repository's complete preserved-version hash/boundary suite, including the new v23 boundary record. Any mismatch is a release blocker.

- [ ] **Step 5: Request code review and address evidence-backed findings**

Use `superpowers:requesting-code-review`. Re-run the affected focused tests after each correction.

- [ ] **Step 6: Verify the final diff and branch state**

Confirm no user-owned deletion, symlink, generated output, or historical reference product is staged. Confirm all production mask artifacts match their recorded checksums.

- [ ] **Step 7: Finish and publish**

Use `superpowers:finishing-a-development-branch`, integrate the reviewed commits onto `main`, then push `main` to `origin` as explicitly requested.

- [ ] **Step 8: Report concrete inspection targets**

Lead with the final mask overlay and calibration review images, then the approved binary mask, manifest, and one representative v24 run report.
