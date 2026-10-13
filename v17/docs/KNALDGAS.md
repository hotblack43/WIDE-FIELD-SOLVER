# KNALDGAS linear-RGB workflow

V17 consumes the inspectable FITS products made from the KNALDGAS Canon CR2
and CR3 originals. RAW conversion is deliberately separate from solving. The
converter keeps exposures of one second or longer and writes no retained TIFF
or PPM intermediates.

The accepted primary HDU is a plane-first signed 16-bit `R,G,B` cube. The
header records `ORIGIN=KNALDGAS`, `CHANNELS=R,G,B`,
`COLSPACE=LINEAR_SRGB`, `TRANSFER=LINEAR`, `GAMMA=1`, `PHOTLINE=T`, the
1,870-ADU pedestal, exposure and camera provenance. Those stored samples are
linear science data.

## Run selected images

From the repository root, solve one image:

```sh
./go17.sh /media/pth/Sandisk8TB/KNALDGAS/FITS_RGB_MMTO/R6m2/example_RGB.fits.bz2 \
  --results-dir /media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17
```

Or designate several files, including a quoted wildcard:

```sh
./go_fits_v17.sh \
  '/media/pth/Sandisk8TB/KNALDGAS/FITS_RGB_MMTO/R6m2/*_RGB.fits.bz2' \
  --results-dir /media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17
```

The launcher expands and validates every input before starting. A missing
file, unsupported suffix or wildcard with no matches rejects the whole batch.

For each successful image, the selected results directory receives three
ordinary, root-level files whose names start with the searchable input-image
name and end in `__report.pdf`, `__solution.fits`, and
`__solution_annotated.fits`. These are ordinary copies of the same bytes
retained in the detailed `runs/` record; they are not stretched or resampled.
Copies are used because the KNALDGAS exFAT destination does not support hard
links. Repeated analyses receive distinct run identifiers and do not overwrite
earlier products.

## Linear science and rich display

Detection and centroiding use one linear image:

```text
L = 0.2126 R + 0.7152 G + 0.0722 B
```

The resulting measured centroid drives blind catalogue association and the
Barghini fit. Once those coordinates are fixed, aperture photometry is made
independently on the unchanged native R, G and B planes, with per-channel
background and saturation handling. Broad or saturated sources retain their
quality flags and measurements.

Only report rendering applies a gamma display transform. The PDF and sky
overlay identify this explicitly as a display-only stretch; it never enters
detection, centroiding, association, astrometry or photometry.

Every catalogue association is marked at its measured detector coordinate.
At most 40 stars also receive text labels. Labels are selected after the fit in
Bayer rounds—alpha first, then beta, gamma and later Greek letters—with
catalogue magnitude ordering inside each round. Ordinary named or Flamsteed
stars fill remaining slots. Unresolved Gaia numbers are not printed.
