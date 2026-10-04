# One-command MMTO processing and photometry

`go_mmto_photometry.sh` processes every verified downloaded MMTO image that
does not already have a v0.11.0 solver receipt, then regenerates the stellar and
planetary photometry products from the accumulated database.

Do not start it while an independently launched `go11.sh` or `goBIG` batch is
still running. The pipeline prevents two copies of itself from running at once,
but it cannot lock an unrelated hand-started solver process.

## Preview

From the repository root:

```sh
./go_mmto_photometry.sh --dry-run
```

The preview reads `raw_allsky_samples/manifest.sqlite` and the selected
`stars.sqlite`, prints the verified, skipped, and pending counts, and lists each
pending image. It does not create a directory, run a solver, or write either
database.

Use explicit locations when the archive or results live elsewhere:

```sh
./go_mmto_photometry.sh --dry-run \
  --archive /path/to/raw_allsky_samples \
  --results-dir /path/to/solver-results
```

When `--results-dir` is omitted, the launcher follows the same choice as
`go11.sh`: `WFS_RESULTS_DIR`, then the host-specific results-directory setting,
then repository-local `results/`.

## Run

After any existing batch has finished:

```sh
./go_mmto_photometry.sh
```

The processing stage:

1. selects downloaded, verified MMTO rows from the downloader manifest;
2. deduplicates them by source SHA-256;
3. skips a source SHA-256 if `stars.sqlite` already contains any v0.11.0
   receipt, whether that attempt succeeded or failed;
4. rechecks each pending file's path, size, and SHA-256 against the manifest;
5. runs the frozen `go11.sh` sequentially for every remaining image; and
6. requires a matching v0.11.0 database receipt after every invocation.

A recorded scientific solve failure counts as processed and does not prevent
the remaining images or the later photometry stages from running. An
operational failure without a matching database receipt stops the pipeline.
Running the command again safely resumes from the receipts already stored.

This command processes files already present in the verified download
manifest. It does not download new images.

## Products

The default output is a new UTC-stamped directory:

```text
RESULTS_DIR/photometry-runs/YYYYMMDDTHHMMSSZ/
├── pipeline.log
├── pipeline_summary.json
├── stellar-lightcurves/
├── nightly-extinction/
└── planet-photometry/
    ├── planet_colour_colour.png
    ├── planet_colour_colour.csv
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
./go_mmto_photometry.sh \
  --archive /path/to/raw_allsky_samples \
  --results-dir /path/to/solver-results \
  --output /path/to/new-photometry-run
```

Existing output paths are refused, including empty directories, so historical
products cannot be overwritten. Extinction coefficients and corrected
magnitudes remain sidecar products; they are never added to `stars.sqlite`.

`pipeline_summary.json` records selection and processing counts, each stage's
exit status, paths, timestamps, and any operational failure. `pipeline.log`
contains the invoked commands and their combined output. After successful
completion the launcher prints `FIGURES (N)` followed by the absolute path of
every PDF or PNG actually present below that run directory. CSV, JSON, log and
working files are deliberately omitted from this operator-facing figure list.
