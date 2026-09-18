# v9 Consolidation Design

## Goal

Create a self-contained v0.9.0 runtime that consolidates the complete v8/v8a
feature set without changing either preserved runtime.  The new runtime is
launched by `go9.sh` (and the pinned `go_v0.9.0.sh`) from an ordinary clone,
with no branch or worktree knowledge required.

## Version boundary

- Preserve `v8/`, `go8.sh`, and `go_v0.8.0.sh` byte for byte.
- Preserve `v8a/` and `go8a.sh` byte for byte as the independent work snapshot.
- Record checksums for both preserved packages and launchers.
- Base `v9/` on the complete tracked v8a package, including its catalogue,
  planet/minor-planet ephemerides, dependency lockfile, tests, and examples.
- Change package/version/launcher identity to v0.9.0 without importing runtime
  code or data from another project.

## Consolidated capabilities

V9 retains all v8/v8a behavior, notably native RGB/high-bit FITS input,
exposure-normalized instrumental count rates, Ceres/Vesta search and brightness
evidence, saturated-source astrometry, per-channel saturated-wing Moffat
diagnostics, exact supplied-time planet/source association, compressed FITS
input, portable results/database placement, and append-only measurement storage.

## Zenith presentation change

When the saved zenith projects to a valid detector position, draw the existing
red X at that exact position and retain its conditional/provisional source label
in the legend.  Do not add an on-image `Zenith (...)` annotation or its bounding
box.  This reveals nearby sources without altering the fitted position,
coordinates, status, caption, legend, or numerical products.  If no zenith is
available, the original image is unavailable, the vector is invalid, or the
projection is outside the image, retain the existing diagnostic notice.

## Evidence and documentation

Add a regression that observes the plotted Matplotlib objects: the red X must
remain at the expected coordinates, the legend must retain the zenith status,
and the axes must contain no marker-attached zenith annotation.  Add launcher,
version-boundary, manifest, complete unit-suite, and historical-demo checks.
Update the root guide, consolidation record, v9 feature status, and v9 source
manifest.  Numerical algorithms and regression thresholds remain unchanged.
