# Gaia v8 runtime

For installation, choosing a solver and running images, use the
[shared guide for go.sh through go8.sh](../README.md).

Run `./go8.sh /path/to/image.jpg` or `./go_v0.8.0.sh /path/to/image.jpg` from the
repository root. This directory contains v0.8.0 and its local Python modules,
Gaia catalogue, provenance, dependency lockfile, tests and scientific status.
No development worktree is required.

Every `go8.sh` / `go_v0.8.0.sh` analysis automatically
appends its available data to `results/stars.sqlite` at the repository root.
Every rerun creates another entry, even for the same image. No duplicates or
quality-flagged measurements are removed. Failed analyses retain their available
partial products and error. See [database storage](docs/DATABASE.md).

V8 accepts native-depth grayscale/RGB PNG and TIFF plus 2-D, RGB and
`R/G1/G2/B` FITS images. Three- and four-plane FITS stacks may be plane-first or
plane-last; named `R/G1/G2/B` and long-form colour extensions are also accepted.
For ambiguous FITS files use, for example:

```sh
./go8.sh /path/to/image.fits --fits-hdu SCI --channel-order RG1G2B \
  --saturation-level R=4095,G1=4095,G2=4095,B=4095
```

The last three options are needed only when the file does not describe itself
unambiguously. Scientific samples retain native depth. The 8-bit rendering in
plots is a display-only stretch; `analysis/dots/input_image.json` records the
exact loading, channel and saturation policy.

After the blind tetra3 bootstrap, v8 performs catalogue association and robust
Barghini fitting in angular sky coordinates. Progressive great-circle gates end
at an 8.1-arcminute physical floor; for undersampled images the fitted camera adds
a minimum allowance equal to one detector pixel expressed in arcminutes.
Reports therefore lead with great-circle RMS/median/p90 and retain pixel
residuals only as useful detector diagnostics. The resolved gate and sampled
plate scale are saved in `result.json`.

By default, the v8 planetary stage uses an observation time found in an explicit
argument, FITS header, EXIF header or recognized filename to restrict the full
planet analysis to ±1 day. Stellar astrometry, refraction and photometric zenith
are fixed before this metadata is read. The local planetary date is still fitted
from measured positions and compared with the metadata time; visibility, solar,
Gaia-competition and missing-bright-planet checks still run. Products identify
this as metadata-conditioned and record the conditional timing error. With no
usable time, v8 falls back to the full blind search. Force that search with:

```sh
./go8.sh /path/to/image.fits --blind-planets
```

When observation-time metadata is available, v8 also performs a separate exact
association at that supplied instant after the blind astrometric fit is fixed.
A measured source inside the positional and catalogue-competition gates is
saved as `metadata_time_match`; visible ephemeris positions without a measured
source are saved and labelled `predicted_no_detected_source`. This can identify
a source such as Jupiter at the FITS time without claiming that the image
independently inferred the epoch.

The root `go.sh` remains the preserved Tycho-2/Hipparcos workflow. The v4, v5,
v6 and v7 launchers retain their corresponding preserved packages. Each runtime has
separate modules and a lockfile. For the implemented science and remaining
limitations, read [GOAL.md](GOAL.md) and [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).

`SOURCE_MANIFEST.json` records this version's source inventory. The baseline is
the exact working v0.7.0 snapshot recorded in
[../docs/v7-runtime.json](../docs/v7-runtime.json); new v8 development belongs
here.

V8 searches Ceres and Vesta alongside the seven inherited major planets using
a committed offline JPL Horizons reference. It also writes `source_photometry.csv`
for every detection and `identified_source_photometry.csv` for catalogue stars
and planet candidates, including metadata-time planet matches. FITS/EXIF exposure time produces instrumental ADU/s while
preserving raw aperture ADU. Saturated channels retain a labelled aperture lower
bound plus a separate robust Moffat-wing total and centroid; modelled values are
never used in the extinction/zenith fit.

Validation, from this directory:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Bright-planet evidence, numerical rules and limitations: [docs/PLANET_NONDETECTIONS.md](docs/PLANET_NONDETECTIONS.md).

V8 inherits v7's conservative recovery of a third or later planet that was initially
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

V8 inherits v7's blind detector-parity selection. A tetra3 seed may describe either a
normal or one-axis-reflected detector, without consulting FITS metadata, site,
time or a saved solution. The chosen parity is part of the Barghini camera,
propagates through saved coordinates, reports and ZPN export, and is recorded in
`bootstrap.json` and `result.json`. Seed refinement is adopted only when its
measured seed residual does not worsen; unusable seeds are rejected and the
remaining blind patch hypotheses continue. Seeds looser than 3 arcminutes RMS
are retained as fallbacks while later blind hypotheses are tried, so a weak
early tetra3 answer cannot suppress a stronger zero-distortion bootstrap.
