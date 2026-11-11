# V24 Camera-Installation Visible-Sky Mask Design

## Intent

Exclude every detector pixel hidden by the fixed MMTO foreground before source
detection. Buildings, dome structure, poles, antennae, the camera housing, and
the region outside the optical field must not supply detections or pixels to
astrometry, photometry, planet association, lunar evidence, or planet
nondetection evidence.

The mask is a calibration of one physical camera installation. If the camera is
moved, rotated, replaced, or the same software is used with another camera, a
new installation identifier and a new mask are required. Old masks remain
immutable evidence.

## Version boundary

V23 and its launchers remain frozen. This change is developed in a new `v24/`
runtime with `go24.sh`, `go_v0.24.0.sh`, and
`go_mmto_photometry_v24.sh`. V24 is initially copied from the final v23 source
and receives its own catalogue, lockfile, ephemeris data, examples, source
manifest, tests, and runtime boundary record.

The generic solver remains usable without a static mask and then records
`not_configured`, preserving the pre-v24 full-detector behaviour. The MMTO v24
launcher requires its installation-specific mask and refuses to continue if it
cannot validate it.

V24 preserves the v23 acquisition order, one-night-at-a-time remote access,
weather gate, solver-worker bound, and per-invocation image cap. It may reuse
the append-only archive, download manifest, results database, and durable v23
backward cursor. V23 and v24 receipts both count as completed acquisition work,
so changing solver versions never restarts the historical queue. Only a v24
receipt represents masked analysis; any historical masked reprocessing must be
requested explicitly rather than being folded into routine queue progress.

## Selected approach

Use a hybrid temporal-consensus mask:

1. Read the original high-dynamic-range MMTO FITS files, not rendered previews.
2. Select representative images across observing dates, darkness, twilight,
   cloud state, and both sides of the night.
3. Normalize the images and combine temporal intensity, edge, and accumulated
   source-density evidence into a proposed unobstructed-sky region.
4. Render the proposal over normal-intensity reference images for human review.
5. Peter reviews and approves or corrects the outline. A draft mask cannot be
   selected by a production launcher.
6. Apply the approved corrections, then add a five-pixel inward safety margin
   by dilating the excluded foreground.
7. Freeze the approved binary mask and its provenance. Runtime solving consumes
   the frozen artifact and never relearns or adapts it from the current image.

This combines reproducible evidence from many frames with an inspectable final
boundary. A fully automatic runtime mask is rejected because clouds, twilight,
the Milky Way, and bright planets can change image structure. A hand trace from
one image is rejected because its edge choices and transient obscuration are
weaker evidence than the time series.

## Mask artifact and coordinate convention

The approved artifact is a lossless, binary, single-channel PNG under
`v24/data/sky_masks/`. Pixel value 255 means unobstructed sky may be used;
pixel value 0 means excluded. Intermediate grey values are invalid. Its array
shape must exactly equal the decoded detector shape. Array row is detector
`y`, array column is detector `x`, and `(0, 0)` is the top-left pixel used by
the existing plots and CSV products. The mask is never resized, registered,
warped, rotated, or interpolated at runtime.

A neighbouring JSON manifest records:

- immutable mask identifier and camera-installation identifier;
- camera/instrument identity, detector shape, plane layout, and orientation;
- mask SHA-256 and generation-code SHA-256;
- source image SHA-256 values and selection rationale;
- temporal-consensus method and thresholds;
- the five-pixel safety margin;
- approval date and coordinate convention.

Observation dates retained for provenance are not solver inputs. Only the
binary detector mask and the camera-installation identity affect pixel
eligibility.

## Camera lifecycle and reset

The first MMTO artifact receives a distinct installation identifier, separate
from the camera model name. Installation identity and orientation are explicit
operator-managed acquisition configuration; they are not inferred from the
FITS timestamp, site, or an astrometric answer. The v24 MMTO launcher selects
the identifier and mask through that configuration. It verifies the declared
installation assignment, FITS instrument identity, decoded shape, plane layout,
mask checksum, and manifest before image analysis. A FITS header does not by
itself prove the physical camera orientation.

The shared acquisition manifest gains append-only v24 installation records and
an explicit `source_sha256` to installation-identifier assignment. Future
downloads receive the currently active installation identifier when their
native FITS identity is validated. Existing archive images are assigned only by
a one-time audited migration: the currently sampled 927 September--November
v23 images have measured skyline stability, while any other historical images
must pass the same installation-consistency audit before assignment. Mask
selection at solve time is by this recorded hardware assignment, never by date.

Moving or rotating the same camera creates a new installation identifier and a
new mask. A different camera always creates a new identifier and mask. New
artifacts are added; existing artifacts are never overwritten or silently
repointed. A mask belonging to another installation, instrument, orientation,
or detector shape is a fatal configuration error for the MMTO launcher.

There is no claim that one arbitrary cloudy frame can reliably prove that a
camera has moved. Resetting the installation identifier is an explicit
operational action. Every saved result records the identifier and mask checksum
so accidental reuse is auditable.

The mask-building command refuses to overwrite an existing installation. Its
first stage produces only proposal images and a draft artifact. Production
integration resumes only after Peter approves the boundary; the final manifest
records that approval and the exact draft from which it was derived.

## Runtime application

After native image decoding, v24 loads the static visible-sky mask and combines
it with finite-pixel validity and the existing per-image optical-footprint mask:

`usable_pixel = static_visible_sky AND dynamic_footprint AND finite_pixel`

This combined mask is authoritative throughout the run.

### Detection and astrometry

- Excluded pixels do not enter background or noise estimation, smoothing,
  thresholding, local-maximum searches, connected components, centroiding, or
  morphology measurements.
- Numerical padding needed by convolution is filled from valid local or robust
  background values and can never create an eligible source. Candidate support
  must remain inside the usable region.
- Every compact, broad, large, or saturated source detected in unobstructed sky
  remains eligible for association and astrometric fitting. No withheld-star
  split is introduced.
- The mask never moves a centroid, a model prediction, or a plotted symbol.
- Only detections formed from usable pixels can reach catalogue association or
  the Barghini fit.

### Photometry

- Aperture and sky-annulus pixels are drawn only from the combined mask.
- A source whose required aperture or annulus intersects the static installation
  mask is retained in the measurement table but marked unusable with the
  explicit reason `aperture_or_annulus_intersects_visible_sky_mask`.
- Existing v23 reasons and behaviour for dynamic-footprint and nonfinite-pixel
  exclusions remain distinct; they are not relabelled as installation-mask
  exclusions.
- Partial apertures are not rescaled into complete measurements.
- Existing saturation and quality flags remain independent of mask exclusion.

### Planets, Moon, and negative evidence

- A predicted planet position outside the usable region is recorded as
  `masked_obstruction` when the static installation mask is the excluding
  layer, never as `predicted_no_detected_source`. Existing below-horizon,
  off-detector, noninvertible-projection, and dynamic-footprint statuses retain
  their own meanings and take precedence when applicable.
- `masked_obstruction` supplies no absence penalty, cannot contradict a planet
  epoch candidate, and cannot trigger targeted source recovery.
- Metadata-conditioned downstream planet photometry reads the exact saved mask
  identity and applies the same eligibility rule; it does not reconstruct a
  mask from the current image.
- Lunar and other broad-object evidence uses the same combined mask. A broad
  candidate intersecting the excluded boundary cannot establish lunar presence
  or absence.
- Image-derived zenith, the horizon altitude rule, and the blindness boundary
  remain unchanged. The detector obstruction mask is not an astronomical
  horizon model and contains no site or time information.

## Saved evidence and figures

Each v24 run stores or references, by checksum:

- the static mask manifest and installation identifier;
- the static-mask, dynamic-footprint, and combined-mask pixel counts;
- a compressed combined usable-pixel mask;
- a normal-intensity image with the excluded region shaded and the approved
  boundary drawn without moving any source markers;
- mask-specific detection and photometry exclusion counts;
- explicit `masked_obstruction` planet and lunar records.

The investigator-facing report identifies the mask and installation, gives the
usable detector fraction, and distinguishes fixed foreground exclusion from
per-image optical-footprint exclusion. Database products retain enough evidence
to reproduce every eligibility decision.

## Validation and regression evidence

Focused tests must establish that:

- non-binary, wrong-shape, wrong-checksum, wrong-instrument, wrong-orientation,
  and wrong-installation masks are rejected; orientation mismatch means the
  operator-declared installation/orientation differs from the immutable mask
  manifest, not that orientation was inferred from a FITS header;
- a synthetic bright, broad, or saturated source wholly behind the mask creates
  no eligible detection;
- unmasked sources, including large and saturated sources, retain v23 behaviour;
- convolution and connected-component processing do not leak masked signal
  across the boundary;
- masked detections cannot reach association or the astrometric fit;
- aperture or annulus overlap produces the recorded unusable measurement row;
- a masked planet prediction is neutral negative evidence and is not recovered;
- the Moon gate cannot use an object truncated by the mask;
- a generic no-mask run reproduces the v23 numerical path;
- the approved MMTO mask removes the fixed structures while retaining ordinary
  stars immediately inside its visible boundary.

V24 must run its complete unit suite and fresh demo, plus the repository's
required root suite and demo. Numerical changes in the MMTO example and
population products are documented rather than hidden by relaxed thresholds.
Before publication, all preserved runtimes are checked and v23 receives a
runtime hash record freezing its final state.

## Non-goals

- No automatic per-image skyline learning.
- No automatic inference of camera installation or physical orientation from an
  observation timestamp or a single science image.
- No resampling or geometric transformation of a mask from another camera or
  installation.
- No use of site, timestamp, filename date, or saved identities to construct a
  blind-fit mask.
- No cosmetic movement of sources or predictions away from the mask boundary.
- No partial-aperture correction.
- No modification of v23 or any earlier preserved runtime.

## Approaches considered

1. **Manual trace from one image.** Simple and transparent, but too dependent on
   one exposure and subjective edge placement.
2. **Fully automatic temporal mask.** Repeatable, but transient sky structure
   can be mistaken for fixed foreground and runtime adaptation would make
   eligibility change between images.
3. **Temporal consensus followed by one human approval (selected).** Uses the
   full image history to propose the boundary, preserves an inspectable manual
   decision, and yields one immutable artifact per camera installation.
