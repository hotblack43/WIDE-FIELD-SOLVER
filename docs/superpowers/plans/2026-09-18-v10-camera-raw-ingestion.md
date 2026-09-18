# V10 Camera-RAW Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every v9 capability in a new v0.10.0 runtime while adding direct scientific CR2 ingestion, trustworthy RAW/FITS calibration provenance, and image-masked WCS export for bounded fisheye sky domains.

**Architecture:** Copy the investigator's current working v9 package into an independent `v10/` package without modifying v9, then add a local LibRaw adapter consumed by the existing `ScientificImage` boundary. Reuse the saved image-only footprint to constrain ZPN validation and publish an explicit sky mask while keeping native planes and fitted coordinates unchanged.

**Tech Stack:** Python 3.12, NumPy, rawpy/LibRaw, exifread, Astropy FITS/WCS, Pillow for ordinary rendered formats only, unittest, uv.

**Spec:** `docs/superpowers/specs/2026-09-18-v10-camera-raw-ingestion-design.md`

## Global Constraints

- Root legacy, `v4/`, `v5/`, `v6/`, `v7/`, `v8/`, `v8a/`, and the complete `v9/` package remain unchanged.
- V10 starts from the current working v9 content requested by the investigator, including the 2026-09-18 single-planet report changes.
- V10 runtime code and dependencies are local to this repository; never import the Earthshine or trail-processing projects.
- CR2 science pixels must come from `rawpy.raw_image_visible`; Pillow is forbidden for CR2.
- Preserve native Bayer ADU, measured centroids, fitted coordinates, and overlays. No demosaicing, resampling, cosmetic shifts, or catalogue-derived mask is allowed.
- Observation time remains post-fit metadata and never seeds blind astrometry, refraction, or photometric zenith.
- The ZPN export error limit remains exactly 0.05 pixel and may not be relaxed.
- `uv.lock` remains committed in v10.
- Before every commit run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output results/check-unique-name` from the repository root with a new unused output path.

---

### Task 1: Create the additive v10 boundary without changing v9

**Files:**
- Create: `v10/**`, excluding `.venv`, `__pycache__`, and generated outputs
- Create: `go10.sh`, `go_v0.10.0.sh`, `test_v10_launchers.py`, `docs/v9-runtime.json`
- Modify: `test_preserved_versions.py`, `AGENTS.md`

**Interfaces:**
- Consumes: current working `/home/pth/WORKSHOP/WIDE-FIELD-SOLVER/v9/`.
- Produces: independent v0.10.0 runtime and an immutable committed-v9 checksum boundary.

- [ ] **Step 1: Copy the complete working v9 package into v10**

```sh
rsync -a --exclude='.venv/' --exclude='__pycache__/' --exclude='*.pyc' \
  /home/pth/WORKSHOP/WIDE-FIELD-SOLVER/v9/ v10/
```

Verify the investigator-edited source files match their v10 copies byte-for-byte and `git status --short -- v9` remains empty in the implementation worktree.

- [ ] **Step 2: Write failing launcher and preservation tests**

Copy `test_v9_launchers.py` to `test_v10_launchers.py` and parameterize it with:

```python
LAUNCHERS = ('go10.sh', 'go_v0.10.0.sh')
VERSION = '0.10.0'
PACKAGE = 'v10'
```

Extend `test_preserved_versions.py` to require `docs/v9-runtime.json` and verify each v9/launcher checksum. Defer the complete v10 manifest inventory check until Task 5, after all v10 files exist. Run the two modules and observe failure because the boundary does not yet exist.

- [ ] **Step 3: Add v10 launchers and version declarations**

Route both launchers to `v10/run.sh`. Change only v10 package/CLI/README/AGENTS version references from `0.9.0` to `0.10.0`; add `cr2` to the usage text. Do not change scientific constants or behavior.

- [ ] **Step 4: Generate and verify `docs/v9-runtime.json`**

Record the exact full parent commit, version `0.9.0`, and SHA-256 for `go9.sh`, `go_v0.9.0.sh`, `v9/SOURCE_MANIFEST.json`, and every file named by that manifest. Update root `AGENTS.md` so upgrades belong in v10. Run:

```sh
uv run --frozen python -m unittest -v test_v10_launchers test_preserved_versions
git diff --exit-code -- v9 go9.sh go_v0.9.0.sh
```

- [ ] **Step 5: Run mandatory verification and commit**

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-v10-boundary
git add AGENTS.md docs/v9-runtime.json v10 go10.sh go_v0.10.0.sh test_v10_launchers.py test_preserved_versions.py
git commit -m "feat: establish preserved v10 runtime"
```

Expected demo: 3,653 associations and 0.39789212340991864 px RMS.

---

### Task 2: Decode CR2 Bayer data and calibration metadata directly

**Files:**
- Create: `v10/point_star_raw.py`, `v10/test_point_star_raw.py`
- Modify: `v10/point_star_image.py`, `v10/test_point_star_image.py`, `v10/pyproject.toml`, `v10/uv.lock`

**Interfaces:**
- Produces `decode_cr2(path: Path) -> CameraRawImage`.
- `CameraRawImage.planes`, `.black_levels`, and `.white_levels` are mappings named `R,G1,G2,B`.
- `.details` contains decoder, CFA, sensor dimensions, exposure, ISO, camera, and lens provenance, but no timestamp.
- `load_scientific_image()` retains the existing `ScientificImage` API.

- [ ] **Step 1: Pin dependencies**

Add `exifread==3.5.1` and `rawpy==0.27.1`; run `uv lock --project v10` and `uv sync --project v10 --frozen`.

- [ ] **Step 2: Write failing CFA tests**

Create a fake RawPy context with a known 4 by 6 `uint16` mosaic. Patch only `rawpy.imread`. Assert explicit expected slices for RGGB, BGGR, GRBG, and GBRG. Assert black levels follow each CFA position's LibRaw colour index, catching the historical G2/B ordering mistake. Run the test and require failure because `point_star_raw` is absent.

- [ ] **Step 3: Implement the minimal adapter**

```python
@dataclass(frozen=True)
class CameraRawImage:
    planes: Mapping[str, np.ndarray]
    black_levels: Mapping[str, float]
    white_levels: Mapping[str, float]
    details: Mapping[str, object]

def decode_cr2(path: Path) -> CameraRawImage:
    ...
```

Use only `raw_image_visible.copy()`. Derive CFA letters from `color_desc[raw_pattern]`; assign row-major green positions to G1 and G2. Reject absent, non-2-D, odd, non-2-by-2, non-Bayer, non-integer, or unequal-plane data explicitly.

- [ ] **Step 4: Verify CFA tests pass**

Run `uv run --project v10 --frozen python -m unittest -v test_point_star_raw`.

- [ ] **Step 5: Write failing loader and FITS-calibration tests**

Patch `point_star_raw.decode_cr2` to return known planes and patch `PIL.Image.open` to fail if called. Assert decoder `rawpy/libraw`, `R,G1,G2,B`, 14 effective bits, and `black_level.status == 'available_not_subtracted'`. Add FITS fixtures containing `BLACK_R/G1/G2/B` and `WHITELEV=16383`; require those exact sources instead of observed-ceiling guesses.

- [ ] **Step 6: Route CR2 before Pillow and ingest calibration levels**

Dispatch `.cr2` before `_read_raster`, use layout `bayer_cell_planes`, and make `_read_fits` return per-plane black/white levels. Saturation priority is explicit CLI, trustworthy RAW/FITS white level, then current fallbacks. Record original ADU as preserved and black levels as available but not globally subtracted.

- [ ] **Step 7: Verify and commit**

Run focused v10 tests, the full v10 suite, mandatory root suite, and root demo; then commit `feat(v10): ingest native CR2 Bayer data`.

---

### Task 3: Resolve CR2 time only after blind fitting

**Files:**
- Modify: `v10/point_star_raw.py`, `v10/point_star_metadata.py`, `v10/test_point_star_raw.py`, `v10/test_point_star_metadata.py`

**Interfaces:**
- Produces `read_cr2_exif(path: Path, fields: Collection[str]) -> dict[str, object]`, returning only requested normalized values.
- `resolve_observation_time()` retains its existing schema and priorities.

- [ ] **Step 1: Write failing metadata-boundary tests**

Patch representative Canon EXIF tags. Require the pre-fit measurement request to return exposure/ISO/camera/lens only, never time. Require post-fit `resolve_observation_time()` to parse `2025:06:25 04:06:01` as `2025-06-25T04:06:01.000 UTC`, source `cr2_exif:DateTimeOriginal`, `assumed_utc=True`.

- [ ] **Step 2: Implement selected-field EXIF reading**

Use `exifread.process_file(..., details=False, strict=False)` and normalize only requested fields. Add `_camera_raw_candidates()` to `point_star_metadata.py`; call it only from the existing post-fit resolver. Never put observation time in `ScientificImage.provenance()`.

- [ ] **Step 3: Verify and commit**

Run `test_point_star_raw`, `test_point_star_metadata`, `test_epoch_integration`, the mandatory root suite and demo; commit `feat(v10): defer CR2 time metadata until post-fit analysis`.

---

### Task 4: Export WCS over the measured sky footprint

**Files:**
- Modify: `v10/point_star_fits.py`, `v10/test_point_star_fits.py`, `v10/test_point_star_fits_ds9.py`

**Interfaces:**
- Extends `validated_header(camera, valid_mask=None)`.
- Produces restricted-domain validation audit, annotated `SKYMASK`, and masked plain primary pixels.

- [ ] **Step 1: Write failing restricted-domain tests**

Construct a camera whose corners exceed 180 degrees but whose circular valid mask stays finite, monotonic, and below 180. Require `domain == 'saved image-derived sky footprint'`, maximum error below 0.05 px, and excluded pixels above zero. Retain refusal without a mask and add refusal when the mask itself reaches the invalid radius.

- [ ] **Step 2: Implement deterministic mask validation**

Validate the full radial interval from zero through the maximum valid-pixel radius. Sample deterministic valid grid points and an evenly subsampled morphological boundary, plus origin and zenith. Retain polynomial orders and `LIMIT_PX=.05`. Record mask area, excluded count, maximum radius/angle, and sample counts.

- [ ] **Step 3: Write failing publication tests**

Require `solution.fits` to contain exact derived luminance inside the mask and NaN outside. Require `solution_annotated.fits['SKYMASK']` to equal the saved uint8 mask, native colour HDUs to round-trip unchanged, WCS headers to agree, mask provenance in WFSINFO/audit, and overlay coordinates to remain unchanged.

- [ ] **Step 4: Publish mask without altering native planes**

Load and shape-check `dots/sky_footprint.npz`. Pass it to `validated_header`; add `WFSVALID='SKYMASK'`; mask only the plain derived image; append a WCS-bearing `SKYMASK` HDU to the annotated product. Preserve every native plane value.

- [ ] **Step 5: Verify and commit**

Run FITS, DS9, and footprint tests, full v10 tests, mandatory root suite and demo; commit `feat(v10): mask non-sky FITS export domain`.

---

### Task 5: Document, freeze, and validate end to end

**Files:**
- Modify: `v10/README.md`, `v10/docs/FEATURE_STATUS.md`, `v10/docs/FITS_EXPORT.md`, `v10/docs/METHOD.md`, `README.md`, `v10/SOURCE_MANIFEST.json`, `test_preserved_versions.py`

**Interfaces:**
- Produces documented `./go10.sh image.cr2` and complete v10 provenance.
- Uses the public Rubin sample for one acceptance run; it is not copied into v10.

- [ ] **Step 1: Document implemented behavior**

Document direct CR2, four Bayer-cell planes, half-resolution coordinates, calibration provenance, post-fit timestamp use, masked WCS, and explicit failure rules. State that v9 and every earlier launcher remain unchanged.

- [ ] **Step 2: Run v10 suite and demo**

```sh
uv run --project v10 --frozen python -m unittest discover -v -s v10
./v10/demo.sh --output results/check-v10-final
```

Require inherited demo associations/residuals to match v9 exactly.

- [ ] **Step 3: Run the Rubin CR2 exactly once**

Run `go10.sh` on the public sample in `.worktrees/raw-allsky-acquisition/raw_allsky_samples/rubin/asc2506240487.cr2`. Verify saved products show rawpy, four `uint16` planes, 14 bits, original SHA-256 `ab36ba13f71f19d10ca6c0b4597abd6efbfc46f8dd77802be9bb17711eceed2d`, 30 seconds, close agreement with the 1,507-source converted-FITS solution, successful WCS export below 0.05 px, NaN non-sky plain pixels, and unchanged annotated native planes. Do not rerun unless retained evidence exposes a specific defect.

- [ ] **Step 4: Regenerate and test the v10 manifest**

Hash every tracked v10 runtime/test/doc/data/lock file except the manifest itself, environments, caches, and outputs. Record version `0.10.0` and the v9 parent boundary. Run manifest and clean-clone tests.

- [ ] **Step 5: Final verification and commit**

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-v10-release
uv run --project v10 --frozen python -m unittest discover -v -s v10
git diff --check
git diff --exit-code -- v9 go9.sh go_v0.9.0.sh
```

Inspect the complete diff for feature deletion, commit `docs: record v10 native camera RAW support`, then use the requesting-code-review procedure and report branch, commits, tests, Rubin output, limitations, and v9 preservation evidence.
