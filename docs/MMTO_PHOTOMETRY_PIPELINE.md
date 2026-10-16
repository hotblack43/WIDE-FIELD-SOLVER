# One-command MMTO processing and photometry

For current work, use `go_mmto_photometry_v20.sh`. It retains every v19 product
and processes a bounded backward batch without inventorying the complete MMTO
archive. The unversioned launcher remains the preserved v0.11.0 workflow.

V20 asks MMTO for one observing-night directory at a time. It first selects
already-downloaded images that lack any solver receipt, checks the current
night, then fills remaining capacity from a durable backward cursor. The
default hard cap is 40 selected images:

```sh
./go_mmto_photometry_v20.sh --dry-run
./go_mmto_photometry_v20.sh
./go_mmto_photometry_v20.sh --max-images 12
```

The default oldest night is `2026-06-30`. V20 and the automatic MMTO worker both
write the sole canonical database, `results/stars.sqlite`; historical automatic
analysis directories remain below `results/mmto-automatic/runs/` without a
second live database. Use `--oldest-night YYYY-MM-DD` only
when deliberately extending the walk farther back. Any receipt in the selected
`stars.sqlite` marks that SHA-256 as processed, including receipts from v16,
v17, v18, v19, v20, other solver generations, and scientific failures. A
verified download with no receipt remains eligible and is reused without a
second transfer.

On 2026-10-16 the former automatic database was losslessly merged into the
canonical file: 716 runs, 14,331 product references, and 2,868,193 measurement
references were imported. Verified pre-merge recovery copies are retained under
`/media/pth/Sandisk8TB/WIDE-FIELD-SOLVER-db-merge-20261016/`. The old
`results/mmto-automatic/stars.sqlite` path is intentionally absent; its
historical `runs/` directories remain preserved because receipt provenance
refers to them.

The cursor defaults to `RESULTS_DIR/mmto-v20-backfill-state.json`. It advances
only after every selected image has an existing or newly written receipt. Dry
runs, transfer failures, and solver failures without receipts do not advance
it. A later derived-product failure does not roll back already completed image
work. If the 40-image cap cuts through one night, that night remains the cursor
and the following invocation takes its next unfinished images. V20 never
calculates a complete remote backlog count.

The sections below describe the inherited photometry products in detail. V20
also retains v19's `variable-stars/variable_star_time_series.pdf` and its CSV
sidecars.

`go_mmto_photometry.sh` processes every verified downloaded MMTO image that
does not already have a v0.11.0 solver receipt, then regenerates the stellar and
planetary photometry products from the accumulated database.

Do not start it while an independently launched `go11.sh` or `goBIG` batch is
still running. The pipeline prevents two copies of itself from running at once,
but it cannot lock an unrelated hand-started solver process.

## Preview

From the repository root:

```sh
./go_mmto_photometry_v20.sh --dry-run
```

The preview reads `raw_allsky_samples/manifest.sqlite` and the selected
`stars.sqlite`, prints the cursor, bounded listing and selection counts, and
lists each selected image. It does not create a directory, run a solver, write
either database, download a file, or advance the cursor.

Use explicit locations when the archive or results live elsewhere:

```sh
./go_mmto_photometry_v20.sh --dry-run \
  --archive /path/to/raw_allsky_samples \
  --results-dir /path/to/solver-results
```

When `--results-dir` is omitted, the launcher follows the same choice as
`go20.sh`: `WFS_RESULTS_DIR`, then the host-specific results-directory setting,
then repository-local `results/`.

## Run

After any existing batch has finished:

```sh
./go_mmto_photometry_v20.sh
```

The processing stage:

1. selects unreceipted verified downloads before requesting remote listings;
2. lists only enough individual nights to fill the bounded image cap;
3. skips a source SHA-256 if `stars.sqlite` contains any solver receipt;
4. rechecks each selected file's path, size, and SHA-256 against the manifest;
5. downloads only selected files that are not reusable;
6. rechecks downloaded SHA-256 values against all solver receipts;
7. runs `go20.sh` sequentially for every remaining image; and
8. requires a matching v0.20.0 database receipt after every invocation.

A recorded scientific solve failure counts as processed and does not prevent
the remaining images or the later photometry stages from running. An
operational failure without a matching database receipt stops the pipeline.
Running the command again safely resumes from the receipts already stored.

V20 downloads only selected manifest gaps after the bounded plan is fixed.

## Products

The default output is a new UTC-stamped directory:

```text
RESULTS_DIR/photometry-runs/v20-YYYYMMDDTHHMMSSZ/
├── pipeline.log
├── pipeline_summary.json
├── stellar-lightcurves/
├── nightly-extinction/
├── variable-stars/
├── planet-photometry/
│   ├── planet_colour_colour.png
│   ├── planet_colour_colour.csv
│   ├── R/
│   ├── G/
│   └── B/
└── planet-empirical-extinction/
    ├── R/
    ├── G/
    └── B/
```

The stages run in that order. `stellar-lightcurves/` contains the instrumental
stellar repeatability products. `nightly-extinction/` is the read-only,
stellar-only extinction sidecar. For each night and R/G/B band it jointly fits
one intercept per star and one robust extinction slope shared by all stars:
`m_machine(s,i) = a_s + k X(s,i)`. `nightly_shared_slope_fits.csv` records the
shared slope, uncertainty, RMS, counts, robust-loss settings, and airmass
leverage; `nightly_star_intercepts.csv` records the fitted stellar intercepts.
`planet-photometry/` first subtracts the applicable `k X_planet` from every raw
planet magnitude, then normalizes the result to unit Sun--planet and
Earth--planet distances using
`m_1,1 = m_raw - k X_planet - 5 log10(r_sun-planet r_earth-planet)`. It contains
two all-night extinction- and distance-corrected plots per band: one against
UTC and one with all nights overlaid against hours past 12:00 Arizona local
time. Lines in the latter join points only within the same planet/night/camera
sequence. Its companion
`planet_extinction_corrected_distance_nightly_slopes.csv` quantifies the
remaining within-night slopes for groups with at least four measurements. No
zero point or colour term is applied.

After all three bands have been written, the planet stage exactly joins R, G,
and B rows from the same image, planet, and detection. It plots `B-G` against
`B-R` in one combined, data-scaled colour--colour diagram. Planet identity is
encoded by marker shape and hours since the latest Arizona local noon by marker
colour. Both indices use `extinction_corrected_distance_magnitude`; raw or
extinction-only magnitudes are not substituted when a corrected band is
missing. The companion CSV records the three corrected magnitudes and both
indices. Existing per-band products retain their established PDF format; the
new single-page colour--colour diagram is written only as PNG.

Choose a new explicit output directory when required:

```sh
./go_mmto_photometry_v20.sh \
  --archive /path/to/raw_allsky_samples \
  --results-dir /path/to/solver-results \
  --output /path/to/new-photometry-run
```

In v16, `planet-empirical-extinction/` fits each planet/night/channel/camera
sequence independently using only planet measurements. Accepted sequences need
at least 10 retained points, at least 0.5 airmass span, and airmass no greater
than 5. The fitted quantity is explicitly named
`planet_empirical_extinction_coefficient_mag_per_airmass`; the correction is
referenced to airmass 1.0. Each band contains the before/after airmass PDF, the
extinction- and distance-corrected magnitude versus hours since Arizona local
noon PDF, and
`planet_nightly_empirical_extinction_coefficients.csv`.

The v16 stage stores one immutable generation in the shared `stars.sqlite`
database. The rows are in
`planet_nightly_empirical_extinction_coefficients`; the convenient read views
are `latest_planet_nightly_empirical_extinction_coefficients` and
`latest_accepted_planet_empirical_extinction_coefficients`. Rejected fits remain
auditable and a newer rejected fit prevents an older accepted row from being
presented as current.

The stage first creates `input_manifest_snapshot.sqlite` with SQLite's backup
API. R, G, and B all read that same standalone snapshot, and its exact path and
SHA-256 are retained in the output summary and database generation.

Existing output paths are refused, including empty directories, so historical
products cannot be overwritten. The legacy stellar coefficient sidecar remains
read-only; only the explicitly named v16 planet empirical coefficients are
added to `stars.sqlite`.

`pipeline_summary.json` records selection and processing counts, each stage's
exit status, paths, timestamps, and any operational failure. `pipeline.log`
contains the invoked commands and their combined output. After successful
completion the launcher prints `FIGURES (N)` followed by the absolute path of
every PDF or PNG actually present below that run directory. CSV, JSON, log and
working files are deliberately omitted from this operator-facing figure list.
