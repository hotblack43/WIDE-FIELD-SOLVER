# Native high-bit and stacked FITS input for v6

Date: 2026-09-16

## Scope

Upgrade only the `v6/` runtime and its two v6 launchers. The frozen root, v4 and
v5 runtimes remain untouched. The change accepts rendered grayscale and colour
images without reducing their scientific samples to eight bits. Camera RAW and
Bayer mosaics are outside this change; RAW converters may instead provide
already separated FITS planes.

Supported scientific inputs are:

- existing 8-bit JPEG, PNG and TIFF images;
- integer grayscale and RGB PNG/TIFF images through 16 bits per sample;
- FITS two-dimensional monochrome images;
- FITS three-plane `R,G,B` stacks; and
- FITS four-plane `R,G1,G2,B` stacks, with a floating-point derived green plane
  `G = (G1 + G2) / 2` for the existing RGB analysis.

Plane-first and plane-last stacks are accepted. Native `G1` and `G2` planes are
retained and measured independently; deriving `G` does not overwrite them.

## Authoritative loader

Add `point_star_image.py` as the only v6 scientific image decoder. It returns a
small `ScientificImage` object containing:

- native planes with their decoded numeric values and names;
- a floating-point RGB or monochrome working representation;
- floating-point detection luminance;
- a two-dimensional finite/valid-pixel mask;
- per-plane and combined saturation masks;
- a separately stretched display RGB array; and
- serialisable provenance.

Detection, footprint inference, photometry, planet non-detection checks,
diagnostic plots and FITS export must use this loader. Display arrays may be
8-bit; scientific arrays may not be quantised for display.

Stages may re-read the source to avoid retaining hundreds of megabytes for an
entire run. They must use the loading policy recorded by the detection stage and
verify the source checksum, so every stage sees the same samples and channel
mapping.

## Format rules

Use format-specific readers rather than Pillow `convert('RGB')`:

- Pillow continues to decode ordinary 8-bit JPEG and compatible images;
- a native-depth PNG reader handles high-bit PNG;
- `tifffile` handles TIFF; and
- `astropy.io.fits` handles FITS, applying standard `BITPIX`, `BSCALE` and
  `BZERO` physical-value decoding.

For FITS, automatically accept a sole suitable image HDU, an unambiguous
three/four-plane cube, or named `RED`, `GREEN`, `BLUE` and optional `GREEN1` /
`GREEN2` extensions. An explicit `--fits-hdu` selects an otherwise ambiguous
image HDU. Multiple plausible unlabelled science images cause a clear input
error listing the choices; the loader never silently chooses one.

The default three-plane order is `RGB`; the default four-plane order is
`RG1G2B`. FITS headers or extension names override defaults when unambiguous,
and `--channel-order` supplies an explicit override. Alpha/mask planes are not
treated as colour. Unsupported or ambiguous layouts fail with a descriptive
message rather than an indexing or array-shape exception.

NaN and infinite FITS samples are invalid pixels. They enter neither detection,
background estimation nor aperture photometry and are not replaced with
apparently valid zero-valued sky. A source aperture or background annulus with
insufficient valid samples is retained with an explicit unusable-photometry
reason.

## Saturation policy

Ordinary 8-bit rendered images retain the current v6 `>=250` compatibility
threshold. For native high-bit input, saturation authority in descending order
is:

1. explicit `--saturation-level`, accepting one value for every plane or a
   channel mapping;
2. trustworthy per-plane FITS saturation metadata;
3. an exact observed standard clipping ceiling of 255, 1023, 4095, 16383 or
   65535; and
4. the integer datatype ceiling.

The selected threshold, source and confidence are recorded. A datatype-ceiling
fallback is explicitly labelled as an assumption. Floating-point data without
an explicit or trustworthy metadata threshold has unknown saturation: the run
continues, sources carry `saturation_known=false`, and photometry reports that
it could not exclude clipping rather than inventing a threshold.

Any native plane reaching its threshold makes the source saturated for the
existing conservative astrometric/photometric rules. Per-plane flags are also
saved. The 8-bit compatibility rule protects the historical v6 regression from
a silent classification change.

## Measurements and products

All background, noise, centroid and aperture calculations use floating-point
arrays derived directly from native samples. Their numerical units remain input
ADU or decoded FITS physical units. No global rescaling is applied. Adaptive
signal-to-noise thresholds therefore continue to operate across bit depths.

`stellar_photometry.csv` retains its existing `R/G/B` columns. Four-plane data
adds `G1` and `G2` flux, magnitude, saturation and usability columns, while `G`
remains the derived channel used by the current extinction fit. Monochrome input
uses an explicitly named luminance channel and maps it to the existing G-based
extinction interface without claiming independent RGB colour.

Write `input_image.json` in every v6 analysis with source checksum, format,
stored and decoded dtypes, array shape, effective bit-depth evidence, FITS
HDU/channel selection, scaling keywords, invalid-pixel counts, black-level
status, saturation policy and channel derivations. Summaries and the PDF state
whether input samples were native-depth and whether saturation was known.

FITS exports preserve every native source plane and its numeric values. The
plain astrometry.net-compatible primary image remains two-dimensional and may be
a derived floating-point luminance plane; it is labelled as derived. The
annotated FITS retains all original planes plus WCS and provenance. This export
derivation does not replace or alter the input evidence.

## Display policy

Plots use a deterministic finite-pixel percentile stretch made only for display.
Each rendered plot states that it is stretched when the source is not already an
8-bit display image. Plotting must never feed pixels back into detection,
photometry, saturation decisions or planet evidence.

## Command line and compatibility

`go6.sh` / `go_v0.6.0.sh` accept `--fits-hdu`, `--channel-order` and
`--saturation-level` and pass them only into v6. Existing commands need no new
arguments. Unsupported input fails before creating a partial analysis directory.

The v6 source manifest and feature-status documentation are updated deliberately.
The database/index proposal remains deferred; immutable per-run CSV/JSON/FITS
files stay canonical.

## Verification

Tests construct equivalent synthetic scenes at 8, 12, 14 and 16 bits and assert:

- samples above 255 remain distinct;
- centroids agree within the existing numerical tolerance;
- fluxes scale by their encoded gain and instrumental-magnitude differences
  follow that scale;
- 12/14-bit clipping in 16-bit containers is flagged by the agreed hierarchy;
- FITS `BSCALE/BZERO`, invalid pixels, selected HDUs and plane-first/plane-last
  RGB/RG1G2B stacks are handled correctly;
- native `G1/G2` measurements survive while derived G is their mean;
- display stretching cannot alter scientific products;
- existing 8-bit v6 regression products remain within their fixed thresholds;
  and
- v4, v5 and preserved root runtime hashes remain unchanged.

Before publication, run the complete unit suite, the required unique-name demo,
the v6 regression checks and launcher/version-boundary checks.
