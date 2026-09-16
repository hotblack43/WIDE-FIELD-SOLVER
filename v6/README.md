# Gaia v6 runtime

For installation, choosing a solver and running images, use the
[shared guide for go.sh, go4.sh, go5.sh and go6.sh](../README.md).

Run `./go6.sh /path/to/image.jpg` or `./go_v0.6.0.sh /path/to/image.jpg` from the
repository root. This directory contains v0.6.0 and its local Python modules,
Gaia catalogue, provenance, dependency lockfile, tests and scientific status.
No development worktree is required.

V6 accepts native-depth grayscale/RGB PNG and TIFF plus 2-D, RGB and
`R/G1/G2/B` FITS images. Three- and four-plane FITS stacks may be plane-first or
plane-last; named `R/G1/G2/B` and long-form colour extensions are also accepted.
For ambiguous FITS files use, for example:

```sh
./go6.sh /path/to/image.fits --fits-hdu SCI --channel-order RG1G2B \
  --saturation-level R=4095,G1=4095,G2=4095,B=4095
```

The last three options are needed only when the file does not describe itself
unambiguously. Scientific samples retain native depth. The 8-bit rendering in
plots is a display-only stretch; `analysis/dots/input_image.json` records the
exact loading, channel and saturation policy.

The root `go.sh` remains the preserved Tycho-2/Hipparcos workflow. `go4.sh` and
`go_v0.4.3.sh` keep the preserved Gaia v0.4.3 package under `v4/`. Each runtime
has separate modules and a lockfile. For the implemented science and remaining
limitations, read [GOAL.md](GOAL.md) and [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).

`SOURCE_MANIFEST.json` records this version's source inventory. The baseline is
v0.5.0 at commit `27455801694a5e8d1338335f93d4e66d8410fc24`; new v6 development
belongs here. The preserved v5 files and launchers are recorded in
[../docs/v5-runtime.json](../docs/v5-runtime.json).

Validation, from this directory:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Bright-planet evidence, numerical rules and limitations: [docs/PLANET_NONDETECTIONS.md](docs/PLANET_NONDETECTIONS.md).

V6 can conservatively recover a third or later planet that was initially
assigned to Gaia when two independently eligible planets anchor a common date.
The full constellation is refitted before the planet and Gaia residuals are
compared. Every compatible one-to-one override alternative inside the ordinary
gate is tested, so a rejected nearer source or extra planet cannot mask a valid
Mars or Uranus match; isolated and two-body gates remain unchanged. JSON and CSV
retain the displaced catalogue identity and a `constellation_override` flag. See
[the verified Mars/Jupiter/Saturn case](docs/PLANET_CONSTELLATION_NOTES.md).

The v6 blind planet search ships a validated 1850--2036 daily proposal table,
batches exact Astropy refinement and uses up to four deterministic planet
workers. Set `WFS_PLANET_WORKERS=1` for the serial reference path. Timing and
call counts are written to `planet_search_performance.json`; see the
[controlled v5/v6 benchmark](docs/PLANET_SEARCH_PERFORMANCE.md), which measured
a 3.09x median planetary-stage speedup with unchanged candidate identities.
