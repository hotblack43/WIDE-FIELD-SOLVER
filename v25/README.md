# Wide-Field Solver v0.25.0

V25 is based directly on frozen v24. It preserves the accepted generic
visible-sky calibration and masked photometry runtime. Its automatic
managed-archive camera-mask engine is implemented and tested, but the current
standalone operator is an experimental maintenance interface rather than the
final routine workflow. V25 does not change the accepted MMTO mask or the
underlying proposal algorithm.

## Overview

Wide-Field Solver identifies stars in very wide-angle sky images and fits a
physical Barghini camera model to their measured positions. It supports native
colour FITS data, including compressed `.fits.bz2` files, and preserves measured
centroids and native detector values throughout the analysis.

The software was created by Peter Thejll and Chris Flynn. It is released under
the permissive [BSD 3-Clause licence](LICENSE), which permits use, modification
and redistribution while requiring the copyright notice and licence to remain
with the software. It does not permit anyone to claim authorship of the original
work.

## Operational commands

The runtime requires Bash and uses [uv](https://docs.astral.sh/uv/) for its
pinned Python environment. From the repository root, install it once:

```sh
uv sync --project v25 --frozen
```

Solve one image with the real v25 launcher:

```sh
./go25.sh /full/path/to/image.fits.bz2
```

Run the v24-compatible bounded MMTO acquisition and analysis pipeline with:

```sh
./go_mmto_photometry_v25.sh
./go_mmto_photometry_v25.sh --max-images 123
```

The intended final v25 behavior is this same routine pipeline plus transparent
horizon-mask construction when it encounters a new detector/installation. That
integration is not complete in this checkpoint. The separate command below is
retained for testing and advanced maintenance; it is not a replacement for the
MMTO pipeline and does not accept `--max-images`.

Generate, validate, register, and activate masks for every camera population
with sufficient verified data in `raw_allsky_samples/manifest.sqlite`:

```sh
./go_visible_sky_v25.sh
```

No camera identifiers, paths, hashes, or mask names are required. The command
first performs bounded acquisition for every uncalibrated camera whose public
RAW source adapter enables automatic acquisition: at most ten recent completed
nights and ten originals per night. It then discovers source/camera populations
from the managed manifest and skips those
that already have an approved registered mask or do not yet meet the minimum
date and held-out-image counts. Adding ordinary images to a calibrated camera
does not regenerate its installation mask. It derives a stable automatic
installation ID from the managed source and camera IDs.

When the bounded acquisition reaches the validation threshold, mask generation
continues in that same invocation. If an archive supplies fewer usable images,
the command reports `ACQUIRING` and a later invocation continues filling the
missing nights. Sources without a verified public RAW adapter are never guessed
or silently substituted with rendered previews.

This command selects verified native originals, holds out complete dates,
creates and seals a proposal, audits the held-out images, builds five date-fold
proposals, applies the fixed acceptance gates, and only then approves,
registers, and activates the mask. It prints one final `ACTIVATED` or `NOT
ACTIVATED` line and names the durable receipt. Automated validation is not
visual review, and the manifest records `approval_mode: automated_validation`
and the machine actor rather than attributing the decision to a person.

Automatic setup requires at least 10 distinct observing dates, including 8 calibration dates
and 2 held-out dates, with at least 20 held-out originals.
The fixed gates also require exactly one detector signature, a nonempty
single-component proposal with visible fraction between 0.10 and 0.95, a
single-component finalized production mask whose visible fraction remains
between 0.10 and 0.95 after the five-pixel inward safety margin, a
median held-out image-footprint IoU of at least 0.80, minimum held-out image-footprint IoU
at least 0.50, at least 100 held-out unmasked detections, and a held-out
boundary-intersection fraction no greater than 0.05. All five date-fold masks
must have IoU at least 0.95 against the primary mask, mean symmetric boundary
separation no greater than 10 pixels, and p95 separation no greater than 24 pixels.
Missing, Boolean, non-finite, or zero-denominator evidence fails closed.

When new verified originals change the accepted evidence for the same fixed
installation, v25 publishes a new immutable content-addressed mask version and
activates that exact mask ID. Earlier masks and activation history remain
preserved. Moving, rotating, cropping, or replacing the camera still requires a
new installation ID.

In short: automated validation is not visual review.

If another installation is already active for the same source and camera, the
command stops before proposal generation. Switch only with an explicit:

```sh
./go_visible_sky_v25.sh auto \
  --replace-active
```

For an archive outside the repository, or an operator-chosen installation ID,
the previous configuration-file form remains an advanced override. Copy
`v25/examples/visible_sky_operator.example.toml` and run:

```sh
./go_visible_sky_v25.sh auto --config /path/to/camera.toml
```

The existing `propose`, `revise`, `approve`, and `activate` subcommands remain
available as advanced recovery tools. They preserve the manual human-review
lifecycle and never overwrite an earlier proposal:

```sh
./go_visible_sky_v25.sh propose \
  --config camera-configs/visible-sky/my-camera.toml
./go_visible_sky_v25.sh approve \
  --config camera-configs/visible-sky/my-camera.toml \
  --proposal calibration-review/INSTALLATION/selection.json \
  --reviewed-draft-sha256 SHA256 --mask-id MASK_ID --approved-by NAME
./go_visible_sky_v25.sh activate \
  --config camera-configs/visible-sky/my-camera.toml
```

The automatic path is regression-tested with synthetic multi-date cameras.
MMTO remains the only real cold-start installation validated from thousands of
native originals; real non-MMTO validation is still limited until another physical camera
passes every automatic gate.

## Verification demo

The demo is a verification command, not the production interface:

```sh
./v25/demo.sh --output v25/results/mmto-demo-v25
```

Dependency installation may require an Internet connection. The demonstration
solve uses the catalogue and solver data included in the package and is invoked
with `--offline`; it makes no catalogue-name network request.

## Built-in MMTO example

The demonstration analyses a native three-colour FITS observation from the MMT
Observatory all-sky camera. Use a fresh output name for every run. A successful
run prints its output location and verifies the result against conservative
scientific thresholds recorded with the example. The v25 demo now runs through
the public analysis entry point with the bundled approved MMTO visible-sky mask,
and verifies that mask's installation ID, mask ID, and SHA-256. On the preserved
example this intentionally changes the v23-era unmasked counts from 1,526
detections and 1,409 associations to 1,362 and 1,280 respectively; the fit
remains at 0.326 px RMS while obstruction-region sources are excluded.

The image credit and its permission boundary are stated in [NOTICE.md](NOTICE.md).
In short: MMTO all-sky-camera image courtesy of MMT Observatory, provided with
permission from Tim Pickering. That permission is separate from the software
licence.

## Solve your own image

Pass one or more input files to the v0.25 launcher:

```sh
./go25.sh /full/path/to/image.fits.bz2
./go25.sh first.fits second.cr2 --results-dir /full/path/to/results
```

By default, output goes to `results/` beside the release. Use `--results-dir`
to select a different location. Inputs are processed sequentially; a failed
image keeps its diagnostic output and does not prevent later inputs from being
attempted.

## Supported inputs

Supported inputs include compressed and uncompressed FITS, Canon CR2, and
native-depth PNG and TIFF images. Colour FITS may contain RGB or `R/G1/G2/B`
planes in common plane-first, plane-last or named-extension layouts. Use
`./go25.sh --help` for FITS HDU, channel-order, saturation and visible-sky
options.

## Visible-sky calibration for a fixed camera

An arbitrary local image still follows the unchanged unmasked path:

```sh
./go25.sh image.fits
```

For a fixed camera, first download native originals with the ordinary
downloader. Calibration assignment is opt-in and does not change existing
downloader commands. The three options below must be supplied together:

```sh
uv run --project v25 --frozen python v25/download_samples.py \
  --site example --camera camera-a --date 2026-11-01 \
  --calibration-registry camera-calibrations/registry.jsonl \
  --installation-assignments camera-calibrations/assignments.jsonl \
  --camera-orientation detector_native_top_left_xy_right_y_down
```

Create a review-only proposal from verified managed downloads:

```sh
uv run --project v25 --frozen python v25/scripts/build_visible_sky_mask.py \
  propose --download-manifest raw_allsky_samples/manifest.sqlite \
  --archive-root raw_allsky_samples --source example --camera camera-a \
  --installation-id example-camera-2026a \
  --orientation detector_native_top_left_xy_right_y_down \
  --output calibration-review/example-camera-2026a
```

The proposal is `draft_not_approved` and cannot be used in production. An
operator may use `revise` to create a new immutable child proposal; the parent
is never overwritten. `approve` requires the reviewed draft SHA-256, writes a
new immutable binary mask and manifest, validates them with the production
loader, and registers them. Approval does not activate the installation:

```sh
uv run --project v25 --frozen python v25/scripts/build_visible_sky_mask.py \
  activate --calibration-registry camera-calibrations/registry.jsonl \
  --source example --camera camera-a --installation-id example-camera-2026a
```

Moving, rotating, cropping, or replacing a camera requires a new installation
ID and a new reviewed mask. Existing source checksums are never reassigned by a
later activation. Historical verified downloads can be previewed and assigned
in an explicitly bounded `assign-existing` operation; mutation requires
`--apply`:

```sh
uv run --project v25 --frozen python v25/download_samples.py assign-existing \
  --manifest /absolute/archive/manifest.sqlite \
  --archive-root /absolute/archive --source example --camera camera-a \
  --limit 20 --calibration-registry camera-calibrations/registry.jsonl \
  --installation-assignments camera-calibrations/assignments.jsonl \
  --camera-orientation detector_native_top_left_xy_right_y_down
```

Solve an assigned image by checksum through the registry:

```sh
./go25.sh /absolute/archive/example.fits \
  --calibration-registry camera-calibrations/registry.jsonl \
  --installation-assignments camera-calibrations/assignments.jsonl
```

`--allow-unconfigured-visible-sky` is valid only with the complete automatic
option set and permits fallback only when the source checksum has no assignment.
Corrupt, conflicting, missing, or identity-mismatched calibration data remains
fatal. The explicit `--visible-sky-mask-manifest` plus
`--camera-installation-id` pair remains available for operator-declared local
images and cannot be combined with automatic resolution.

## Reproduce a cold-start calibration test

`scripts/replay_visible_sky_cold_start.py propose` selects complete observing
dates before calibration, seals the proposal without an approved reference,
and reserves at least one fifth of dates. After sealing, `evaluate` processes
the held-out frames and reveals an approved reference. The optional
`audit-held-out` command runs production point-source detection on every
held-out original and records each measured source coordinate, support box,
and whether that support is visible, crosses the proposed boundary, or is
excluded. Interrupted audits resume from their validated JSONL prefix.

The native MMTO replay used 3,194 verified FITS originals across 116 dates. Its
669 held-out frames contained 380,048 unmasked detections: 10,539 source
supports intersected the proposed boundary and 3,410 were wholly excluded.
These figures validate the generic machinery on MMTO only; they do not claim a
successful calibration for another camera installation.

Peter visually accepted the sealed MMTO boundary on 2026-11-16. The immutable
acceptance receipt is `examples/mmto/cold_start_regression_acceptance.json`.
The corresponding sealed proposal mask is preserved as
`examples/mmto/cold_start_candidate_mask.png`, so the test suite recomputes the
comparison metrics from the two binary masks instead of trusting metric values
copied into the receipt. Enforce the fixed receipt on any newly generated
comparison with:

```sh
uv run --project v25 --frozen python v25/scripts/replay_visible_sky_cold_start.py \
  check-acceptance --comparison /path/to/cold-start/comparison.json
```

The command exits nonzero when any fixed limit fails or when the receipt,
approved-reference identity, evidence hashes, or proposal seal are invalid.
It fixes these conservative regression limits: exact agreement at least 0.98,
mask IoU at least 0.97, false-visible fraction at most 0.015, false-excluded
fraction at most 0.005, mean boundary separation at most 6.5 pixels, and p95
boundary separation at most 16 pixels. These limits were selected only after
the sealed comparison and must not be relaxed to conceal a later regression.

## Aperture-radius benchmark

Run `./run_v25_aperture_radius_benchmark.sh --help`. It compares fixed and
blob-scaled apertures, then fixed and blob-scaled sky annuli, using held-out
nights and a single shared R/G/B acceptance rule.

## Routine MMTO processing

Run the incremental MMTO queue from the repository root with:

```sh
./go_mmto_photometry_v25.sh
```

V25 first requests the current MMTO observing-night directory and then any
intervening recent nights not completed since the previous invocation. New
images therefore cannot be hidden by a skipped daily run. It inherits the
durable v24 backward cursor on its first invocation, then maintains its own v25
state. V23 and v24 receipts suppress duplicate acquisition work, while only a
successful v25 solve using the approved MMTO mask completes v25 processing, so a
version upgrade does not replay the completed November-to-September queue.
After the recent-night check, selection continues from the inherited historical
cursor. Selection stops as soon as the default total 40-image cap is full.
Change the cap with:

```sh
./go_mmto_photometry_v25.sh --max-images 12
```

The pipeline solves four images concurrently by default. Override the bound
with `--solver-workers N`; use `--solver-workers 1` for serial execution. Each
worker uses one BLAS/OpenMP thread, a unique run directory, and the existing
atomic SQLite append. Routine batch solves use the bundled display-name cache
offline, so unavailable SIMBAD service cannot delay numerical processing.

A v23 or v24 solver receipt for an image SHA-256 counts as completed acquisition
work, including a recorded scientific failure. A v25 receipt counts only when
the solve succeeded with the approved MMTO installation mask; failed, unmasked,
or differently masked v25 attempts remain pending. The v25 receipt remains the
only record of a masked v25 solve; historical masked reprocessing is a separate,
explicit operation. The historical cursor, latest current-night marker and
pending recent-night queue are stored beside `stars.sqlite`; before the first
v25 state is written, these values are inherited from
`mmto-v24-backfill-state.json`. They advance only after the selected batch has
receipts and remain unchanged after a dry run, transfer failure, or solver
failure without a receipt. A later derived-product failure does not undo
completed image work. The default oldest night is 2026-06-30; moving earlier
requires an explicit `--oldest-night YYYY-MM-DD`.

V25 runs planet photometry through `v25/plot_ALL_planets_v25.sh`. The wrapper
retries only transient JPL Horizons connection, read, and retryable HTTP
failures, up to four total attempts with bounded exponential delays. Each
failed attempt remains beside the requested output as
`planet-photometry-failed-attempt-N`; non-network and malformed-response
failures stop immediately. A retry starts with the requested
`planet-photometry/` path clear, so successful products retain the correct
absolute output paths in their provenance.

The R, G and B planet products are generated in one Python process. Each
source FITS is checksum-verified and decoded once for the three empirical
uncertainty calculations, and one shared distance lookup feeds the unchanged
per-channel CSV and PDF outputs.

Before every solve, the recognised MMTO FITS header is checked and its exposure
start, duration and midpoint are stored in the existing download manifest's
`mmto_v25_observations` table. Header contradictions are fatal. The filename is
not a clock, and the archive-listing timestamp remains discovery provenance
only. The solve command includes `--blind-planets` and receives no observation
time or site coordinates.

The existing `results/stars.sqlite` and
`raw_allsky_samples/manifest.sqlite` files are reused append-only. V25 does not
copy either database. Runs are distinguished by solver version `0.25.0`, while
the header-observation sidecar is keyed by the verified source SHA-256.

Post-processing adds these v25 directories below each pipeline output:

- `nightly-extinction-v25/` fits
  `m(s,i) = a_s + k X(s,i) + Z_i` independently by night and channel, with
  `sum_i Z_i = 0`. The soft-L1 fit retains fixed sample membership and rejects
  deficient airmass leverage rather than reporting a confounded slope. Its
  numerical solve uses the exact sparse Jacobian with LSMR and computes the
  `k`/`Z_i` covariance through the algebraically equivalent star-intercept
  Schur complement. This preserves the model and measurements while avoiding
  dense-SVD failures for production nights containing thousands of stars.
- `same-sidereal-transmission/` pairs distinct nights one-to-one by apparent
  sidereal time. Maps plot actual measured centroids only; sparse comparisons
  are marked insufficient and never interpolated. The saved manifest retains
  every map path. Routine stage output and the final figure listing report only
  the map count and directory, rather than enumerating every map path.
- `known-site-time-validation/` reveals the MMTO header midpoint and site only
  after the blind products are fixed. It compares zenith, latitude, airmass,
  parallactic/refraction direction, stellar epoch and every saved blind planet
  candidate without altering or reranking candidates. Stellar coordinates are
  transformed as one vector per exposure. Fitted Julian-year epochs are treated
  as TDB for this post-fit comparison, so old blind estimates do not invoke an
  extrapolated UTC leap-second conversion.
- `differential-photometry/` compares a local stellar ensemble, random forest,
  gradient boosting, and a small neural network on rows jointly held out by
  night and star identity, with measured injected-signal recovery. Its input
  run IDs come from the fresh cumulative `nightly-extinction/` sidecar made in
  the same invocation, rather than an immutable legacy population. The loader
  combines the v21, v23, v24, and v25 FITS-header observation tables and fails on any
  conflicting observation metadata. The planet PDF includes every accumulated
  identity, and the injected-signal PDF draws every finite measured recovery
  row while reporting both finite and total counts; neither display silently
  truncates its population.
  The simplest passing method receives one final pseudo-planet test. Failed
  scientific gates are reported normally and publish no corrected planet value;
  they are not pipeline crashes.

The legacy nightly-extinction products are still generated for compatibility
with inherited variable-star and planet plots. The new grey-corrected table
uses `m_corrected = m_machine - k X - Z_i` and is separately auditable.

The pipeline saves `acquisition_timeline.pdf` and `acquisition_timeline.csv`
immediately after its image-processing pass. They show which MMTO observing
nights were processed in this invocation, whether each image was downloaded
or reused, and whether its v25 solve succeeded. The PDF also shows the current
night and backward cursor. These files remain available if a later plotting
stage fails; the pipeline prints their path in that case. This report does not
change image selection or numerical analysis.

Run `./remind_me.sh` from the repository to list the newest available v25
PDF, PNG, SVG, and JPEG plots. It labels plots from an earlier run when the
latest run stopped before producing them. The run summary and acquisition
timeline appear first, so older fallback figures are not mistaken for current
results.

V25 replaces the inherited chronological variable-star PDF with
`variable-stars/variable_star_phase_curves.pdf`. Each panel phase-folds one
confirmed VSX object into `[0,1)` using its catalogue period and its earliest
plotted UTC as phase zero. Each R, G, or B point is the flux-space average of
all qualifying measurements for that object, observing night, and channel.
Individual measurements first use the nightly stellar correction

```text
m_corrected = m_machine - k_night,channel X
```

The nightly value is `-2.5 log10(mean(10^(-0.4 m_corrected)))`. No distance
correction or catalogue zero-point shift is applied. Phase folding changes only
the plotted horizontal coordinate; it does not change any measured or corrected
magnitude. The default selection is strictly `5 < period < 30` days and
catalogue magnitude `< 5.0`. It starts at `2026-06-30T00:00:00Z`, excluding the
isolated March datum only from this added product. Change these controls with
`--variable-min-period-days`, `--variable-max-period-days`,
`--variable-max-catalogue-magnitude`, and `--variable-start-utc`. VSX
associations are read from the frozen v25 file; routine plotting is offline.

Each channel with at least three independent nightly phases also receives an
unweighted sinusoidal least-squares fit in magnitude space. The VSX period is
held fixed while the mean magnitude, semi-amplitude, and phase are fitted. The
reported phase is the brightest-light phase in `[0,1)` under the same
earliest-plotted-UTC convention. Solid same-colour curves and phase labels
appear in the PDF; exact parameters and explicit non-fit statuses are in
`variable-stars/variable_star_sine_fits.csv`.

## Outputs

Each successful run contains a PDF report, machine-readable JSON and CSV
tables, measured-source photometry, association residuals and a FITS astrometric
solution. The persistent `stars.sqlite` database in the chosen results directory
collects available measurements across runs.

`lunar_evidence.json` records the image-level bright resolved-Moon classification
and the above/below-horizon audit for retained dates. Planet-search performance
also records how many positional visits the combined celestial gate rejected
before exact ephemeris refinement.

Photometry preserves raw aperture counts and, when exposure time is available,
also reports count rates in ADU/s. Instrumental magnitudes are derived from
count rates; they are not calibrated apparent magnitudes. Saturated measurements
are labelled and retained rather than silently discarded.

## Scientific interpretation

The stellar camera fit is blind: time and site metadata are withheld until the
measured stellar solution is fixed. Catalogue association and robust fitting are
performed in angular sky coordinates using the refraction-aware Barghini model,
and saved coordinates receive the same selected correction. Unsupported
refraction candidates become exact zero rather than being forced into the
result. Plots show measured centroids
and model predictions without cosmetic displacement.

Planet inference remains a secondary blind result in the automated MMTO path.
The known FITS midpoint is compared with all saved candidates only after the
solve. That comparison never changes candidate order, associations or the
fitted astrometry. A common planetary epoch is useful evidence from detected
sources, but sparse or ambiguous detections can leave it weakly constrained.

Moon corroboration is separate from the point-source fit. The image is classified
once. A possible Moon must be unidentified, at least 0.5 degrees across its
minor axis, at least 5 degrees above the derived horizon, and either saturated
or have peak SNR at least 25. After the cheap interpolated planet proposal, the
proposal date and image-derived zenith supply a metadata-free topocentric lunar
altitude. Observed and predicted Moon presence must agree when the prediction is
outside the plus/minus 5-degree horizon guard. Phase and positional coincidence
do not enter this deliberately simple gate. Sun and Moon compatibility are
combined before exact planet ephemerides and before joint camera/epoch fitting.

The photometric-zenith constraint is image-derived. It is not replaced by a
site- or time-derived airmass calculation.

## Licence and citation

The program source is Copyright (c) 2026 Peter Thejll and Chris Flynn and is
licensed under BSD 3-Clause. Modified versions may be developed and distributed
provided the licence conditions and original attribution are retained.

For scientific use, cite the software using [CITATION.cff](CITATION.cff) and
also cite [Barghini et al. (2019)](https://doi.org/10.1051/0004-6361/201935580)
for the camera model.

## Data and image credits

Catalogue and dependency provenance is recorded in [NOTICE.md](NOTICE.md) and
the `data/` documentation. The Gaia catalogue is derived from public Gaia DR3
data from ESA and DPAC; the bright-star supplement derives from Tycho-2 and
Hipparcos.

The curated release includes the permitted MMTO example only. A separate
photograph by Fred Espenak that was used during historical development is
credited to him but is **not included** in this release.

## Known limitations

- Extremely distorted, clouded or poorly exposed frames may not yield a blind
  pattern match.
- Planet identifications depend on a measured point source and can be ambiguous
  near catalogue stars; nondetections remain nondetections.
- Instrumental magnitudes are suitable for relative analysis but are not a
  substitute for a calibrated photometric system.
- The bundled catalogue and ephemeris tables cover their documented ranges;
  consult the data provenance before extrapolating beyond them.

Detailed numerical behaviour and remaining limitations are documented under
`docs/` in the full source repository.
