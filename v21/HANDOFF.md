# V21 MMTO header-time reprocessing handoff

Use `./go21.sh IMAGE` or `./go_v0.21.0.sh IMAGE` for the independent v21
runtime. Use `./go_mmto_photometry_v21.sh` to select at most 40 unfinished MMTO
images by default, download only selected gaps, analyse them, and regenerate
every v19 photometry and variable-star product.
The original `go_mmto_photometry.sh` remains pinned to v11.

The v21 queue never requests a multi-night historical listing. It drains
downloaded images without receipts first, checks the current night, and then
continues from `RESULTS_DIR/mmto-v21-backfill-state.json`, one night per remote
request. Any solver receipt counts as done, including earlier versions and
scientific failures. Dry runs, transfer failures, and solver failures without
receipts do not advance the cursor; a later product-stage failure does not undo
completed image work. Use `--max-images N` to change the 40-image cap and
`--oldest-night` to move the default 2026-06-30 floor deliberately.

The variable product uses `m_corrected = m_machine - k_night,channel X` from
the nightly-extinction sidecar, then flux-averages all measurements by VSX
object, observing night, and native channel before converting the mean flux
back to magnitude. It is not distance corrected or phase folded. The default
selection is the strict interval `5 < period < 30` days and catalogue magnitude
`< 5.0`; all three limits are adjustable with `--variable-min-period-days`,
`--variable-max-period-days`, and `--variable-max-catalogue-magnitude`. The
default UTC boundary is
`2026-06-30T00:00:00Z`, so the isolated March 2026 point is audited but not
plotted. The frozen local VSX association keeps runtime operation offline.

For each R/G/B channel, v21 fits the nightly points with the published period
held fixed. The unweighted magnitude-space model is
`m(t) = mean - A cos(2 pi ((t-reference)/period - phase_brightest))`.
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
