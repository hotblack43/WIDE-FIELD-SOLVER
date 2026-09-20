# WIDE-FIELD SOLVER

**Blind, full-frame astrometry for fisheye and other extreme wide-field images**

Peter Thejll and Chris Flynn

[![Solver regression](https://github.com/hotblack43/WIDE-FIELD-SOLVER/actions/workflows/tests.yml/badge.svg)](https://github.com/hotblack43/WIDE-FIELD-SOLVER/actions/workflows/tests.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-312E81)](pyproject.toml)
[![Development line](https://img.shields.io/badge/development-v0.10.0-C026D3)](v10/README.md)
[![MMTO astrometry](https://img.shields.io/badge/MMTO_RMS-0.327_px-F2B134)](docs/SCIENTIFIC_STATUS.md)
[![License: BSD 3-Clause](https://img.shields.io/badge/license-BSD_3--Clause-312E81)](LICENSE)

WIDE-FIELD SOLVER finds point-source stars directly from an image, identifies
them against a catalogue, and fits the Barghini O/Z fisheye model across the
whole detector. The stellar solution is seeded without an observing site,
camera orientation or image timestamp.

<p align="center">
  <img src="reports/wide-field-diagnostics/figures/mmto_sky_overlay.png"
       width="1100"
       alt="Solved colour all-sky image from the MMT Observatory, with identified catalogue stars, Jupiter, a provisional zenith and a predicted Uranus position">
</p>

<p align="center"><em>
MMT Observatory colour FITS image. The labels are generated after the astrometric
fit; the display stretch does not change the native scientific samples.
</em></p>

## What it does

- detects ordinary, undersampled, broad and saturated point sources;
- bootstraps a blind sky identification with `tetra3`;
- fits the Barghini fisheye camera model in angular sky coordinates;
- propagates Gaia proper motions and tests a stellar epoch;
- measures instrumental multi-channel photometry and a provisional
  image-derived zenith/extinction constraint;
- searches for planetary position matches in a separate, explicitly labelled
  stage; and
- saves an illustrated PDF report, machine-readable tables, provenance and an
  append-only SQLite record.

## Current single-image result

The v0.9.0 solver was run on one MMT Observatory colour FITS image dated
2026-01-15. It obtained:

| Measure | Result |
|---|---:|
| Matched stars | 1,380 |
| Astrometric RMS | **0.3267 px** |
| Median residual | **0.2350 px** |
| 90th-percentile residual | **0.4964 px** |
| Angular RMS | 2.502 arcmin |

These are fitted residuals, not an independent withheld-star accuracy test.
The result is nevertheless directly comparable in detector units with the
approximately 0.33-pixel whole-night result reported for the MMTO camera's
operational calibration.

## Quick start

The tested platform is Linux. Install
[`uv`](https://docs.astral.sh/uv/), then run:

```bash
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
uv sync --project v10 --frozen
./go10.sh /full/path/to/image.fits
```

Compressed FITS input is accepted directly:

```bash
./go10.sh /full/path/to/image.fits.bz2
```

Canon CR2 input is decoded from the native 14-bit Bayer sensor data, not its
embedded JPEG preview:

```bash
./go10.sh /full/path/to/image.cr2
```

Shell-expanded wildcards process a batch sequentially with the same options:

```bash
./go10.sh raw_allsky_samples/mmto/mmto-skycam/*/*.fits.bz2 \
  --results-dir /path/to/results
```

Each image gets its own run directory. A failed image does not prevent later
images from running; the final batch summary and exit status report whether any
failed. An unmatched wildcard is rejected before analysis starts.

Each run gets a unique directory. The command prints the location of
`analysis/report.pdf`, the run log and `stars.sqlite` when it starts and again
when it finishes.

## Read next

| If you want to… | Read… |
|---|---|
| install and solve a first image | [Quick start](docs/QUICKSTART.md) |
| understand the fitted model | [Method](docs/METHOD.md) |
| interpret reports and output files | [Results and outputs](docs/RESULTS.md) |
| see what is validated and what remains provisional | [Scientific status](docs/SCIENTIFIC_STATUS.md) |
| choose among preserved versions | [Version guide](docs/VERSIONS.md) |
| see every launcher and advanced option | [Complete reference](REFERENCE.md) |

The documentation source is configured for MkDocs/Read the Docs. Build it
locally with:

```bash
uvx --with mkdocs-material==9.7.7 mkdocs==1.6.1 build --strict
```

## Scientific boundaries

The code distinguishes a successful plate solution from an identified physical
zenith or observation epoch. Instrumental count rates are not calibrated fluxes.
Metadata is not allowed to seed or tune the stellar astrometric fit; when used
later for planetary analysis it is labelled as metadata-conditioned. See
[the durable scientific goal](GOAL.md) and
[the detailed v0.10.0 feature inventory](v10/docs/FEATURE_STATUS.md).

## Citation, releases and reuse

The project-authored software is copyright © 2026 Peter Thejll and Chris Flynn
and is available under the [BSD 3-Clause License](LICENSE). You may use, modify
and redistribute it under those terms. If you use WIDE-FIELD SOLVER in
scientific work, please use the repository's [`CITATION.cff`](CITATION.cff);
GitHub's **Cite this repository** menu supplies APA and BibTeX forms.

The latest packaged release is v0.6.0; current development is v0.10.0 under
`v10/`. The complete v9 runtime is preserved unchanged. Historical solvers
remain available for reproducible comparison and are protected by recorded
manifests and regression tests.

The BSD licence covers project-authored software, not third-party code,
catalogues or images. Those materials retain their own terms. Read
[NOTICE.md](NOTICE.md) before redistribution.

Analyses and publications using MMTO all-sky-camera data should acknowledge the
MMT Observatory. We thank Tim Pickering and the Observatory for maintaining the
camera and making its colour FITS archive available.

## Raw colour all-sky acquisition

`download_samples.py` lists archive metadata, applies deterministic cadence and
the absolute file cap, and only then downloads selected originals. The default
cadence is ten minutes; omitting it never means “download everything”. Existing
files are checksum-verified through `raw_allsky_samples/manifest.sqlite`.

Preview one MMTO night without downloading:

```bash
uv run --frozen python download_samples.py \
  --site mmto --night 2026-09-18 --sun-below -12 \
  --cadence 20m --max-files 20 --dry-run
```

`--night` is the observing-night date: local noon on that date through local
noon the following date. `--sun-below -12` retains only exposures with the
geometric centre of the Sun more than 12 degrees below the site's horizon,
excluding bright dusk and dawn twilight. Site latitude,
longitude and timezone come from `sources.json`; missing latitude or longitude
is an error rather than an assumed location. Remove `--dry-run` to download.
`--date` and `--start`/`--end` retain their site-local civil-day meanings:

```bash
uv run --frozen python download_samples.py \
  --site mmto --start 2026-09-01 --end 2026-09-03 \
  --cadence 30m --max-files 20 --dry-run

uv run --frozen python download_samples.py \
  --site trex --camera luck_rgb-03 --date 2026-01-15 \
  --cadence 30m --max-files 15 --dry-run
```

Inspect downloaded FITS, HDF5 and camera-RAW originals without modifying them:

```bash
uv run --script inspect_allsky_samples.py
```

The script isolates `rawpy` and `h5py` from every preserved solver runtime.
Inspection results go to `raw_allsky_samples/inspection.json`; display previews
are derived products. See [the source audit](SOURCES.md) for exact URLs and
scientific validation.

New downloads are grouped as
`raw_allsky_samples/<source>/<camera>/<observing-night>/filename`, where the
observing-night label changes at local noon rather than midnight. Existing MMTO
downloads have been migrated to this layout; historical files were preserved
even when they predate the solar-altitude filter.

The safe incremental MMTO command uses a Phoenix-local noon-to-noon observing
night, rejects exposures with solar altitude greater than or equal to -12 degrees,
uses a 20-minute cadence, selects the oldest cadence slot not already recorded
as downloaded, and permits at most one new raw file per invocation. This lets a
late-published archive file be recovered on a later cycle instead of being
permanently skipped:

```bash
uv run --frozen python run_raw_allsky_cron.py --site mmto --dry-run
```

Installing the repository does not modify cron. On a capture host, the MMTO
acquisition command is normally scheduled at minutes 0, 20 and 40 under
`/tmp/wide-field-raw-allsky-mmto.lock`. Moon-down selection remains future
work; solar-altitude selection is available through `--sun-below` for any
registered telescope with latitude and longitude.

### Automatic MMTO processing queue

New files downloaded by the recurring MMTO command are atomically added to a
durable FIFO queue in `raw_allsky_samples/manifest.sqlite`. Existing files and
checksum-verified `REUSE` events are deliberately not bulk-enqueued. A separate
worker takes at most one image per invocation and calls the frozen root
`go10.sh` with that image only. It writes automated runs to
`results/mmto-automatic/`; neither `go10.sh` nor `v10/` is modified, and current
`go11.sh`/`v11/` development is explicitly outside this queue.

The processing worker is normally scheduled every two minutes under
`/tmp/wide-field-solver-mmto-processing.lock`, independently of acquisition.
If one solve takes longer, later cron invocations fail to acquire that worker
lock and do nothing. New downloads continue to enter the queue, and the oldest
pending image is selected when the worker becomes free. Files, logs, run
directories, database rows and queue events are never erased by the worker.
The solver inherits the worker lock and writes its attempt log directly, so
killing the wrapper does not unlock a still-running solver or lose its output.

Inspect the live queue without changing it:

```bash
uv run --frozen python run_allsky_processing.py status
```

The states are `pending`, `running`, `succeeded`, `solver_failed`,
`operational_failed`, and `interrupted`. A stale `running` row means the worker
was probably stopped after claiming the image; it does not block later pending
rows. Scientific solver failures and operational failures are both terminal:
there is no automatic retry and no stochastic assumption that an identical
rerun will improve the answer.

The cleanup command is an explicit later sweep. It is read-only unless
`--apply` is supplied, and an applying sweep must be bounded by a source,
observing night, job ID, or remote URL plus its absolute `--limit`:

```bash
uv run --frozen python run_allsky_processing.py cleanup \
  --source mmto --night 2026-09-18 --limit 20

uv run --frozen python run_allsky_processing.py cleanup \
  --source mmto --night 2026-09-18 --limit 20 --apply
```

Before requeueing, cleanup searches the dedicated `stars.sqlite` by the
verified source checksum. It records one existing matching solver receipt
instead of rerunning the image and refuses ambiguous multiple receipts.
An applying cleanup must also acquire the processing-worker lock, so it
refuses to alter a stale-looking row while a long solver process is still
active.
Cleanup may explicitly requeue overlooked downloads, stale interrupted jobs,
or selected operational failures. It never requeues `solver_failed` jobs.
Each attempt records the exact hashes of `go10.sh` and
`v10/SOURCE_MANIFEST.json` used for provenance; those hashes are evidence, not
input to the blind solution.
