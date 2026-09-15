# Sky Footprint Mask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v5 solve only the photographed sky footprint, excluding a dark frame and graphics on that frame before catalogue association.

**Architecture:** A focused `point_star_footprint.py` module infers a conservative Boolean footprint from finite image luminance using large-scale smoothing and connected components. The established detector still measures the original pixels, then filters centroids through that mask; saved mask evidence is reused by planet non-detection checks. Ambiguous images fall back to the whole detector.

**Tech Stack:** Python 3.12, NumPy 2.4.4, SciPy 1.17.1, Pillow 12.2.0, Matplotlib 3.11.1, unittest.

**Spec:** `docs/superpowers/specs/2026-09-15-sky-footprint-mask.md`

## Global Constraints

- Modify only v5 runtime behavior; preserve `go.sh`, `go4.sh`, `go_v0.4.3.sh`, root runtime, and `v4/` byte-for-byte.
- Use no OCR, EXIF, filename, observing metadata, catalogue coordinates, saved identities, or fitted zenith to construct the mask.
- Do not use NaN pixels as a mask and do not alter the original image or FITS pixel arrays.
- Retain every compact, broad, and saturated detection inside the inferred footprint.
- Text inside the accepted sky footprint is unsupported and remains the user's responsibility.
- Add no dependency and keep `v5/uv.lock` committed.
- Do not relax any existing regression threshold.

---

### Task 1: Infer a conservative sky footprint

**Files:**
- Create: `v5/point_star_footprint.py`
- Create: `v5/test_point_star_footprint.py`

**Interfaces:**
- Consumes: finite greyscale or RGB `numpy.ndarray` image pixels.
- Produces: `infer_sky_footprint(image) -> tuple[numpy.ndarray, dict]`, where the array is a two-dimensional Boolean valid mask and the dictionary contains `status`, `method`, `valid_pixel_fraction`, `threshold_adu`, `inside_median_adu`, `outside_median_adu`, and `reason`.

- [x] **Step 1: Write failing footprint tests**

```python
def test_round_field_excludes_black_frame_and_disconnected_frame_marks(self):
    image = framed_field(shape=(240, 300), centre=(142, 116), radii=(112, 96))
    image[222:228, 30:120] = 220
    mask, audit = infer_sky_footprint(image)
    self.assertEqual(audit['status'], 'framed_footprint')
    self.assertTrue(mask[116, 142])
    self.assertFalse(mask[225, 60])
    self.assertGreater(mask.mean(), .35)
    self.assertLess(mask.mean(), .65)

def test_dark_full_frame_image_falls_back_to_all_pixels(self):
    image = full_frame_star_field(shape=(180, 220))
    mask, audit = infer_sky_footprint(image)
    self.assertEqual(audit['status'], 'full_image')
    self.assertTrue(mask.all())

def test_off_centre_cropped_field_does_not_require_image_centre(self):
    image = framed_field(shape=(220, 260), centre=(82, 112), radii=(105, 94))
    mask, audit = infer_sky_footprint(image)
    self.assertEqual(audit['status'], 'framed_footprint')
    self.assertTrue(mask[112, 82])
    self.assertFalse(mask[15, 240])
```

- [x] **Step 2: Run the focused tests and verify RED**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_point_star_footprint.py`

Expected: FAIL because `point_star_footprint` does not exist.

- [x] **Step 3: Implement footprint inference**

Implement luminance conversion, scale-aware Gaussian smoothing, low-end candidate thresholds, connected-component selection, closing, hole filling, and conservative confidence checks. Select the largest coherent illuminated component without requiring it to contain the geometric centre. Return an all-true mask when exterior contrast, component area, or coherence is insufficient.

The implementation must expose only:

```python
def infer_sky_footprint(image):
    """Return `(valid_mask, audit)` inferred only from image pixels."""
```

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_point_star_footprint.py`

Expected: all footprint tests PASS without warnings.

- [x] **Step 5: Check the footprint component**

```bash
git diff --check -- v5/point_star_footprint.py v5/test_point_star_footprint.py
```

Do not commit yet: the v5 source manifest must be updated before the root
preservation suite can pass.

### Task 2: Filter detections and save auditable mask products

**Files:**
- Modify: `v5/point_star_detection.py`
- Modify: `v5/test_point_star_detection.py`
- Modify: `v5/test_epoch_integration.py`

**Interfaces:**
- Consumes: `infer_sky_footprint(image)` from Task 1.
- Produces: filtered `star_candidates.csv`; `rejected_candidates.csv` rows with `outside_sky_footprint`; `dots/sky_footprint.npz` containing `valid_mask`; `dots/sky_footprint.png`; footprint fields in `dots/detection.json`.

- [x] **Step 1: Write failing detection integration tests**

Add tests that create a finite circular field with a compact star, a broad saturated star inside, and point-like frame marks outside. Assert that both inside sources survive, outside sources appear only in rejected audit rows, final detection IDs are consecutive, and `write_products` saves a Boolean mask whose summary counts match the CSV files.

The production change that must make these tests pass is post-measurement centroid filtering by the inferred mask; changing morphology thresholds must not make them pass.

- [x] **Step 2: Run the focused tests and verify RED**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_point_star_detection.py v5/test_epoch_integration.py`

Expected: FAIL because frame candidates remain and footprint products are absent.

- [x] **Step 3: Integrate filtering without changing centroid measurement**

Extend the detector interface to:

```python
def detect_stars(image, detection_sigma=6., background_sigma=10., *, valid_mask=None):
    """Measure finite pixels, then reject centroids outside `valid_mask`."""
```

When `valid_mask` is omitted, infer it from the image. Validate supplied mask shape and Boolean conversion. Preserve the existing pixel calculations through duplicate removal, append outside candidates to `audit['rejected']`, and assign detection IDs only after filtering. Include `valid_mask` and `footprint` in the audit dictionary.

In `write_products`, save the compressed Boolean mask, render an alpha overlay/boundary without altering the source pixels, add footprint counts and limitations to JSON, and plot the same boundary in `dots_overlay.png`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_point_star_footprint.py v5/test_point_star_detection.py v5/test_epoch_integration.py`

Expected: all selected tests PASS; existing centroid and broad/saturated assertions remain unchanged.

- [x] **Step 5: Check detection integration**

```bash
git diff --check -- v5/point_star_detection.py v5/test_point_star_detection.py v5/test_epoch_integration.py
```

### Task 3: Propagate the footprint to planet absence evidence

**Files:**
- Modify: `v5/point_star_planets.py`
- Modify: `v5/test_planet_nondetections.py`

**Interfaces:**
- Consumes: `dots/sky_footprint.npz` key `valid_mask`.
- Produces: the existing `check_candidate_absences(..., valid_mask=mask)` behavior, causing outside-footprint predictions to remain inconclusive rather than count as absent planets.

- [x] **Step 1: Write a failing integration test**

Create a temporary solution containing `sky_footprint.npz`, arrange a predicted bright planet outside the valid mask, run the real planet-evidence handoff, and assert that its evidence status is `inconclusive_mask_or_edge` and never `missing_bright_planet`.

- [x] **Step 2: Run the test and verify RED**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_planet_nondetections.py`

Expected: FAIL because `fit_blind_planet_epoch` does not load or pass the saved mask.

- [x] **Step 3: Load and pass the saved Boolean mask**

Add a small private loader that validates the stored mask against the original image shape through `LocalDetectability`. Missing legacy mask files pass `None` and retain current behavior. Pass the loaded array to `check_candidate_absences` without changing candidate positions or ranking.

- [x] **Step 4: Run planet tests and verify GREEN**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_planet_nondetections.py v5/test_point_star_planets.py`

Expected: all selected tests PASS.

- [x] **Step 5: Check planet-mask propagation**

```bash
git diff --check -- v5/point_star_planets.py v5/test_planet_nondetections.py
```

### Task 4: Let FITS validation continue after a non-finite trial WCS

**Files:**
- Modify: `v5/point_star_fits.py`
- Modify: `v5/test_point_star_fits.py`

**Interfaces:**
- Consumes: each candidate ZPN WCS generated by `validated_header(camera)`.
- Produces: a rejected attempt record for non-finite candidate transforms and continued validation of higher orders.

- [x] **Step 1: Write the failing Espenak-camera regression**

Build the camera from the saved numerical parameters recorded by the failing run, call `validated_header`, and assert that order 13 succeeds below `LIMIT_PX` while the order-7 attempt has `maximum_error_px is None`.

- [x] **Step 2: Run the FITS test and verify RED**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_point_star_fits.py`

Expected: FAIL with `The function value at x=0.0 is NaN`.

- [x] **Step 3: Reject non-finite trial transforms before Barghini inversion**

After `all_pix2world`, check whether `world` is finite. If not, append the order attempt with `maximum_error_px: None` and a factual reason, then continue. Apply the same guard to inverse-WCS results before composing numerical errors. Do not change camera parameters, ZPN coefficients, or the 0.05-pixel acceptance threshold.

- [x] **Step 4: Run FITS tests and verify GREEN**

Run: `uv run --project v5 --frozen python -m unittest -v v5/test_point_star_fits.py v5/test_point_star_fits_ds9.py`

Expected: all selected tests PASS and the regression validates order 13 near 0.0129 pixels.

- [x] **Step 5: Check the FITS control-flow repair**

```bash
git diff --check -- v5/point_star_fits.py v5/test_point_star_fits.py
```

### Task 5: Document, manifest, and verify the complete v5 behavior

**Files:**
- Modify: `v5/docs/FEATURE_STATUS.md`
- Modify: `v5/docs/METHOD.md`
- Modify: `v5/SOURCE_MANIFEST.json`
- Test: all root and v5 test modules

**Interfaces:**
- Consumes: all implementation files from Tasks 1–4.
- Produces: factual status documentation, a complete v5 source manifest, preserved runtimes, and a fresh runnable Espenak result.

- [x] **Step 1: Update factual documentation**

Document the footprint as image-domain support rather than source withholding, the no-OCR limitation, whole-image fallback, saved evidence, and planet-mask semantics. Document the FITS control-flow repair separately from numerical astrometry.

- [x] **Step 2: Update the v5 manifest deliberately**

Run the repository's existing manifest update/check mechanism, including the new runtime, tests, documentation, and changed hashes. Do not modify recorded v4 or legacy hashes.

- [x] **Step 3: Run the complete v5 suite**

Run: `uv run --project v5 --frozen python -m unittest discover -v -s v5`

Expected: all v5 tests PASS.

- [x] **Step 4: Run the required preserved unit suite**

Run: `uv run --frozen python -m unittest discover -v`

Expected: all root tests PASS, including runtime hash preservation and the updated v5 manifest.

- [x] **Step 5: Run the required historical demo**

Run: `./demo.sh --output results/check-unique-name`

Expected: PASS without relaxed thresholds; 3,653 associations and RMS no worse than the preserved bound.

- [x] **Step 6: Run the Espenak image through the public launcher**

Run: `./go5.sh /home/pth/Skrivebord/StarTrails/FishEye18-1032w_Espenak.jpg`

Expected: the new run saves `dots/sky_footprint.npz` and `.png`; detections along the bottom frame near `y = 910` are audited outside the footprint and absent from `star_coordinates.csv`; a `solution.fits` is exported through the separately repaired validator.

- [x] **Step 7: Inspect scientific regression evidence**

Check the saved mask against the original, verify the circular stellar field is retained, count outside-footprint rejections, confirm zero associated detections in the bottom frame, and compare in-footprint association/RMS values against the original run without weakening acceptance criteria.

- [x] **Step 8: Commit the verified implementation, documentation, plan, and manifest**

```bash
git add docs/superpowers/plans/2026-09-15-sky-footprint-mask.md v5/point_star_footprint.py v5/point_star_barghini.py v5/point_star_detection.py v5/point_star_planets.py v5/point_star_fits.py v5/test_point_star_footprint.py v5/test_point_star_detection.py v5/test_epoch_integration.py v5/test_planet_nondetections.py v5/test_point_star_fits.py v5/docs/FEATURE_STATUS.md v5/docs/METHOD.md v5/SOURCE_MANIFEST.json
git commit -m "feat(v5): restrict solving to the sky footprint"
```
