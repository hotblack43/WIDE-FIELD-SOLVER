# Wide-Field Solver v0.11.0

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
its pinned Python environment. From the unpacked release directory, run:

```sh
uv sync --project v11 --frozen
./demo.sh --output results/mmto-demo
```

The first command may require an Internet connection to obtain Python packages.
The demonstration solve itself uses the catalogue and solver data included in
the release and is invoked with `--offline`; it makes no catalogue-name network
request.

## Built-in MMTO example

The demonstration analyses a native three-colour FITS observation from the MMT
Observatory all-sky camera. It overwrites its named output directory when run
again, so repeated checks do not accumulate temporary result trees. A successful
run prints its output location and verifies the result against conservative
scientific thresholds recorded with the example.

The image credit and its permission boundary are stated in [NOTICE.md](NOTICE.md).
In short: MMTO all-sky-camera image courtesy of MMT Observatory, provided with
permission from Tim Pickering. That permission is separate from the software
licence.

## Solve your own image

Pass one or more input files to the v0.11 launcher:

```sh
./go11.sh /full/path/to/image.fits.bz2
./go11.sh first.fits second.cr2 --results-dir /full/path/to/results
```

By default, output goes to `results/` beside the release. Use `--results-dir`
to select a different location. Inputs are processed sequentially; a failed
image keeps its diagnostic output and does not prevent later inputs from being
attempted.

## Supported inputs

Supported inputs include compressed and uncompressed FITS, Canon CR2, and
native-depth PNG and TIFF images. Colour FITS may contain RGB or `R/G1/G2/B`
planes in common plane-first, plane-last or named-extension layouts. Use
`./go11.sh --help` for FITS HDU, channel-order, saturation and observation-time
options.

## Outputs

Each successful run contains a PDF report, machine-readable JSON and CSV
tables, measured-source photometry, association residuals and a FITS astrometric
solution. The persistent `stars.sqlite` database in the chosen results directory
collects available measurements across runs.

Photometry preserves raw aperture counts and, when exposure time is available,
also reports count rates in ADU/s. Instrumental magnitudes are derived from
count rates; they are not calibrated apparent magnitudes. Saturated measurements
are labelled and retained rather than silently discarded.

## Scientific interpretation

The stellar camera fit is blind: time and site metadata are withheld until the
measured stellar solution is fixed. Catalogue association and robust fitting are
performed in angular sky coordinates using the Barghini model, and saved
coordinates receive the same fitted corrections. Plots show measured centroids
and model predictions without cosmetic displacement.

Planet validation is a separate stage. If trustworthy observation-time metadata
is supplied, planet positions may be checked at that time and are explicitly
reported as metadata-conditioned. With no usable time, the solver can perform a
broader blind epoch search. A common planetary epoch is evidence from the
detected sources, not a replacement for reliable observation metadata, and
sparse or ambiguous planet detections can leave the epoch weakly constrained.

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
