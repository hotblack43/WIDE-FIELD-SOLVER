# Wide-Field Solver v0.22.0

V22 is based directly on frozen v21. It retains the complete bounded MMTO
workflow and adds FITS-header-timed reprocessing plus separate post-fit MMTO
site/time validation.

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

## Quick start

The release requires Bash and uses [uv](https://docs.astral.sh/uv/) to install
its pinned Python environment. From the repository root, run:

```sh
uv sync --project v22 --frozen
./v22/demo.sh --output v22/results/mmto-demo-v22
```

The first command may require an Internet connection to obtain Python packages.
The demonstration solve itself uses the catalogue and solver data included in
the release and is invoked with `--offline`; it makes no catalogue-name network
request.

## Built-in MMTO example

The demonstration analyses a native three-colour FITS observation from the MMT
Observatory all-sky camera. Use a fresh output name for every run. A successful
run prints its output location and verifies the result against conservative
scientific thresholds recorded with the example.

The image credit and its permission boundary are stated in [NOTICE.md](NOTICE.md).
In short: MMTO all-sky-camera image courtesy of MMT Observatory, provided with
permission from Tim Pickering. That permission is separate from the software
licence.

## Solve your own image

Pass one or more input files to the v0.22 launcher:

```sh
./go22.sh /full/path/to/image.fits.bz2
./go22.sh first.fits second.cr2 --results-dir /full/path/to/results
```

By default, output goes to `results/` beside the release. Use `--results-dir`
to select a different location. Inputs are processed sequentially; a failed
image keeps its diagnostic output and does not prevent later inputs from being
attempted.

## Supported inputs

Supported inputs include compressed and uncompressed FITS, Canon CR2, and
native-depth PNG and TIFF images. Colour FITS may contain RGB or `R/G1/G2/B`
planes in common plane-first, plane-last or named-extension layouts. Use
`./go22.sh --help` for FITS HDU, channel-order, saturation and observation-time
options.

## Routine MMTO processing

Run the incremental MMTO queue from the repository root with:

```sh
./go_mmto_photometry_v22.sh
```

V22 first requests the current MMTO observing-night directory and then any
intervening recent nights not completed since the previous invocation. New
images therefore cannot be hidden by a full local backlog or by a skipped daily
run. It then fills the remaining capacity with verified local images lacking a
v22 solver receipt before continuing a durable newest-to-oldest historical
cursor. An incomplete recent night remains ahead of historical work for the
next invocation. Selection stops as soon as the default total 40-image cap is
full. Change the cap with:

```sh
./go_mmto_photometry_v22.sh --max-images 12
```

Any v22 solver receipt for an image SHA-256 counts as completed v22 work,
including a recorded scientific failure. Earlier-version receipts remain
preserved but do not suppress v22 reprocessing. Downloads without v22 receipts
remain eligible. The historical cursor, latest current-night marker and pending
recent-night queue are stored beside `stars.sqlite`; they advance only after the
selected batch has receipts. They remain unchanged after a dry run, transfer
failure, or solver failure without a receipt. A later derived-product failure
does not undo completed image work. The default oldest night is 2026-06-30;
moving earlier requires an explicit `--oldest-night YYYY-MM-DD`.

V22 runs planet photometry through `v22/plot_ALL_planets_v22.sh`. The wrapper
retries only transient JPL Horizons connection, read, and retryable HTTP
failures, up to four total attempts with bounded exponential delays. Each
failed attempt remains beside the requested output as
`planet-photometry-failed-attempt-N`; non-network and malformed-response
failures stop immediately. A retry starts with the requested
`planet-photometry/` path clear, so successful products retain the correct
absolute output paths in their provenance.

Before every solve, the recognised MMTO FITS header is checked and its exposure
start, duration and midpoint are stored in the existing download manifest's
`mmto_v22_observations` table. Header contradictions are fatal. The filename is
not a clock, and the archive-listing timestamp remains discovery provenance
only. The solve command includes `--blind-planets` and receives no observation
time or site coordinates.

The existing `results/stars.sqlite` and
`raw_allsky_samples/manifest.sqlite` files are reused append-only. V22 does not
copy either database. Runs are distinguished by solver version `0.22.0`, while
the header-observation sidecar is keyed by the verified source SHA-256.

Post-processing adds these v22 directories below each pipeline output:

- `nightly-extinction-v22/` fits
  `m(s,i) = a_s + k X(s,i) + Z_i` independently by night and channel, with
  `sum_i Z_i = 0`. The soft-L1 fit retains fixed sample membership and rejects
  deficient airmass leverage rather than reporting a confounded slope. Its
  numerical solve uses the exact sparse Jacobian with LSMR and computes the
  `k`/`Z_i` covariance through the algebraically equivalent star-intercept
  Schur complement. This preserves the model and measurements while avoiding
  dense-SVD failures for production nights containing thousands of stars.
- `same-sidereal-transmission/` pairs distinct nights one-to-one by apparent
  sidereal time. Maps plot actual measured centroids only; sparse comparisons
  are marked insufficient and never interpolated.
- `known-site-time-validation/` reveals the MMTO header midpoint and site only
  after the blind products are fixed. It compares zenith, latitude, airmass,
  parallactic/refraction direction, stellar epoch and every saved blind planet
  candidate without altering or reranking candidates.
- `differential-photometry/` compares a local stellar ensemble, random forest,
  gradient boosting, and a small neural network on held-out nights and stars.
  The simplest passing method receives one final pseudo-planet test. Failed
  scientific gates are reported normally and publish no corrected planet value;
  they are not pipeline crashes.

The legacy nightly-extinction products are still generated for compatibility
with inherited variable-star and planet plots. The new grey-corrected table
uses `m_corrected = m_machine - k X - Z_i` and is separately auditable.

V22 runs every v19 plotting stage, including
`variable-stars/variable_star_time_series.pdf`. Each panel is a chronological
UTC time series for one confirmed VSX object. Each R, G, or B point is the
flux-space average of all qualifying measurements for that object, observing
night, and channel. Individual measurements first use the nightly stellar
correction

```text
m_corrected = m_machine - k_night,channel X
```

The nightly value is `-2.5 log10(mean(10^(-0.4 m_corrected)))`. No distance
correction, catalogue zero-point shift, or phase folding is applied. The
default selection is strictly `5 < period < 30` days and catalogue magnitude
`< 5.0`. It starts at `2026-06-30T00:00:00Z`, excluding the isolated March
datum only from this added product. Change these controls with
`--variable-min-period-days`, `--variable-max-period-days`,
`--variable-max-catalogue-magnitude`, and `--variable-start-utc`. VSX
associations are read from the frozen v22 file; routine plotting is offline.

Each channel with at least three independent nightly phases also receives an
unweighted sinusoidal least-squares fit in magnitude space. The VSX period is
held fixed while the mean magnitude, semi-amplitude, and phase are fitted. The
reported phase is the brightest-light phase in `[0,1)`, measured after the
earliest plotted nightly UTC for that star. Solid same-colour curves and phase
labels appear in the PDF; exact parameters and explicit non-fit statuses are in
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
