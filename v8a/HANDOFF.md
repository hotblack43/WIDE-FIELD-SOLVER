# Work/home handoff

v8a is an independent source/data copy of work v8, prepared on 2026-09-18
from commit `4035e1ddac6cd2254eb232714367c08ff27ef6f7` plus the uncommitted work changes.
The source version remains 0.8.0. Use `./go8a.sh IMAGE` from the repository root.
Its own environment is created from `v8a/uv.lock`; no v8 environment is copied.

## Features to preserve when combining home v8 and work v8a

- Direct `.fits.bz2`, `.fit.bz2` and `.fts.bz2` input, including post-fit
  FITS metadata, native colour/pixel values and compressed-source provenance.
- Portable output/database location: CLI, environment, host-specific config,
  then repository-local results. No work-only disk path is built into runtime.
- SQLite tests close connections before removing temporary directories on NFS.
- All inherited v8 science, exposure-normalized source photometry, saturated
  wing measurements and supplied-time planet association remain intact.
- Standalone MMT downloader: `scripts/mmt_archive/`, default 10-minute sampling.

`SOURCE_MANIFEST.json` contains the snapshot's hashes and original v8 manifest
hash. Scientific Python modules, catalogues, ephemerides and lockfile were
copied byte for byte; only launcher paths/labels and handoff documentation differ.

## Handoff after the work batch

The 65-image MMTO batch finished. Work `v8/` and `test_v8_launchers.py` now
match the committed baseline above; their work changes are preserved in `v8a/`
and `test_v8a_launchers.py`. The work changes were also saved as a binary Git
patch in `/dmidata/projects/earthshine/MMTO/handoff-backups/20260918T094218Z/`.
The backup includes the original `goBIG`, its patch, and source hashes.

Use `./go8a.sh IMAGE` for the updated work solver. `go8.sh` continues to select
the baseline v8; it does not include the bz2/output-location changes in v8a.
No solver results or database files were moved or removed.

The intended handoff adds v8a, its launcher/tests, the MMT downloader and the
MMTO plotting scripts. It changes no existing v8 file and deletes no version.
The user's edited `goBIG` remains separate from this additive handoff until its
batch-launcher choice is settled. Do not inadvertently include it in a broad
commit: it still references the old `go8.sh` entry point.

At home, preserve the existing v8 work before pulling. This additive handoff
lets home v8 coexist with work v8a. Ask Codex to compare and combine their
features afterward. Other shared files still need ordinary Git conflict checks.

The work machine's results preference lives outside Git. A different host
without its own setting uses local `results/`. Databases are not automatically
moved or merged; v8a appends to the configured database by default.

## MMTO photometry plots

`./plot_mmto_lightcurves.sh` reads the database without changing it. It makes
four named light curves with cross-validated polynomial trends and residual SD,
plus a residual-SD versus catalogue-magnitude plot for all qualifying MMTO stars.
It exports the measurements, residuals and statistics as CSV. The `latest/`
shortcut points to the newest default output. See `../scripts/MMTO_LIGHTCURVES.md`.
Figures are for astronomers: no explanatory magnitude-direction annotations.

## Handoff validation on 2026-09-18

- Complete root suite: 131 tests passed.
- Complete v8a suite: 307 tests, OK; one optional isolated DS9 consumer test
  skipped because `WFS_TEST_XVFB` was not enabled.
- Standalone MMT downloader: 9 tests passed.
- Historical demo: 3,653 associations, RMS 0.397892 pixels; unchanged baseline
  passed with 40 distributed labels.
- A clean export of the staged additions launches `go8a.sh`, `v8a/analyse.sh`
  and the MMTO plotter outside this workspace.
- Only new paths are included in the handoff commit. Every manifest asset,
  including the bundled historical images, is included and hash-verified.
