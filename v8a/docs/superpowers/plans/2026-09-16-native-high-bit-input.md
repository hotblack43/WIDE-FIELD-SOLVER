# Native High-Bit Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v6 ingest and analyse native-depth PNG, TIFF and two-/three-/four-plane FITS without scientific 8-bit conversion, while preserving existing 8-bit results.

**Architecture:** A single `ScientificImage` loader owns decoding, channel semantics, invalid pixels, saturation and provenance. Existing v6 stages re-read the immutable source through that loader and use native floating-point working arrays; only plotting receives a derived 8-bit display array.

**Tech Stack:** Python 3.12, NumPy, Pillow, PyPNG, tifffile, Astropy FITS, unittest

**Spec:** `v6/docs/superpowers/specs/2026-09-16-native-high-bit-input.md`

## Global Constraints

- Modify only v6 runtime, v6 dependencies, v6 tests, v6 documentation, and the root deferred-note document.
- Do not change `go.sh`, any `go4*`/`go5*` launcher, or any file under `v4/` or `v5/`.
- RAW files and Bayer mosaics are out of scope; already separated sensor planes are in scope.
- Scientific arrays must never be quantised to eight bits; only display arrays may be stretched to `uint8`.
- Three-plane defaults are `R,G,B`; four-plane defaults are `R,G1,G2,B`, with floating `G=(G1+G2)/2`.
- Existing 8-bit rendered inputs retain the v6 `>=250` saturation rule.
- Existing input commands remain valid without new arguments.
- No metadata, cached solution or stored identity may enter the blind fit.
- Do not relax any regression threshold.

---

### Task 1: Native image data model and raster decoders

**Files:**
- Create: `v6/point_star_image.py`
- Create: `v6/test_point_star_image.py`
- Modify: `v6/pyproject.toml`
- Modify: `v6/uv.lock`

**Interfaces:**
- Produces: `load_scientific_image(path, *, fits_hdu=None, channel_order=None, saturation_level=None) -> ScientificImage`
- Produces: `ScientificImage.planes: dict[str, np.ndarray]`, `.rgb`, `.luminance`, `.valid_mask`, `.saturated_mask`, `.display_rgb`, and `.provenance()`.
- Produces: `ImageLoadPolicy` serialisation for exact re-loading by later stages.

- [ ] **Step 1: Write failing raster-depth tests**

Create synthetic 8-bit RGB, 16-bit grayscale PNG, 16-bit RGB PNG and uint16 TIFF fixtures. Assert that samples `256`, `4095`, `16383` and `65535` survive decoding, that plane names are stable, and that `display_rgb.dtype == np.uint8` while scientific planes retain their values.

```python
image = load_scientific_image(path)
self.assertEqual(image.planes['G'][0, 2], 4095)
self.assertEqual(image.display_rgb.dtype, np.uint8)
self.assertGreater(image.luminance[0, 2], 255)
```

- [ ] **Step 2: Run the focused tests and confirm the missing-module failure**

Run: `uv run --directory v6 --frozen python -m unittest -v test_point_star_image`

Expected: FAIL because `point_star_image` does not exist.

- [ ] **Step 3: Add pinned decoder dependencies**

Add `pypng` and `tifffile` to `v6/pyproject.toml`, then run `uv lock --directory v6` and retain the regenerated `v6/uv.lock`.

- [ ] **Step 4: Implement immutable native raster loading**

Implement a frozen `ScientificImage` dataclass. Use Pillow unchanged for existing 8-bit JPEG/PNG inputs, PyPNG for PNG bit depths above eight, and tifffile for TIFF. Reject palette/alpha input with an explicit policy error. Convert decoded arrays to floating working arrays only after retaining native plane arrays. Build luminance with `[0.2126, 0.7152, 0.0722]`; monochrome uses its native plane.

```python
@dataclass(frozen=True)
class ScientificImage:
    path: Path
    planes: Mapping[str, np.ndarray]
    rgb: np.ndarray | None
    luminance: np.ndarray
    valid_mask: np.ndarray
    saturated_mask: np.ndarray
    display_rgb: np.ndarray
    metadata: Mapping[str, object]
```

- [ ] **Step 5: Implement display-only percentile stretching**

For high-bit/float data, derive finite-pixel per-channel 0.5/99.5-percentile stretches. For existing uint8 RGB inputs return the decoded RGB samples unchanged. Tests must mutate/copy the display array and demonstrate that native planes and luminance do not change.

- [ ] **Step 6: Run raster loader tests**

Run: `uv run --directory v6 --frozen python -m unittest -v test_point_star_image`

Expected: PASS for all raster and display-isolation cases.

### Task 2: FITS stacks, invalid pixels and saturation policy

**Files:**
- Modify: `v6/point_star_image.py`
- Modify: `v6/test_point_star_image.py`

**Interfaces:**
- Extends: `load_scientific_image` with FITS HDU selection and cube interpretation.
- Produces: per-plane `SaturationDefinition(level, source, confidence, known)` records.
- Produces: derived G while retaining G1/G2 for four-plane stacks.

- [ ] **Step 1: Write failing FITS layout tests**

Generate 2-D FITS, `(3,H,W)`, `(H,W,3)`, `(4,H,W)`, `(H,W,4)`, named RGB extensions, and ambiguous multi-HDU files. Assert default RGB/RG1G2B naming, exact native plane values, `G == (G1+G2)/2`, explicit HDU selection, and a descriptive ambiguity exception containing candidate HDU names.

- [ ] **Step 2: Write failing invalid-pixel and scaling tests**

Create scaled integer FITS using `BSCALE/BZERO` and float FITS containing NaN/Inf. Assert decoded physical values, recorded header scaling, and a false `valid_mask` wherever any science plane is nonfinite.

- [ ] **Step 3: Write failing saturation-hierarchy tests**

Cover explicit thresholds, FITS `SATURATE`, exact 4095/16383 clipping ceilings in uint16 containers, datatype fallback, existing uint8 threshold 250, and unknown float saturation. Assert both combined and per-plane masks and all provenance labels.

- [ ] **Step 4: Implement FITS selection and channel mapping**

Select a sole supported image HDU automatically. Accept one spatial axis pair plus a unique 3/4 channel axis, and named plane extensions. Apply `--channel-order` only after validating it contains exactly `RGB` or `RG1G2B` semantics. Raise `ImageLayoutError` for remaining ambiguity.

- [ ] **Step 5: Implement saturation resolution**

Resolve the explicit option first, trusted FITS keywords second, an observed exact standard ceiling third, and dtype ceiling last. Preserve the 250 threshold for uint8 rendered input. Float input without declared metadata remains `known=False` and has an all-false saturation mask.

- [ ] **Step 6: Run all loader tests**

Run: `uv run --directory v6 --frozen python -m unittest -v test_point_star_image`

Expected: PASS, including both stack orientations and four native planes.

### Task 3: Detection integration, provenance and command line

**Files:**
- Modify: `v6/point_star_detection.py`
- Modify: `v6/point_star_barghini.py`
- Modify: `v6/analyse_image.py`
- Modify: `v6/test_point_star_detection.py`
- Create: `v6/test_high_bit_cli.py`

**Interfaces:**
- Changes: `detect_stars(image, ..., valid_mask=None, saturated_mask=None, saturation_known=True)` consumes native luminance/RGB rather than selecting threshold 250 internally.
- Changes: `write_products(..., image_options=None)` writes `dots/input_image.json` before scientific products.
- Adds CLI: `--fits-hdu`, `--channel-order`, `--saturation-level`.

- [ ] **Step 1: Write failing equivalent-bit-depth detection tests**

Encode one synthetic star field at gains 1, 16, 64 and 257 in uint8/uint16 containers. Assert the same candidate count and centroid agreement better than 0.02 pixels, while flux and noise scale with gain. Add a clipped 12-bit star and assert saturation is retained without excluding its centroid.

- [ ] **Step 2: Write failing CLI/provenance tests**

Parse each new option; run detection on a four-plane FITS fixture; assert `input_image.json` contains checksum, format, native shape/dtype, plane order, derivation, invalid count and saturation authority. Assert a bad layout fails before the output directory is created.

- [ ] **Step 3: Refactor detection around loader products**

Remove scientific `Image.open(...).convert('RGB')` and the internal fixed saturation calculation. Use loader luminance, valid mask and supplied combined saturation mask. Modify footprint calculations only as needed to ignore invalid samples without replacing them with valid black pixels.

- [ ] **Step 4: Thread image policy through the v6 entry point**

Parse the new options into a serialisable policy, pass it to `point_star_barghini.run`, and have subsequent stages validate/reuse `dots/input_image.json`. Keep all old function defaults compatible with current tests and programmatic callers.

- [ ] **Step 5: Run detection and CLI tests**

Run: `uv run --directory v6 --frozen python -m unittest -v test_point_star_detection test_high_bit_cli`

Expected: PASS with centroid invariance and complete provenance.

### Task 4: Native-depth photometry and planet evidence

**Files:**
- Modify: `v6/point_star_science.py`
- Modify: `v6/point_star_planet_nondetections.py`
- Modify: `v6/test_blind_photometry.py`
- Modify: `v6/test_planet_nondetections.py`

**Interfaces:**
- Changes: `measure_photometry` loads the recorded `ScientificImage` and measures all native planes.
- Adds CSV fields for four-plane input: `G1_flux`, `G2_flux`, `G1_mag`, `G2_mag`, per-plane saturation and usability; existing RGB fields remain.
- Changes: planet absence probes use native RGB/luminance and the shared validity mask.

- [ ] **Step 1: Write failing scaled-photometry tests**

Measure identical aperture scenes at 8/12/14/16-bit gains. Assert flux ratios equal the gains and magnitude offsets equal `-2.5*log10(gain)`, with unchanged centroids and fixed photometric membership.

- [ ] **Step 2: Write failing G1/G2 and invalid-aperture tests**

Give G1 and G2 different known source/background levels. Assert native fluxes survive, derived `G_flux` equals their mean-flux derivation, and invalid/insufficient annuli retain rows with `photometry_usable=False` plus an explicit reason.

- [ ] **Step 3: Replace 8-bit photometry conversion**

Measure apertures from loader planes as float without rescaling. Compute each native channel independently, then compute derived G from the G1/G2 samples. A combined saturated source keeps raw diagnostic fluxes but no machine magnitudes, preserving the project’s saturation contract.

- [ ] **Step 4: Replace planet-probe image conversion**

Load native arrays and validity through the same recorded policy. Ensure local source evidence treats invalid pixels as unavailable and does not infer darkness from NaN replacement.

- [ ] **Step 5: Run focused science tests**

Run: `uv run --directory v6 --frozen python -m unittest -v test_blind_photometry test_planet_nondetections`

Expected: PASS with exact gain/magnitude relationships.

### Task 5: Diagnostics, report and lossless FITS export

**Files:**
- Modify: `v6/point_star_barghini.py`
- Modify: `v6/point_star_diagnostics.py`
- Modify: `v6/point_star_science.py`
- Modify: `v6/point_star_planets.py`
- Modify: `v6/point_star_report.py`
- Modify: `v6/point_star_fits.py`
- Modify: `v6/test_point_star_fits.py`
- Modify: `v6/test_point_star_report.py`

**Interfaces:**
- Plotting consumes only `ScientificImage.display_rgb`.
- `write_fits` writes every native plane to annotated output and labels the two-dimensional compatible primary as derived when applicable.
- PDF and summary expose native bit depth, channel mapping and saturation certainty.

- [ ] **Step 1: Write failing FITS round-trip tests**

Export uint16 RGB and RG1G2B input. Reopen annotated FITS and assert exact equality for every native plane, WCS equality across plane extensions, provenance presence, and a two-dimensional plain primary. Assert the compatible primary is floating-point luminance when integer rounding would lose dynamic information.

- [ ] **Step 2: Write failing high-bit report tests**

Build a minimal high-bit analysis and assert report generation succeeds, the input provenance text names the stored dtype/planes, and a stretched-display notice appears. Existing uint8 report snapshots must still load without the notice.

- [ ] **Step 3: Remove remaining scientific/display source decoding**

Replace source-image `Image.open`, `mpimg.imread` and equivalent reads in v6 runtime with loader scientific arrays or display arrays according to purpose. Keep Pillow reads used solely to verify generated PNG products in tests.

- [ ] **Step 4: Generalise FITS export**

Write named extensions for all native planes and include serialised input provenance in `WFSINFO`. Generate the plain two-dimensional luminance from float working values without clipping to source integer range. Retain atomic publication and checksum checks.

- [ ] **Step 5: Run export/report tests and scan for regressions**

Run: `uv run --directory v6 --frozen python -m unittest -v test_point_star_fits test_point_star_fits_ds9 test_point_star_report test_point_star_diagnostics`

Run: `rg -n "Image\.open\(image_path\).*convert\('RGB'\)|mpimg\.imread\(image_path\)" v6 --glob '*.py'`

Expected: tests PASS; scan finds no v6 scientific source conversion.

### Task 6: Documentation, manifests and compatibility verification

**Files:**
- Modify: `v6/docs/FEATURE_STATUS.md`
- Modify: `v6/docs/METHOD.md`
- Modify: `v6/SOURCE_MANIFEST.json`
- Modify: `docs/FOR_LATER.md`
- Test: existing root and v6 test suites

**Interfaces:**
- Documents native-depth support as implemented evidence, not a proposal.
- Updates only the v6 source manifest entries affected by this feature.

- [ ] **Step 1: Run the complete v6 unit suite**

Run: `uv run --directory v6 --frozen python -m unittest discover -v`

Expected: PASS with no skipped high-bit tests other than existing external-tool skips.

- [ ] **Step 2: Run the repository-required suite**

Run: `uv run --frozen python -m unittest discover -v`

Expected: PASS.

- [ ] **Step 3: Run the required demo and v6 smoke solve**

Run: `./demo.sh --output results/check-unique-name`

Run v6 on the historical example into a fresh uniquely named results directory and run `v6/scripts/check_demo.py` against it.

Expected: both commands PASS without changing fixed regression thresholds.

- [ ] **Step 4: Verify preserved-version boundaries**

Run the repository’s legacy/v4/v5/v6 manifest or launcher checks, then use `git diff --name-only` to confirm no preserved runtime file changed. Run `go.sh --version`, `go4.sh --version`, `go5.sh --version` and `go6.sh --version` if supported by their existing interfaces.

- [ ] **Step 5: Update status and deferred note**

Document native input, saturation provenance and remaining RAW/Bayer limitation in `FEATURE_STATUS.md` and `METHOD.md`. Mark only the high-bit/FITS portion of `docs/FOR_LATER.md` implemented; retain the SQLite index as deferred.

- [ ] **Step 6: Regenerate and verify the v6 source manifest**

Use the repository’s manifest update procedure, then run its verification test. Confirm `uv.lock` remains committed and frozen installation succeeds.

- [ ] **Step 7: Review and commit only feature files**

Inspect `git status --short` and `git diff --check`; stage only this plan/spec, v6 implementation/tests/dependencies/docs, and the deferred-note update. Do not stage the user’s `.gitignore`, fetch script or fetch-script test. Commit on current `main`; do not create or push a branch and do not push to GitHub unless separately requested.
