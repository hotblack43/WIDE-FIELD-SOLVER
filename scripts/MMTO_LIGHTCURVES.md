# MMTO machine magnitude versus time

From the repository root:

```sh
./plot_mmto_lightcurves.sh
```

This makes four vertically stacked panels, one star per panel, using completed
MMTO runs currently in the SQLite database. The batch may keep running. Repeat
the command later to include newly completed images. It writes `lightcurves.png`,
`lightcurves.pdf`, `measurements.csv`, `residuals.csv`, `summary.json`, plus
`sd_vs_magnitude.png`, `.pdf` and `.csv` into a new timestamped
folder beside the database, under `lightcurves/`. It never writes to the database
or changes the active v8 solver.

The default database uses `WFS_RESULTS_DIR`, then the launcher's host-specific
user setting, then repository-local `results/stars.sqlite`. No work-only path
is built into the code. The downloader's `manifest.csv` is found beside the
database or one directory above. Explicit locations work on either computer:

```sh
./plot_mmto_lightcurves.sh \
  --database /dmidata/projects/earthshine/MMTO/solver-results/stars.sqlite \
  --manifest /dmidata/projects/earthshine/MMTO/manifest.csv
```

Choose one star using a catalogue ID or a saved/cached alias:

```sh
./plot_mmto_lightcurves.sh --star 'HD 219134'
./plot_mmto_lightcurves.sh --star 'HIP 114622' --channel R
```

A star must actually have usable stored MMTO measurements and the requested
identifier/alias must be saved in the database or the plotter's name cache. An absent name gives an explicit
error. Repeat `--star` for multiple named panels. Named selection bypasses the
random sample's magnitude and count thresholds; it still requires valid,
unsaturated photometry. Different catalogue hashes remain separate series.

Default random selection: catalogue magnitude 2.5–6.0, at least 10 independent
images and at least 75% of the largest qualifying count. Magnitudes are the
stored catalogue passband (Gaia G or the bright Tycho/Hipparcos supplement), not
calibrated camera magnitudes. Seed 42 makes the sample reproducible for the same
database snapshot. Change the sample or cuts, for example:

```sh
./plot_mmto_lightcurves.sh --seed 7 --count 4 --min-points 15 --max-mag 5.5
./plot_mmto_lightcurves.sh --star 'HD 219134' --channel G --output /tmp/hd219134-lightcurve
```

The output directory must be new, to preserve earlier plots. If fewer stars meet
the cuts, only those are plotted and the shortage is reported; cuts are never
silently weakened. `summary.json` records chosen stars, filters and omitted-run
counts; `measurements.csv` contains each plotted measurement and its provenance.

## Scientific conventions

- MMTO restriction is by image SHA-256 matched to downloader manifest rows whose
  source URL is on `skycam.mmto.arizona.edu/skycam/archive/`. Other-camera rows
  and MMTO images without a matching timestamp are excluded. Original image
  files need not still be available.
- Time is the manifest's corrected UTC exposure midpoint. Neither database
  insertion time nor uncorrected FITS/filename time becomes observation time.
- Machine magnitude is `-2.5 log10(aperture ADU / exposure seconds)`, using the
  saved count rate where available. Its arbitrary zero point is zero. Default
  channel is G; `--channel R`, B, L, G1 and G2 are also accepted when stored.
- Exclude unknown/saturated channels, nonpositive/nonfinite count rates and
  unknown/nonpositive exposure durations. Saturated wing-model fluxes are not
  mixed with aperture fluxes. A clean channel remains eligible when another
  channel is saturated.
- Only successful runs enter plots. For a repeated image/catalogue pair, use
  the most recently recorded successful run, then apply quality cuts. Reruns
  cannot inflate the number of observed images. Nothing is removed from SQLite.
- These are raw instrumental light curves. Airmass, vignetting, transparency,
  colour response and aperture effects can produce trends; no extinction,
  differential comparison-star or flat-field correction is applied. Points are not connected across missing data.

Dependencies are supplied by the existing locked v8a environment. To run the
Python script directly:

```sh
uv run --project v8a --frozen python scripts/plot_star_lightcurves.py --help
uv run --project v8a --frozen python -m unittest -v test_plot_star_lightcurves
```

## Polynomial trends and residual scatter

Each panel overlays an unweighted least-squares polynomial. Degrees 0 through 6
are considered by default (`--max-degree 4` changes the upper bound). The selected
degree minimizes leave-one-out prediction mean-square error; numerical ties
prefer the lower degree. This is optimal within the tested degrees under that
criterion, not a physical light-curve model. The cap is also at most N−3 and the
number of distinct times minus one, retaining at least two residual degrees of
freedom when N permits. One/two-point series receive a constant trend; a single
point has no reportable SD or cross-validation score.

Time is centred and scaled to [-1,1], using a Chebyshev polynomial basis for
numerical stability. All accepted measurements enter each final fit, with no
clipping or uncertainty weighting. Cross-validation omits each point only for
scoring the degree; it does not remove points from the saved data or solver fits.
The smooth line is drawn only over the observed time interval.

The title reads `catalogue mag ... | residual SD ... mag`. SD is the sample
standard deviation of `observed magnitude − polynomial`, with denominator N−1.
It describes scatter after fitting and is not an independent noise estimate.
`summary.json` also records `residual_standard_error_mag`, using denominator
N−(degree+1), the chosen degree, cross-validation scores, coefficients and exact
time scaling. Model selection and time-correlated residuals can still bias
precision interpretations; the polynomial can remove genuine variability too.

`measurements.csv` retains the original magnitudes and adds `polynomial_degree`,
`fitted_magnitude` and `residual_mag`. `residuals.csv` provides these together with
UTC midpoints, star IDs, run IDs and source hashes for further analysis.

Ordinary saved aliases are used first. For missing names the plotter queries
SIMBAD using the exact catalogue IDs, through the existing v8a name resolver.
Results are cached in `lightcurves/display_names.json` beside the database;
`--offline-names` suppresses network access. Neither names nor the cache can
change measurements, star associations or polynomial fits. Failed lookups are
reported, with an unavailable-name panel label and the real catalogue ID retained
in CSV/JSON and console output. Cached resolved names work in later `--star` commands.
SIMBAD's lookup interface is documented at
https://astroquery.readthedocs.io/en/latest/simbad/simbad.html.

## Output paths and ensemble scatter

`lightcurves.png` itself contains the orange polynomial fits and each residual
SD after the catalogue magnitude. Old timestamped folders retain their original
figures. Each successful default run also updates the relative `latest` shortcut:

```text
RESULTS_DIRECTORY/lightcurves/latest/lightcurves.png
RESULTS_DIRECTORY/lightcurves/latest/sd_vs_magnitude.png
```

Both full PNG paths and these shortcuts are printed by the command. Explicit
`--output` keeps its own files and does not change the default shortcut.

`sd_vs_magnitude.png` plots polynomial-residual SD against stored catalogue
magnitude for **all** MMTO stars passing `--min-mag`, `--max-mag`, `--min-points`
and `--coverage`. The sample is independent of the four random panels and uses
the same time data, quality cuts, polynomial-selection rule and SD definition.
At least two measurements are required to define an SD, even with
`--min-points 1`. One row per star/catalogue series is saved in `sd_vs_magnitude.csv`, including
count, selected polynomial degree, residual SD and degrees-of-freedom-corrected
standard error. The four panel stars are highlighted if they meet these cuts.
No network name queries are made for the full ensemble.

Figure audience: professional astronomers. Do not add magnitude-direction
explanations such as “brighter is higher”, or tutorials about magnitude
conventions. Restrict annotations to quantities, selection, methods and statistics.
