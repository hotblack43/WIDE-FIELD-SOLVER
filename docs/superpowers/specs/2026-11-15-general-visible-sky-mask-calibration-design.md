# General Visible-Sky Mask Calibration Design

## Intent

Generalise the v24 camera-installation visible-sky mask from one MMTO-specific
calibration into a complete workflow that another operator can use with any
fixed all-sky camera supported by the downloader and v24 image loader. The
workflow begins with verified original images, proposes an installation mask,
produces review figures, requires explicit approval, registers the immutable
calibration, and applies it to later images from that installation.

The existing approved MMTO mask remains immutable evidence. The generic path
must reproduce its creation from a clean calibration state without reading the
approved mask or its review artifacts during proposal generation.

This is a detector-coordinate obstruction calibration. It is not an
altitude-versus-azimuth terrain horizon and supplies no site, time, or
astrometric answer to the blind solve.

## Goals

- Remove MMTO-specific names and identifiers from the proposal builder.
- Generate a draft from verified downloaded originals selected across multiple
  observing dates and night phases.
- Preserve native detector samples and require one unchanged detector shape,
  plane layout, instrument identity, and orientation per installation.
- Produce normal and inverted boundary-review images before approval.
- Make approval a separate, explicit operation that freezes a binary mask,
  applies the safety margin, writes provenance and checksums, and refuses to
  overwrite an existing calibration.
- Maintain a portable calibration registry mapping a source, camera, and
  installation identifier to an approved manifest.
- Bind individual source checksums to an installation before solving, so a
  camera move or replacement cannot silently repoint historical images.
- Let the generic v24 launcher resolve an approved mask for downloaded images,
  while retaining explicit manifest and installation options for arbitrary
  local images.
- Preserve the current MMTO v24 pipeline behaviour through the generic
  interfaces rather than through MMTO-only constants and helper modules.
- Demonstrate the workflow with a cold-start MMTO replay and held-out MMTO
  frames.

## Non-goals

- No automatic approval or silent promotion of a draft.
- No claim that one image can distinguish the true sky boundary from clouds,
  snow, glare, twilight, or transient illumination.
- No inference that a camera has moved solely from one science image.
- No resampling, rotation, warping, or reuse of a mask from another detector
  geometry or installation.
- No use of site coordinates, solved coordinates, cached identities, or the
  existing approved mask to classify pixels or tune a proposal. Observation
  dates and within-night ordering may be used only to select temporally diverse
  calibration frames and to predeclare the held-out split; they never enter the
  pixel classifier or the blind solver.
- No claim of cross-camera validation from replaying MMTO data.
- No modification of v23 or an earlier frozen runtime.

## Selected approach

Use a complete but controlled calibration workflow:

1. The downloader records verified originals and their source and camera IDs as
   it does now.
2. A generic calibration command queries that download manifest, or accepts an
   explicit JSON list for images outside a managed archive.
3. It validates a single detector signature and selects representative frames
   deterministically across dates and early, middle, and late night phases.
4. The existing temporal-consensus algorithm writes a review-only proposal.
5. An operator inspects the two boundary overlays and explicitly approves the
   exact draft checksum.
6. A finalisation command erodes the visible region by the chosen safety margin,
   writes an immutable PNG and manifest, and appends the calibration to a
   registry.
7. Each downloaded image is assigned by source checksum to an explicitly active
   installation after its instrument and detector signature have been checked.
8. The solver resolves the source assignment to the approved manifest and
   records the installation ID, mask ID, and checksums in its result.

The alternative builder-only approach was rejected because it would still
leave outside users to hand-author manifests and manually connect every solve
to a mask. Fully automatic generation and approval was rejected because a
plausible boundary is not sufficient scientific evidence that the calibration
is correct.

## Commands and user workflow

The existing builder becomes camera-neutral and exposes three operations. Exact
option spelling may be adjusted during planning, but the responsibilities stay
separate.

### Propose from a managed download archive

```sh
uv run --project v24 --frozen python v24/scripts/build_visible_sky_mask.py \
  propose \
  --download-manifest raw_allsky_samples/manifest.sqlite \
  --source mmto \
  --camera mmto-skycam \
  --installation-id mmto-skycam-2026a \
  --orientation detector_native_top_left_xy_right_y_down \
  --output calibration-review/mmto-skycam-2026a
```

An alternative `--sources FILE.json` remains available for verified files that
are not in the managed download archive. Source and camera identity, instrument,
detector shape, plane layout, orientation, source checksums, selection rule,
and date coverage are recorded in `selection.json`.

The builder no longer emits an MMTO-specific draft filename. The draft name is
derived safely from the installation identifier, and all identifiers are passed
explicitly or resolved from the download manifest.

### Approve and register

```sh
uv run --project v24 --frozen python v24/scripts/build_visible_sky_mask.py \
  approve \
  --proposal calibration-review/mmto-skycam-2026a/selection.json \
  --reviewed-draft-sha256 SHA256 \
  --mask-id mmto-visible-sky-2026a-v1 \
  --approved-by Peter \
  --safety-margin-pixels 5 \
  --calibration-root camera-calibrations
```

Approval fails unless the supplied checksum identifies the exact draft named by
the proposal, every proposal artifact is intact, the calibration root contains
no conflicting installation or mask ID, and all required identity fields are
complete. It writes the approved PNG and JSON manifest first, validates them
through the production loader, then atomically appends the registry entry.

The approval statement is provenance, not authentication. The command records
the approving name, UTC date, proposal checksum, generation-code checksum,
finalisation-code checksum, and safety margin.

Approval registers the calibration but does not make it active for future
downloads. Activation is a separate explicit operation, so reviewing an
artifact cannot silently change acquisition behaviour:

```sh
uv run --project v24 --frozen python v24/scripts/build_visible_sky_mask.py \
  activate \
  --calibration-registry camera-calibrations/registry.jsonl \
  --source mmto \
  --camera mmto-skycam \
  --installation-id mmto-skycam-2026a
```

An activation record is append-only. Changing it affects only files downloaded
after that record; it never reassigns an existing source checksum.

### Correct and reseal a proposal

An operator may correct a proposed binary boundary, but never edits an existing
proposal in place. A `revise` operation accepts the parent `selection.json` and
one edited binary PNG, validates its shape and 0/255 values, and writes a new
immutable proposal directory. It regenerates both boundary overlays and every
artifact hash, and records the parent proposal inventory and edited-mask hash.
Only the new sealed proposal may be approved.

### Solve with registered calibration

For a downloaded file whose checksum already has an installation assignment,
the launcher can resolve the calibration from the download manifest and
calibration registry:

```sh
./go24.sh downloaded-image.fits.bz2 \
  --download-manifest raw_allsky_samples/manifest.sqlite \
  --calibration-registry camera-calibrations/registry.jsonl
```

For an arbitrary local image, the existing explicit pair remains supported:

```sh
./go24.sh image.fits \
  --visible-sky-mask-manifest camera-calibrations/example/example-v1.json \
  --camera-installation-id example-installation-v1
```

Supplying both automatic-resolution and explicit-mask options is an error. A
downloaded image without an installation assignment remains unmasked only when
the user explicitly requests the generic unconfigured path; the MMTO production
pipeline continues to fail closed.

For an arbitrary local image, selecting the explicit manifest and installation
ID is the operator's declaration that the image belongs to that physical
installation and orientation. The runtime independently checks the decoded
instrument identity when present, detector shape, and plane layout against the
manifest. Orientation cannot be derived from ordinary image metadata and is
therefore verified by the explicit installation selection. Source ID and camera
ID are not required for this unmanaged local-image path.

## Calibration registry and assignments

The calibration root is user-selectable and may live outside the repository.
Bundled release calibrations, including MMTO, use the same schema and may be
searched as a read-only registry layer. User calibrations form a separate
writable layer, avoiding edits inside an installed or unpacked release.

The append-only registry records:

- source ID and camera ID;
- installation ID and mask ID;
- instrument identity and optional serial;
- detector shape, plane layout, orientation, and coordinate convention;
- manifest path and manifest SHA-256;
- mask path and mask SHA-256;
- approval provenance; and
- registry-record UTC time.

An installation ID and a mask ID are globally unique within the combined
registry layers. An identical repeated registration is idempotent; a conflicting
record is fatal.

Source-to-installation assignments remain append-only and are keyed by source
SHA-256. They are not reconstructed from a timestamp. The active installation
for future downloads is an explicit operator setting for a source/camera pair.
Changing that setting creates a new installation; it never changes assignments
already recorded for earlier source checksums.

For new managed downloads, assignment is written transactionally at successful
ingest using the then-active installation, after detector-signature validation.
If assignment cannot be validated, the verified original remains preserved but
unassigned and cannot enter a fail-closed configured solve. Existing historical
files are assigned only by a separate bounded `assign-existing` operation that
prints the selected source checksums before applying them. Lazy assignment at
solve time is prohibited because it could bind historical images to whichever
installation happens to be active later.

Before assigning a file, the system validates instrument identity when present,
decoded shape, plane layout, and declared orientation against the approved
manifest. Missing instrument serial may match the same recorded camera model,
as in the existing MMTO rule; a different explicit serial is rejected.

## Proposal generation

The temporal-consensus numerical method remains the v24 method unless cold-start
evidence reveals a concrete defect. It combines robustly normalised temporal
median, temporal variability, accumulated source density, optical-footprint
consensus, persistent dark structure, radial skyline, and the connected region
containing the detector centre.

The proposal command requires at least three valid frames but warns that this is
only the algorithmic minimum. The review record reports the number of dates,
night-phase coverage, and detector-signature consistency. No minimum number of
dates is silently claimed to establish a production-quality mask.

Every proposal is immutable: the output directory must not exist. Review files
include the binary draft, temporal reference, normal overlay, inverted overlay,
selection record, and hashes of every artifact. Drafts are never eligible for
runtime resolution.

Observation date and within-night order are permitted only at this selection
boundary: they create temporal diversity and the predeclared held-out split.
They are not inputs to intensity normalisation, temporal evidence, morphology,
the visible-sky classifier, or any subsequent blind astrometric calculation.

## Cold-start MMTO replay

The replay is a calibration reproducibility experiment, not an independent
cross-camera validation.

### Isolation

Run in a fresh temporary calibration root containing:

- no approved PNG or JSON mask;
- no proposal or review artifacts;
- no calibration registry;
- no source-to-installation assignments;
- no solver result database; and
- only the generic v24 code, the verified MMTO raw files, and download metadata
  needed to locate those files.

The proposal process receives no path to `v24/data/sky_masks/`, the existing
MMTO `selection.json`, or the frozen approved mask. The test records every input
path and hash and seals the new proposal and selection record before any
comparison reference is opened.

Because the temporal algorithm and its thresholds were originally developed
with MMTO, this is correctly described as a clean-state reproducibility replay,
not as though the method itself had never been informed by MMTO.

### Training and held-out dates

Partition observing dates deterministically before loading images. Calibration
dates generate the proposal. Held-out dates do not affect selection, temporal
evidence, thresholds, morphology, or manual corrections.

The split rule and resulting date lists are written before generation. The
planner will select a deterministic rule that preserves early, middle, and late
coverage across the full available interval and leaves at least one fifth of
the dates held out. No frame from a held-out date may enter the proposal.

### Sealed evaluation

After the proposal directory and its SHA-256 inventory are sealed:

1. Render the new boundary on held-out native MMTO frames.
2. Measure the new mask's visible fraction and stability of the apparent
   foreground boundary over held-out dates.
3. Run detection on held-out frames and audit sources rejected by the new static
   mask, especially supports intersecting the boundary.
4. Only then reveal the existing approved MMTO mask and compute pixel agreement,
   intersection-over-union, false-visible area, false-excluded area, and boundary
   distance distributions.
5. Present the new normal and inverted overlays beside the approved boundary for
   Peter's review.

The first cold-start run establishes observed comparison values; it does not
invent acceptance thresholds in advance. If Peter approves the cold-start
boundary, conservative regression thresholds are fixed from that sealed result
with documented margins and may not later be relaxed to conceal a failure.

The held-out test establishes whether a calibration made from part of the MMTO
history remains usable on other MMTO dates. It cannot establish that the method
works on a different camera geometry or foreground. A future real non-MMTO raw
sequence remains the required cross-camera validation.

## Runtime behaviour

The existing v24 rule remains authoritative:

```text
usable_pixel = static_visible_sky AND dynamic_footprint AND finite_pixel
```

The generalisation changes calibration discovery and lifecycle, not numerical
mask application. Excluded pixels remain absent from detection, noise and
background estimation, centroiding, association, astrometry, photometry,
planet negative evidence, and lunar evidence. The mask never moves measured or
predicted positions.

An explicitly unconfigured generic solve retains the pre-v24 numerical path and
records `not_configured`. A configured solve records the resolved source ID,
camera ID, installation ID, mask ID, manifest checksum, mask checksum, registry
record, and assignment evidence.

## MMTO migration

The bundled `mmto-visible-sky-2026a-v1` PNG and JSON remain byte-for-byte
unchanged. Add a bundled registry entry describing that existing calibration.
Route the MMTO pipeline through the generic registry and assignment APIs while
preserving its fail-closed requirement and its existing receipt definition.

Existing MMTO source assignments are imported idempotently into the generic
assignment schema. No historical result is rewritten. V24 receipts produced
with the same mask and installation continue to count as completed masked work.

MMTO-specific archive timing, weather, header validation, photometry, and queue
behaviour remain in the MMTO pipeline; only camera-calibration handling becomes
generic.

## Error handling

Fail before source detection when:

- proposal inputs contain mixed detector signatures;
- an input checksum or managed-download record is invalid;
- the proposal or approved output path already exists;
- proposal artifacts changed after review;
- a mask is not binary, has the wrong shape, or fails its checksum;
- installation, instrument, plane layout, or orientation is incompatible;
- registry layers contain conflicting identifiers;
- a source checksum has conflicting installation assignments; or
- automatic resolution finds no unique approved calibration.

Errors identify the source, camera, installation, and evidence path needed to
resolve the problem. A failure never falls back silently from a configured mask
to an unmasked solve.

## Testing

Use test-driven development for each layer:

- generic proposal names and metadata contain no MMTO defaults;
- managed-download selection includes only verified files for one source and
  camera and remains deterministic;
- mixed shape, layout, instrument, and orientation inputs fail;
- approval requires the exact reviewed draft checksum;
- a corrected draft creates a new immutable child proposal with regenerated
  overlays and a complete parent provenance link;
- finalisation applies the requested safety margin and refuses overwrite;
- registry append is atomic, idempotent for an identical record, and rejects
  conflicts across bundled and user layers;
- approval does not activate an installation, while a separate append-only
  activation affects only future downloads;
- new downloads receive their assignment transactionally at ingest, and
  historical images require explicit bounded assignment rather than lazy
  solve-time binding;
- source assignments are immutable and historical files are not repointed when
  the active installation changes;
- automatic resolution selects exactly one approved calibration;
- explicit and automatic mask options cannot be combined;
- MMTO production still fails closed without its approved assignment;
- the generic no-mask path remains numerically unchanged;
- the existing v24 mask-loading, detection, photometry, planet, lunar, report,
  and receipt regressions continue to pass;
- the isolated cold-start MMTO replay writes sealed comparison evidence and
  never reads the approved mask before the reveal stage.

Before completion run the v24 full unit suite and demo, the root full unit suite
and unique-name demo required by the repository, preserved-runtime boundary
checks, and the cold-start MMTO replay. The known repository CI manifest defect
must be fixed rather than bypassed or hidden by weaker checks.

## Documentation and release boundary

Update the v24 README and root documentation to distinguish:

- bundled MMTO calibration;
- user-generated draft calibration;
- explicitly approved user calibration;
- automatic resolution for a downloaded source with an immutable assignment;
  and
- the unconfigured generic path.

Document that camera movement, rotation, detector cropping, or replacement
requires a new installation ID and review. State the evidence required before
claiming another camera is validated.

The generalised workflow belongs in v24 while v24 remains the active
development line. If v24 is frozen before implementation finishes, development
moves intact to a new version directory and launchers rather than altering the
frozen boundary.

## Approaches considered

1. **Generic builder only.** Smallest change, but outside users must still
   hand-author manifests and manually connect each solve to a mask.
2. **Complete controlled workflow (selected).** Generic proposal, explicit
   approval, registry, immutable source assignments, and automatic resolution;
   more work, but it meets the intended outside-user workflow safely.
3. **Fully automatic mask generation and approval.** Convenient but rejected:
   transient sky structure can produce a plausible wrong boundary, and silent
   self-approval would erase the scientific review boundary.
