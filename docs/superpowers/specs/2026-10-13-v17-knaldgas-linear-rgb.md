# V17 KNALDGAS Linear-RGB Solver Design

## Objective

Version 17 is the numbered, independent KNALDGAS runtime. It accepts the
linear three-plane `R,G,B` FITS products derived from the KNALDGAS Canon
CR2/CR3 collection, solves them without using stretched pixels, and produces
a rich investigator-facing report whose labels make the bright identified
stars immediately recognisable.

Development uses versioned directories and launchers only. No Git branch or
worktree is part of this workflow.

## Version boundary

The current tested v16 runtime is frozen at the v17 boundary in
`docs/v16-runtime.json`. Its package, launchers, source manifest, results and
historical examples are not subsequently edited for v17 work.

V17 is a complete independent copy under `v17/`, with version `0.17.0`, its
own lockfile, catalogue, ephemeris data, documentation, tests and
`SOURCE_MANIFEST.json`. The public entry points are:

- `go17.sh`;
- `go_v0.17.0.sh`; and
- `go_fits_v17.sh` for one or more explicitly designated FITS files, including
  quoted wildcard patterns.

All launchers invoke only code and data under `v17/`. They never import the
v16 package at runtime. `go17.sh` and `go_fits_v17.sh` accept the KNALDGAS
linear `.fits` and `.fits.bz2` products directly. RAW conversion remains an
explicit preceding operation so the linear science FITS is preserved and
inspectable rather than hidden in a temporary solver step.

## KNALDGAS input and science path

The accepted KNALDGAS primary HDU is a plane-first signed 16-bit cube with
`CHANNELS=R,G,B`, `COLSPACE=LINEAR_SRGB`, `TRANSFER=LINEAR`, `GAMMA=1` and
`PHOTLINE=T`. The 1,870-ADU pedestal and camera/exposure provenance remain in
the header. V17 treats the stored samples as linear science data.

Detection and centroiding use the existing linear luminance projection

```text
L = 0.2126 R + 0.7152 G + 0.0722 B
```

The one measured centroid per source drives the blind astrometric association
and Barghini fit. After those coordinates are fixed, aperture photometry is
measured independently on the native linear R, G and B planes with per-channel
background and saturation handling. The report-only gamma rendering never
enters detection, centroiding, association, fitting or photometry.

## Bright-star annotation policy

The astrometric solution continues to use every associated source. Naming and
label selection happen only after the fit and remain display-only.

The sky overlay distinguishes association from annotation:

- every catalogue-associated star is shown with a small unobtrusive marker;
- at most 40 stars receive large marker rings and text labels;
- the legend and report state both totals, for example “542 identified; 40
  labelled”; and
- broad or saturated bright detections remain eligible for a label when their
  astrometric association passes the existing angular-residual gate.

Text labels are selected in Bayer rounds. All available alpha stars are
considered first, ordered by catalogue magnitude; then beta, then gamma, then
the remaining Greek letters in Bayer order. Numbered Bayer components retain
their component notation. Remaining slots are filled by other ordinary named
or Flamsteed stars in magnitude order. Unresolved long Gaia identifiers are
never printed. The existing post-layout collision solver retains every chosen
label, moves only text boxes and leaders, and never moves measured star
positions.

Alias lookup is limited to the bright, accurately associated display-candidate
pool. It uses the bundled/local cache first and may query SIMBAD only after the
blind solution is fixed. Lookup failure leaves the solution intact and falls
back to locally available ordinary designations.

## KNALDGAS documentation and outputs

V17 documentation explicitly names KNALDGAS in its README, feature status and
a dedicated `docs/KNALDGAS.md`. The document records the RAW-to-linear-FITS
provenance, one-second inclusive exposure selection, display-only rendering,
combined-image astrometry and per-plane photometry.

New validation results are written under
`/media/pth/Sandisk8TB/KNALDGAS/SOLVER_RESULTS_RGB_MMTO_V17/`. Existing v16
results and `/media/pth/Sandisk8TB/KNALDGAS/FITS_RGB_MMTO/` inputs are read-only
during v17 validation. No TIFF, PPM or nonlinear diagnostic FITS is retained.

## Verification

Tests are written before each production change and cover:

- the frozen v16 boundary and independent v17 package/launchers;
- direct and wildcard KNALDGAS FITS launching;
- alpha, beta, gamma and subsequent Bayer-round ordering;
- magnitude ordering within a Bayer round;
- eligibility of accurately associated broad bright sources;
- separate identified and labelled marker counts in the report;
- unchanged measured marker coordinates and collision-free text layout;
- unchanged linear samples during report rendering; and
- separate native R, G and B photometry at the shared measured centroids.

The representative 30-second KNALDGAS image is solved with both frozen v16 and
v17. V17 must retain the same astrometric associations and numerical residuals;
only display annotation may change. Completion also requires the full repository
unit suite, the root blind demo, the v17 demo, manifest checks, FITS checksum
checks and visual inspection of every regenerated PDF page.
