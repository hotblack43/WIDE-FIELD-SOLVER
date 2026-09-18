# Gaia v0.10.0 wide-field solver

V10 preserves the complete v9 feature set in an independent
runtime. Its parent packages are checksum-frozen; run folders and database rows
record this package's distinct source manifest. The inherited v0.9.0 display change keeps
the fitted zenith marker and legend entry while omitting its large on-image text
label. No fitted coordinates or scientific algorithms changed.

For installation, choosing a solver and running images, use the
[shared guide for go.sh through go10.sh](../README.md).

Run `./go10.sh /path/to/image.jpg` from the
repository root. This directory contains v0.10.0 and its local Python modules,
Gaia catalogue, provenance, dependency lockfile, tests and scientific status.
No development worktree is required.

Every `go10.sh` analysis automatically
appends its available data to `stars.sqlite` in the selected results directory
(default: `results/` at the repository root).
Every rerun creates another entry, even for the same image. No duplicates or
quality-flagged measurements are removed. Failed analyses retain their available
partial products and error. See [database storage](docs/DATABASE.md).

V10 accepts Canon CR2 directly as native undemosaiced Bayer samples, plus
native-depth grayscale/RGB PNG and TIFF and 2-D, RGB and
`R/G1/G2/B` FITS images. Three- and four-plane FITS stacks may be plane-first or
plane-last; named `R/G1/G2/B` and long-form colour extensions are also accepted.
CR2 is decoded only with rawpy/LibRaw from `raw_image_visible`; an embedded JPEG
preview is never used. The RGGB/BGGR/GRBG/GBRG mosaic is separated without
interpolation into half-resolution `R/G1/G2/B` planes, preserving integer ADU.
Black and white levels, exposure, ISO, camera and lens provenance are recorded.
Black levels are not globally subtracted because local background estimates
already remove offsets. Capture time is deliberately requested only after the
blind stellar fit is fixed.

```sh
./go10.sh /path/to/exposure.cr2
```

For ambiguous FITS files use, for example:

```sh
./go10.sh /path/to/image.fits --fits-hdu SCI --channel-order RG1G2B \
  --saturation-level R=4095,G1=4095,G2=4095,B=4095
```

The last three options are needed only when the file does not describe itself
unambiguously. Scientific samples retain native depth. The 8-bit rendering in
plots is a display-only stretch; `analysis/dots/input_image.json` records the
exact loading, channel and saturation policy.

When an image-derived footprint excludes a dark camera frame, FITS WCS
validation is restricted to that measured sky domain. `solution.fits` contains
NaN outside the accepted sky; `solution_annotated.fits` keeps every native plane
unchanged and adds a `SKYMASK` extension. A mask cannot rescue a radial model
that is non-invertible inside the accepted sky, and the 0.05-pixel export limit
is unchanged. See the [Rubin CR2 acceptance record](docs/RUBIN_CR2_ACCEPTANCE.md).

After the blind tetra3 bootstrap, v10 performs catalogue association and robust
Barghini fitting in angular sky coordinates. Progressive great-circle gates end
at an 8.1-arcminute physical floor; for undersampled images the fitted camera adds
a minimum allowance equal to one detector pixel expressed in arcminutes.
Reports therefore lead with great-circle RMS/median/p90 and retain pixel
residuals only as useful detector diagnostics. The resolved gate and sampled
plate scale are saved in `result.json`.

By default, the v10 planetary stage uses an observation time found in an explicit
argument, FITS header, EXIF header or recognized filename to restrict the full
planet analysis to ±1 day. Stellar astrometry, refraction and photometric zenith
are fixed before this metadata is read. The local planetary date is still fitted
from measured positions and compared with the metadata time; visibility, solar,
Gaia-competition and missing-bright-planet checks still run. Products identify
this as metadata-conditioned and record the conditional timing error. With no
usable time, v10 falls back to the full blind search. Force that search with:

```sh
./go10.sh /path/to/image.fits --blind-planets
```

When observation-time metadata is available, v10 also performs a separate exact
association at that supplied instant after the blind astrometric fit is fixed.
Planet/source assignment, blind candidate fitting and Gaia competition all use
great-circle residuals: the ordinary planet gate is 30 arcminutes and the
positional-uncertainty floor is 3 arcminutes. Pixel residuals remain saved only
as detector diagnostics. A measured source inside the angular and
catalogue-competition gates is saved as `metadata_time_match`; visible ephemeris
positions without a measured source are saved and labelled
`predicted_no_detected_source`.

For a metadata-predicted planet without an ordinary source, v10 may audit nearby
maxima from the detector pass actually selected for the solution, rejected only
as `too_sharp` or `too_small`. Maxima outside the saved sky footprint or
overlapping an accepted source are excluded. A remaining maximum is
recovered only when it is significant in at least two channels of a colour image
(or the one channel of a monochrome image) and lies inside the same angular
planet gate. It remains labelled `targeted_planet_recovery`, never enters the
stellar camera fit, and retains its original rejection reason. Its per-channel
aperture counts and count rates are appended to the photometry tables. This can
recover an undersampled source such as Uranus without moving either the measured
centroid or predicted ephemeris symbol, and without claiming that the image
independently inferred the epoch.

The root `go.sh` remains the preserved Tycho-2/Hipparcos workflow. The v4, v5,
v6 and v7 launchers retain their corresponding preserved packages. Each runtime has
separate modules and a lockfile. For the implemented science and remaining
limitations, read [GOAL.md](GOAL.md) and [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).

`SOURCE_MANIFEST.json` records this version's source inventory. The baseline is
the preserved v8 and v8a snapshots recorded in
[../docs/v8-runtime.json](../docs/v8-runtime.json) and
[../docs/v9-runtime.json](../docs/v9-runtime.json); new v10 development belongs here.

V10 searches Ceres and Vesta alongside the seven inherited major planets using
a committed offline JPL Horizons reference. It also writes `source_photometry.csv`
for every detection and `identified_source_photometry.csv` for catalogue stars
and planet candidates, including metadata-time planet matches. FITS/EXIF exposure time produces instrumental ADU/s while
preserving raw aperture ADU. Saturated channels retain a labelled aperture lower
bound plus a separate robust Moffat-wing total and centroid; modelled values are
never used in the extinction/zenith fit.

The report's RGB-versus-Gaia diagnostic uses soft-L1 robust least squares with
a fixed 0.1-mag loss scale and reports MAD residual scatter. It does not display
or silently fall back to an ordinary least-squares photometry line.

Validation, from this directory:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Bright-planet evidence, numerical rules and limitations: [docs/PLANET_NONDETECTIONS.md](docs/PLANET_NONDETECTIONS.md).

V10 inherits v7's conservative recovery of a third or later planet that was initially
assigned to Gaia when two independently eligible planets anchor a common date.
The full constellation is refitted before the planet and Gaia residuals are
compared. Every compatible one-to-one override alternative inside the ordinary
gate is tested, so a rejected nearer source or extra planet cannot mask a valid
Mars or Uranus match; isolated and two-body gates remain unchanged. JSON and CSV
retain the displaced catalogue identity and a `constellation_override` flag. See
[the verified Mars/Jupiter/Saturn case](docs/PLANET_CONSTELLATION_NOTES.md).

The inherited blind planet search ships a validated 1850--2036 daily proposal table,
batches exact Astropy refinement and uses up to four deterministic planet
workers. It remains the `--blind-planets` path and the no-metadata fallback.
Set `WFS_PLANET_WORKERS=1` for the serial reference path. Timing and
call counts are written to `planet_search_performance.json`; see the
[controlled v5/v6 benchmark](docs/PLANET_SEARCH_PERFORMANCE.md), which measured
a 3.09x median planetary-stage speedup with unchanged candidate identities.
The measured Paranal ApiCam diagnosis and corrected v7 result are recorded in
[docs/APICAM_PARANAL_V07.md](docs/APICAM_PARANAL_V07.md).

V10 inherits v7's blind detector-parity selection. A tetra3 seed may describe either a
normal or one-axis-reflected detector, without consulting FITS metadata, site,
time or a saved solution. The chosen parity is part of the Barghini camera,
propagates through saved coordinates, reports and ZPN export, and is recorded in
`bootstrap.json` and `result.json`. Seed refinement is adopted only when its
measured seed residual does not worsen; unusable seeds are rejected and the
remaining blind patch hypotheses continue. Seeds looser than 3 arcminutes RMS
are retained as fallbacks while later blind hypotheses are tried, so a weak
early tetra3 answer cannot suppress a stronger zero-distortion bootstrap.

Compressed FITS input is supported directly, for example:

```sh
./go10.sh /path/to/image.fits.bz2
```

`.fit.bz2` and `.fts.bz2` also work. Astropy decompresses on read; the original
file, FITS headers, physical pixel values and colour channels are preserved.
Input provenance records `source_compression: bz2` and the compressed-file hash.
Compression does not change the existing interpretation of observation-time
headers; archive-specific clock errors still require an explicit corrected time
when running a metadata-conditioned analysis.

### Process several images

Pass a shell-expanded wildcard, or list several paths explicitly:

```sh
./go10.sh /path/to/mmto/*.fits.bz2 --results-dir /path/to/results
./go10.sh first.cr2 second.cr2
```

Inputs are validated before analysis begins, so an unmatched wildcard cannot
start a partial batch. Images run sequentially with the same native-input
options and each receives a unique run directory. If one analysis fails, its
partial output and log are retained and later images still run. The launcher
prints a final success/failure count and returns status 1 if any image failed.

### Results on a larger disk

`go10.sh` stores both run folders and `stars.sqlite` under the
selected results directory. Priority: `--results-dir PATH`, `WFS_RESULTS_DIR`,
host-specific user preference, then this repository's `results/`.

```sh
./go10.sh image.fits.bz2 --results-dir /path/to/larger/disk/results
# Or for a shell/batch:
export WFS_RESULTS_DIR=/path/to/larger/disk/results
./go10.sh image.fits.bz2
```

A persistent setting for this computer only is a one-line absolute path in
`${XDG_CONFIG_HOME:-$HOME/.config}/wide-field-solver/results-dir.$(hostname)`.
Create the destination directory first. For example, on the work machine:

```sh
mkdir -p /dmidata/projects/earthshine/MMTO/solver-results
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/wide-field-solver"
printf '%s\n' /dmidata/projects/earthshine/MMTO/solver-results > \
  "${XDG_CONFIG_HOME:-$HOME/.config}/wide-field-solver/results-dir.$(hostname)"
```

No `/dmidata` path is built into the launcher. On another computer without its
own setting, output stays in the local repository's `results/`. A missing or unwritable
configured directory produces a clear error instead of silently switching to
the local default. Logs print the actual run and database locations. Existing databases are
not automatically merged or moved when switching locations; pass the selected
`stars.sqlite` explicitly to tools that otherwise assume `results/stars.sqlite`.
