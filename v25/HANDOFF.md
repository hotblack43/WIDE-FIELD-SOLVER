# V25 handoff

## Interface correction recorded 2026-11-16

Peter's intended v25 boundary is deliberately small: retain the complete v24
operational workflow and CLI, then add automatic horizon-mask construction when
normal processing encounters a genuinely new camera installation. In
particular, `go_mmto_photometry_v25.sh` remains the routine command and keeps
the v24 options such as `--max-images`.

The current checkpoint contains a tested automatic mask engine and a separate
`go_visible_sky_v25.sh` operator, including bounded acquisition, held-out-date
validation, five-fold stability checks, content-addressed approval and
activation. That machinery is useful, but promoting the separate operator as
the normal interface was an overdesign. It is not yet integrated into the
routine v24-shaped pipeline, and `go_visible_sky_v25.sh --max-images N` is not a
valid command at this checkpoint.

The next v25 change should reuse, not discard, the mask engine while simplifying
the user path:

1. Normal acquisition and solving continue through
   `go_mmto_photometry_v25.sh`, with the same arguments and bounded archive
   behavior as v24.
2. A source matching an active compatible detector/installation mask uses that
   mask without recalibration as ordinary images accumulate.
3. A previously unseen detector/installation identity accumulates native
   images through the normal pipeline. Once the fixed evidence gates are met,
   the existing automatic engine builds, validates, registers and activates its
   horizon mask without a second routine command or manual identifiers.
4. The explicit operator and manual proposal/revision/approval commands remain
   advanced maintenance and recovery tools.
5. A physical camera replacement must not be hidden by reusing only the logical
   source/camera ID; detector signature and installation identity must decide
   whether an existing mask is compatible.

Do not describe the current standalone operator as the final v25 interface, and
do not freeze v25 until this integration has regression evidence. The approved
MMTO v24 mask and all historical runtimes remain preserved.

## Current MMTO runtime

Use `./go25.sh IMAGE` or `./go_v0.25.0.sh IMAGE` for the independent v25
runtime. Use `./go_mmto_photometry_v25.sh` to select at most 40 MMTO images
without v23/v24 acquisition progress or a successful masked v25 receipt, reuse
local files, download only selected gaps, analyse them, and regenerate inherited
and v25 post-fit products.
The original `go_mmto_photometry.sh` remains pinned to v11.

Image analysis uses four concurrent worker processes by default. Use
`--solver-workers N` to change that bound or `--solver-workers 1` for the prior
serial resource profile. Every worker remains internally single-threaded for
BLAS/OpenMP, writes a unique run directory and appends through the existing
atomic SQLite transaction. The batch runner invokes the pinned v25 interpreter
directly with `--offline`; this removes repeated shell/uv startup and
display-only SIMBAD network waits while retaining the bundled name cache.

The v25 queue never requests a multi-night historical listing. It checks the
current night and then continues from `RESULTS_DIR/mmto-v25-backfill-state.json`,
one night per remote request. If that file does not yet exist, it inherits
`RESULTS_DIR/mmto-v24-backfill-state.json`. A v23 or v24 receipt counts as done
acquisition work, including a recorded scientific failure. A v25 receipt counts
only when the solve succeeded with the approved MMTO installation mask; failed,
unmasked, or differently masked v25 attempts remain pending. Dry runs, transfer
failures, and solver failures without receipts do not advance the cursor; a
later product-stage failure does not undo completed image work. Use
`--max-images N` to change the 40-image cap and `--oldest-night` to move the
default 2026-06-30 floor deliberately.

The two existing databases are reused. V25 appends versioned runs to
`results/stars.sqlite` and adds `mmto_v25_observations` to
`raw_allsky_samples/manifest.sqlite`. Each selected file must pass recognised
MMTO header checks. The exposure midpoint is computed from header start plus
half the header duration; neither filename time nor discovery time is a
scientific fallback.

The automated solve is forced to use `--blind-planets` and is never given site
or time. Once the receipt and blind products are fixed, read-only stages write:

- `nightly-extinction-v25/image_grey_transparency.csv` and
  `grey_transparency.png` for constrained per-exposure `Z_i` terms;
- `same-sidereal-transmission/sidereal_pair_summary.csv`, measured-point CSVs,
  and non-interpolated map PNGs;
- `known-site-time-validation/mmto_site_time_validation.csv`, per-star airmass
  comparisons, secondary planet-candidate offsets and two validation PNGs.
- `differential-photometry/benchmark_summary.json`, four diagnostic PDFs, held-
  out metrics, and planet rows. A failed scientific gate exits successfully but
  sets `correction_available` false and leaves corrected magnitudes absent.

The differential benchmark reads the databases without writing them and uses
the fresh `nightly-extinction/` product from the same pipeline invocation as
its population and comparison control. That sidecar records the latest
successful run for every MMTO image in the accumulated database, so all four
diagnostic PDFs change as the database grows instead of replaying one legacy
v21 population. Held-out night/star roles remain mandatory for honest model
validation. Planet identities and finite injected-signal recovery rows are
plotted without hard-coded display caps, and non-finite recovery rows are
counted in the figure. The stage makes no network request.

The aperture benchmark is also read-only. Its 71-image test retained the v22
production geometry: aperture `clamp(2.5 * major_sigma, 3, 9)` and sky annulus
from aperture+3 through aperture+7 pixels. The larger 4-sigma aperture lowered
raw scatter but failed held-out residual-trend gates. Blob-scaled annuli did not
improve R, G and B together.

The historical `run_distributed_gobig.py` remote workflow is v11-specific. Do
not point it at v25 or the shared MMTO databases. Local verification and a dry
run are required before designing a separate Monster2 v25 dispatcher.

The variable product uses `m_corrected = m_machine - k_night,channel X` from
the nightly-extinction sidecar, then flux-averages all measurements by VSX
object, observing night, and native channel before converting the mean flux
back to magnitude. It is not distance corrected. The PDF phase-folds each star
into `[0,1)` with its published period and earliest plotted UTC as phase zero;
the folding changes only the plotted horizontal coordinate. The default
selection is the strict interval `5 < period < 30` days and catalogue magnitude
`< 5.0`; all three limits are adjustable with `--variable-min-period-days`,
`--variable-max-period-days`, and `--variable-max-catalogue-magnitude`. The
default UTC boundary is
`2026-06-30T00:00:00Z`, so the isolated March 2026 point is audited but not
plotted. The frozen local VSX association keeps runtime operation offline.

For each R/G/B channel, v25 fits the nightly points with the published period
held fixed. The unweighted magnitude-space model is
`m(phase) = mean - A cos(2 pi (phase - phase_brightest))`.
The common reference is the star's earliest plotted nightly UTC. The PDF draws
the fitted curves and labels the brightest-light phase; the fit CSV records the
phase in cycles and days, first brightest epoch, mean, semi-amplitude, RMS, and
fit status. Fewer than three points or fewer than three independent phases are
audited rather than fitted.

V15 combines the existing Sun check with a binary Moon-above/below-horizon check
after cheap interpolated planet proposals and before exact planet refinement.
Moon candidacy requires a bright resolved object: at least 0.5 degrees across,
at least 5 degrees above the image-derived horizon, and saturated or peak SNR
at least 25. Phase and positional coincidence do not enter the gate. The JSON
audits are retained; no all-candidate image overlay is generated.

# v8/v8a consolidation record

V9 was created on 2026-09-18 from the complete tracked v8a work snapshot after
that snapshot was safely fast-forwarded from GitHub. The parent v8 and v8a
runtimes were not edited. Their exact package and launcher bytes are recorded in
`../docs/v8-runtime.json` and `../docs/v8a-runtime.json`.

## Features consolidated in v9

- Native-depth monochrome, RGB, stacked FITS, TIFF and PNG input.
- Direct `.fits.bz2`, `.fit.bz2` and `.fts.bz2` input with metadata and
  compressed-source provenance.
- Exposure-normalized instrumental count rates when positive, consistent FITS
  or EXIF exposure metadata exists; raw aperture ADU remain available.
- Ceres and Vesta search and brightness evidence alongside the seven inherited
  major planets.
- Saturated and broad detections remain eligible for astrometry.
- Per-channel saturated aperture lower bounds plus separate robust masked
  Moffat-wing totals, count rates, centroids and fit-quality diagnostics.
- Exact supplied-time planet/source association, distinct from unmatched
  predicted planet positions and from blind epoch inference.
- Portable result/database location and append-only SQLite recording.

## V9 presentation change

The adopted extinction or geometric zenith is still plotted at its exact saved
detector coordinate as a red X. Its source and conditional/provisional status
remain in the legend, but the marker no longer has a large on-image text label.
Missing, invalid, off-image and unavailable-image notices are retained. This
does not alter the camera, source positions, fitted zenith, residuals, or any
other numerical product.

Use `./go9.sh IMAGE` or the pinned `./go_v0.9.0.sh IMAGE` from the repository
root. The package uses `v9/uv.lock` and does not depend on a development branch
or worktree.
