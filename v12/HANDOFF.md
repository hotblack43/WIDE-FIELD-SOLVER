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
