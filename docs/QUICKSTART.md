# Quick start

## Requirements

- Linux or another Unix-like system with Bash
- Git
- [`uv`](https://docs.astral.sh/uv/)
- enough free space for the image, dependencies and generated report products

Python 3.12 and the solver dependencies are selected from the committed v0.9.0
lock file.

## Install

```bash
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
uv sync --project v9 --frozen
```

The first installation requires network access to obtain the pinned Python
packages. The Gaia catalogue and planetary proposal ephemeris used at runtime
are already included.

## Solve an image

```bash
./go9.sh /full/path/to/image.fits
```

Accepted inputs include monochrome or RGB PNG/TIFF, ordinary FITS and
losslessly compressed `.fits.bz2` files. Multi-plane FITS files may contain
RGB or R/G1/G2/B channels.

```bash
./go9.sh /full/path/to/image.fits.bz2
```

Paths containing spaces must be quoted. Every invocation creates a unique run
directory and prints its location before computation begins.

## Ambiguous FITS files

Most FITS files need no extra arguments. When the file does not identify its
science HDU, channel order or saturation value, provide them explicitly:

```bash
./go9.sh image.fits \
  --fits-hdu SCI \
  --channel-order RG1G2B \
  --saturation-level R=4095,G1=4095,G2=4095,B=4095
```

These options describe input storage only; they do not supply a sky position,
orientation or astrometric solution.

## Planet-search mode

The normal v0.9.0 path uses a FITS, EXIF or filename observation time only after
the stellar solution and image-derived constraints have been fixed. To suppress
that time and request the full blind planetary search, run:

```bash
./go9.sh image.fits --blind-planets
```

## Retaining results elsewhere

```bash
./go9.sh image.fits --results-dir /data/wide-field-results
```

The unique run folders and their shared `stars.sqlite` database remain together
under the selected directory.

## What to open first

At completion, open the printed `analysis/report.pdf`. Then consult
`result.json` for fitted values and status flags. A visually convincing overlay
does not by itself establish a unique epoch or physical zenith; read the status
labels in both products.
