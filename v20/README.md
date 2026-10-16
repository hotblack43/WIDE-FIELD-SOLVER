# Wide-Field Solver v0.20.0

V20 is based directly on frozen v19. It retains the complete v19 photometry and
variable-star workflow and adds bounded, resumable backward MMTO acquisition.

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
uv sync --project v20 --frozen
./v20/demo.sh --output v20/results/mmto-demo-v20
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

Pass one or more input files to the v0.20 launcher:

```sh
./go20.sh /full/path/to/image.fits.bz2
./go20.sh first.fits second.cr2 --results-dir /full/path/to/results
```

By default, output goes to `results/` beside the release. Use `--results-dir`
to select a different location. Inputs are processed sequentially; a failed
image keeps its diagnostic output and does not prevent later inputs from being
attempted.

## Supported inputs

Supported inputs include compressed and uncompressed FITS, Canon CR2, and
native-depth PNG and TIFF images. Colour FITS may contain RGB or `R/G1/G2/B`
planes in common plane-first, plane-last or named-extension layouts. Use
`./go20.sh --help` for FITS HDU, channel-order, saturation and observation-time
options.

## Routine MMTO processing

Run the incremental MMTO queue from the repository root with:

```sh
./go_mmto_photometry_v20.sh
```

V20 first selects verified local MMTO images lacking any solver receipt. It
then requests one MMTO observing-night directory at a time: the current night
first, followed by a durable newest-to-oldest cursor. Discovery stops as soon
as the default 40-image cap is full, so it never inventories the complete
historical archive merely to discard most entries. Change the cap with:

```sh
./go_mmto_photometry_v20.sh --max-images 12
```

Any solver receipt for an image SHA-256 counts as completed work, irrespective
of solver generation or scientific success. Downloads without receipts remain
eligible. The cursor is stored beside `stars.sqlite`, advances only after the
selected batch has receipts, and remains unchanged after a dry run, transfer
failure, or solver failure without a receipt. A later derived-product failure
does not undo completed image work. The default oldest night is 2026-06-30;
moving earlier requires an explicit `--oldest-night YYYY-MM-DD`.

V20 runs every v19 plotting stage, including
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
associations are read from the frozen v20 file; routine plotting is offline.

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

Planet validation is a separate stage. If trustworthy observation-time metadata
is supplied, planet positions may be checked at that time and are explicitly
reported as metadata-conditioned. With no usable time, the solver can perform a
broader blind epoch search. A common planetary epoch is evidence from the
detected sources, not a replacement for reliable observation metadata, and
sparse or ambiguous planet detections can leave the epoch weakly constrained.

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
