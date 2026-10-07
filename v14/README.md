# Wide-Field Solver v0.14.0

V14 preserves v13 integrated refraction and adds conservative, metadata-free
Moon corroboration for retained planet-date candidates. The Moon is predicted
topocentrically from each candidate date and the image-derived zenith; it is
never fitted as a point source or allowed to move measured coordinates.

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
uv sync --project v14 --frozen
./v14/demo.sh --output v14/results/mmto-demo-v14
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

Pass one or more input files to the v0.14 launcher:

```sh
./go14.sh /full/path/to/image.fits.bz2
./go14.sh first.fits second.cr2 --results-dir /full/path/to/results
```

By default, output goes to `results/` beside the release. Use `--results-dir`
to select a different location. Inputs are processed sequentially; a failed
image keeps its diagnostic output and does not prevent later inputs from being
attempted.

## Supported inputs

Supported inputs include compressed and uncompressed FITS, Canon CR2, and
native-depth PNG and TIFF images. Colour FITS may contain RGB or `R/G1/G2/B`
planes in common plane-first, plane-last or named-extension layouts. Use
`./go14.sh --help` for FITS HDU, channel-order, saturation and observation-time
options.

## Routine MMTO processing

Run the incremental MMTO queue from the repository root with:

```sh
./go_mmto_photometry_v14.sh
```

The routine queue uses night-level LIFO ordering: it selects the newest night
containing images without v14 receipts and processes only that night. Later
runs skip retained v14 receipts and work backward to the next-newest incomplete
night. A newly downloaded night takes priority on the following run. V11
receipts do not mark an image complete for v14, so spare capacity gradually
builds genuine v14 historical coverage without scheduling the whole archive as
one routine job. Whole-archive processing remains separate and explicit:

```sh
./go_mmto_photometry_v14.sh --backfill-v14
```

Use `--dry-run` first to inspect either queue without processing images or
writing products.

## Outputs

Each successful run contains a PDF report, machine-readable JSON and CSV
tables, measured-source photometry, association residuals and a FITS astrometric
solution. The persistent `stars.sqlite` database in the chosen results directory
collects available measurements across runs.

When planet-date candidates exist, `lunar_evidence.json` records the image-level
Moon classification and, for every date, its phase, altitude, derived observer
coordinates and the exact reason the date is rejected or retained.

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

Moon corroboration is separate from the point-source fit. Each candidate date
and the image-derived zenith imply a metadata-free observer latitude/longitude,
which supplies topocentric lunar parallax. Saturation alone is insufficient:
the measured minor-axis footprint must subtend at least the Moon's 0.5-degree
diameter. If no such resolved object is observed, dates predicting a Moon at
least 25% illuminated and at least 5 degrees above the derived horizon inside
the valid sky image are rejected. If a resolved Moon is observed, its measured
position must agree with the prediction. Ordinary saturated stars cannot
neutralise this constraint. Lunar-contradicted dates remain auditable but are
excluded before the expensive joint camera/epoch fitting stage.

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
