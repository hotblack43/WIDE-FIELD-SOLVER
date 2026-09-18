# V10 Camera-RAW Ingestion and Sky-Domain FITS Export Design

**Date:** 2026-09-18

**Status:** Approved for implementation planning

## Purpose

Create a new, self-contained v0.10.0 runtime from v9 that can ingest a Canon
CR2 file as genuine camera-RAW data. V10 must never let Pillow silently select
the CR2's embedded 8-bit JPEG. It must preserve the working blind point-star
solver, native Bayer measurements, historical runtimes, and the separation
between blind fitting and later observation-time use.

V10 also corrects two issues demonstrated by the Rubin all-sky sample:

1. trustworthy black and white levels in RAW/FITS inputs must be recorded and
   used to define calibration and saturation provenance; and
2. a fitted all-sky solution must be exportable when the image itself
   establishes a bounded sky footprint, even if meaningless non-sky corners
   make the Barghini radial model non-invertible over the entire rectangular
   detector.

The public Rubin sample `asc2506240487.cr2` is the end-to-end validation case.
Its separately verified sensor data are a 6744 by 4502 `uint16` RGGB mosaic
from a Canon EOS 5D Mark IV, with black levels near 2050, a white level of
16383, and a 30-second exposure. The existing ISS/Moon Earthshine conversion
pipeline proved the intended scientific representation: four half-resolution
planes ordered `R,G1,G2,B`, without demosaicing or rescaling.

## Version Boundary

V9 remains unchanged in the implementation branch. Root `go9.sh`,
`go_v0.9.0.sh`, and the complete `v9/` package continue to launch and describe
v0.9.0. A new `docs/v9-runtime.json` records the committed v9 boundary.

V10 starts from the current working v9 content requested by the investigator,
including the uncommitted single-planet report improvements present on
2026-09-18. Those files are copied into `v10/`; they are not staged, rewritten,
or committed under `v9/`. Generated environments, caches, reports, and run
products are excluded from the copy.

V10 owns:

- `v10/`, including code, catalogue data, ephemeris data, documentation,
  dependency lockfile, tests, and source manifest;
- root launchers `go10.sh` and `go_v0.10.0.sh`; and
- root preservation tests and documentation needed to identify the new
  boundary.

The v10 package version, CLI version, launchers, README, feature-status file,
and source manifest all identify v0.10.0. V10 must run from a clean clone with
no dependency on `.worktrees`, the Earthshine repository, or any other project.

## Chosen Ingestion Architecture

V10 decodes CR2 directly in the scientific image loader with pinned `rawpy`
(LibRaw). It does not invoke the Earthshine program at runtime and does not
write a temporary TIFF or FITS file. The established Earthshine logic is a
scientific reference whose small, necessary rules are implemented locally in
v10.

For a `.cr2` input, the loader:

1. calls `rawpy.imread` and selects `raw_image_visible`;
2. requires a two-dimensional, even-sized Bayer mosaic and a supported 2 by 2
   CFA pattern (`RGGB`, `BGGR`, `GRBG`, or `GBRG`);
3. maps the four CFA positions into equally shaped, half-resolution native
   planes named `R`, `G1`, `G2`, and `B`;
4. preserves the decoded integer samples without demosaicing, white balance,
   gamma, colour-space conversion, black subtraction, or rescaling;
5. constructs derived floating RGB/luminance arrays through the existing v9
   channel combination, with `G=(G1+G2)/2`; and
6. records the original CR2 checksum, decoder, visible/raw dimensions, CFA
   pattern, plane mapping, native dtype, black levels, white level, and load
   policy.

No exception or unsupported CR2 layout falls through to `_read_raster` or
Pillow. It fails with an explicit `ImageLayoutError`. Other camera-RAW suffixes
are outside this release's user-facing contract even when LibRaw could decode
them; the internal boundary may be extended deliberately in a later version.

The half-resolution plane coordinates represent one 2 by 2 sensor CFA cell.
They intentionally match the successful Rubin FITS solve and existing
Earthshine L1 representation. Results and reports must describe that coordinate
scale accurately rather than implying full sensor-pixel resolution.

## Calibration, Saturation, and Native Values

Native plane arrays remain unchanged so the original measurements are always
recoverable. V10 does not globally subtract black levels from these arrays.
Existing local-annulus aperture photometry removes a constant local offset
without converting the archive data into signed or clipped values.

Calibration metadata is no longer reported as unavailable when it is known:

- CR2 black levels come from `rawpy.black_level_per_channel` and are mapped to
  the named CFA planes.
- CR2 saturation uses the per-channel camera white levels when present,
  otherwise LibRaw's scalar `white_level`.
- FITS recognizes `BLACK_R`, `BLACK_G1`, `BLACK_G2`, `BLACK_B`, and
  `WHITELEV`, in addition to the existing `SATURATE` convention.
- Provenance states that black levels are available but original ADU are
  preserved, rather than claiming that no trustworthy value exists.
- Saturation records name their actual RAW or FITS-header source with
  established confidence. An observed clipping ceiling remains only a
  fallback.

Effective bit depth is derived from the trustworthy white/saturation level.
The display stretch remains a one-way visualization and never replaces the
scientific planes.

## Metadata and Blindness Boundary

Pixel decoding may expose integration time, camera, lens, ISO, CFA, black
level, and white level because these describe the measurement and are not
allowed to seed the astrometric solution.

Observation date/time and site information remain unavailable to blind
astrometry, refraction fitting, and photometric-zenith fitting. V10 extends the
post-fit metadata resolver to read CR2 EXIF with pinned `exifread`. The solver
may use that timestamp only after the stellar camera and photometric results
are fixed, under the same metadata-conditioned planet-search rules already
documented for v9. The timestamp source and any assumed timezone remain in the
audit. Failure to parse a timestamp retains the existing full-blind planetary
fallback.

## Image-Derived Sky Domain

The saved `dots/sky_footprint.npz` mask is the authoritative image-only support
domain for export. It is already produced before association by the
conservative connected illuminated-field algorithm. No catalogue positions,
camera metadata, observation site, timestamp, OCR, hand-entered radius, or
cosmetic circle may alter it.

For a framed footprint, v10 validates the Barghini-to-ZPN approximation over
the complete radial interval needed by valid mask pixels, plus dense valid-mask
and boundary samples. It requires:

- finite radial angles;
- strictly positive radial derivative;
- angles below 180 degrees throughout the valid radial interval;
- finite forward and inverse WCS transformations; and
- less than 0.05 pixel maximum added export error on all validation samples.

It does not require meaningful coordinates at rectangular detector corners
outside the sky mask. If the mask is absent, ambiguous, full-frame, malformed,
or itself reaches a non-invertible/non-physical radial domain, export retains
the current safe refusal.

The exporter preserves the original full-sized coordinate system; it does not
crop, shift, resample, or cosmetically move data or overlays. It writes an
explicit `SKYMASK` uint8 extension (`1=valid sky`, `0=non-sky`) to the annotated
scientific product and records the mask method, checksum, area, radial domain,
and WCS validation domain in `WFSINFO` and `fits_export.json`.

For the plain two-dimensional `solution.fits`, derived luminance outside the
sky mask is `NaN`. This file is already a derived solve-field compatibility
product for colour input. Its header identifies the mask policy. The annotated
FITS retains every native `R,G1,G2,B` value unchanged and carries the mask as a
separate extension. Overlay anchors and numerical residuals remain in the
original fitted coordinates.

## Error Handling

V10 fails explicitly and before analysis for:

- a CR2 that LibRaw cannot decode;
- a non-Bayer, non-2-by-2, unsupported-colour, or odd-sized visible mosaic;
- missing or inconsistent RAW plane shapes; or
- calibration arrays that cannot be mapped to the CFA channels.

FITS export fails without publishing a current `solution.fits` when:

- the saved input checksum or scientific loading policy differs;
- the saved footprint is missing or inconsistent when restricted-domain
  export is required;
- the fitted radial model is non-invertible anywhere in the accepted sky
  domain; or
- no ZPN order through the existing limit satisfies the 0.05-pixel error
  threshold.

As in v9, a refused re-export archives any previous current export rather than
leaving a stale file presented as valid.

## Verification

Development follows test-first changes in v10. Unit and integration tests must
cover:

- every supported CFA pattern and exact plane placement;
- native dtype/value preservation and half-resolution dimensions;
- an explicit guarantee that `.cr2` never reaches Pillow;
- RAW and FITS black/white-level provenance and saturation masks;
- exposure metadata and post-fit-only CR2 timestamp resolution;
- clear rejection of unsupported and malformed RAW layouts;
- full-frame export behavior unchanged for already valid cameras;
- image-derived restricted-domain WCS validation;
- refusal when the accepted footprint remains non-invertible;
- `SKYMASK`, outside-sky `NaN`, native-plane round trips, mask provenance,
  and unchanged overlay coordinates; and
- v9 preservation, v10 launcher/version consistency, manifest completeness,
  and clean-clone operation.

One final end-to-end run uses the public Rubin `asc2506240487.cr2` sample. Its
direct-CR2 result is compared with the already successful L1 FITS result:
1,507 fitted sources, approximately 0.696 reduced-image-pixel RMS and
2.868 arcminute RMS. Exact association identity and close numerical agreement
are required; changed scientific results must be explained rather than hidden
by relaxed thresholds. The run must also publish a masked WCS FITS whose valid
sky positions round-trip within 0.05 pixel and whose non-sky pixels are marked
invalid.

Before each commit, run the repository-mandated root suite and demo:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Before declaring completion, also run the complete v10 unit suite, v10 demo,
launcher/preservation checks, manifest verification, and the single Rubin
end-to-end acceptance run. Do not repeatedly rerun the expensive Rubin solve.

## Non-Goals

- Demosaiced full-resolution RGB is not a scientific input representation for
  v10.
- V10 does not alter the Barghini fit to make plots or WCS export look better.
- V10 does not infer a circular sky domain from the fitted camera or catalogue.
- V10 does not add site metadata to blind fitting.
- V10 does not support every LibRaw camera format merely because the library
  can decode it.
- V10 does not modify or import runtime code from the ISS/Moon, trail, or RAW
  acquisition projects.
