# MMTO nightly extinction calibration

The MMTO extinction workflow is a read-only analysis of accumulated solver
results. It estimates atmospheric extinction only from identified stars and
then applies the stellar result to planets. It does not modify `stars.sqlite`.

## Scientific model

The fit is performed independently for every observing night and camera band
R, G, and B. All eligible stellar measurements in one night/band are solved
together:

```text
m_machine(s, i) = a_s + k_night,band X(s, i) + error(s, i)
m_machine = -2.5 log10(count_rate_adu_per_s)
```

Every star `s` has its own fitted intercept `a_s`. The extinction coefficient
`k_night,band` is the one slope shared by all stars in that night and band. A
soft-L1 robust least-squares solution, with a 0.1-mag loss scale, fits all star
intercepts and the shared slope simultaneously. Catalogue magnitudes select and
identify the reference stars; they are not forced into a common intercept.

This fixed-effects form is essential: stars have different intrinsic
brightnesses and therefore cannot share an intercept. The slope is identified
from changes in airmass within repeatedly observed stars, not from brightness
differences between stars.

The adopted assumptions are that conditions and instrumental response are
constant within one night and band, that all selected stars share one
extinction coefficient, and that no colour term is needed. Each night and band
is solved separately.

Only stars with catalogue magnitude below 4.0, at least 10 valid observations
in that night/band, known-unsaturated ordinary-aperture photometry, and saved
airmass `X <= 5` enter the fit. Each image needs at least 30 such stars. A
night/band needs at least 10 accepted images and at least 1.0 airmass of
within-star leverage. Failed gates remain explicit; the code does not lower
the thresholds or substitute another fit.

Per-image Theil--Sen and OLS slopes remain diagnostics of departures from the
constant-night assumption. They never replace the shared nightly slope.

## Planet correction

Planets do not participate in fitting `k`. Once a nightly band-specific slope
has been accepted, every planet measurement with known airmass is corrected by

```text
m_extinction_corrected = m_planet_raw - k_night,band X_planet
```

No stellar intercept, catalogue magnitude, image zero point, colour term, or
planet distance correction enters this intermediate extinction-corrected
quantity. The standard batch subsequently distance-normalizes it and plots the
combined extinction- and distance-corrected magnitude. A deliberately
extinction-only plot remains available through the separate command-line mode.

The calibrated join is exact in source SHA-256, catalogue SHA-256, observing
night, band, and trusted manifest UTC. Missing joins, invalid planet airmass,
or unreproducible aperture fluxes are retained in
`planet_extinction_correction_audit.csv` and excluded from the plot. There is
no raw-magnitude fallback.

## Run the workflow

The complete workflow, including stellar light curves, the nightly fit, and
the three planet plots, is:

```sh
./go_mmto_photometry.sh \
  --archive raw_allsky_samples \
  --results-dir results \
  --output results/photometry-runs/NEW-UNIQUE-NAME
```

The output path must not already exist. The nightly stage can also be run
alone:

```sh
./calibrate_mmto_extinction.sh \
  --database results/stars.sqlite \
  --manifest raw_allsky_samples/manifest.sqlite \
  --output results/nightly-extinction/NEW-UNIQUE-NAME
```

To replot planets from an existing sidecar:

```sh
./plot_ALL_planets.sh \
  --database results/stars.sqlite \
  --nightly-calibration results/nightly-extinction/NEW-UNIQUE-NAME \
  --output results/planet-plots-nightly-NEW-UNIQUE-NAME
```

The database is opened read-only/query-only and calibration works from one
transaction snapshot. Images and corrected UTC midpoints are selected by exact
source-SHA matches to verified downloader-manifest rows. Nights use the Arizona
local-noon bucket. Stellar airmass comes from the saved blind solution and is
not recomputed from site/time metadata.

## Calibration sidecar

The nightly sidecar contains:

- `nightly_shared_slope_fits.csv`: one adopted fit per night/band, including
  all contributing catalogue hashes, `k`, its uncertainty, robust-fit settings,
  residual RMS, counts, total airmass range, and maximum within-star airmass
  span;
- `nightly_star_intercepts.csv`: every fitted `a_s`, proving that the joint
  system used a distinct intercept for each star;
- `nightly_extinction_coefficients.csv`: the adopted shared slopes plus the
  scatter of diagnostic per-image slopes;
- `image_extinction_joins.csv`: exact image identities linked to the accepted
  night/band slope, without exporting or applying a zero point;
- `calibration_star_measurements.csv`: inclusion, exclusion, and residual
  audit rows;
- `corrected_stellar_photometry.csv`: stellar values after subtracting `kX`;
- `image_extinction_fits.csv`: diagnostic per-image fits;
- `extinction_diagnostics.pdf` and `extinction_by_band_and_night.pdf`: fit
  diagnostics; and
- `calibration_manifest.json`: provenance, formulae, thresholds, and aggregate
  statuses.

Each planet band directory contains:

- `planet_extinction_corrected_distance_magnitude_vs_time.pdf`: all nights in
  one plot after extinction correction and distance normalization;
- `planet_extinction_corrected_distance_magnitude_vs_hours_past_local_noon.pdf`:
  the same final quantity overlaid by elapsed time since 12:00 Arizona local
  time, with lines joining measurements only within one
  planet/night/camera sequence;
- `planet_extinction_corrected_distance_magnitude_vs_airmass.pdf`: the same
  final quantity against saved planet airmass, using the local-noon plot's
  planet colours, camera symbols, uncertainty bars, and within-sequence lines;
- `planet_raw_vs_extinction_corrected_magnitude_vs_airmass.pdf`: a two-panel
  diagnostic comparing raw instrumental magnitude with `m_machine - kX` on a
  shared inverted magnitude scale. Distance normalization is deliberately
  omitted from both panels so their only numerical difference is the nightly
  stellar extinction correction;
- `planet_extinction_corrected_distance_measurements.csv`: the plotted raw
  magnitude, planet airmass, nightly `k`, extinction-corrected magnitude,
  distance-normalized magnitude, distances, local-noon phase, and
  uncertainties;
- `planet_extinction_corrected_distance_nightly_slopes.csv`: an ordinary
  least-squares diagnostic slope in magnitude per hour for each
  planet/night/camera group having at least four points;
- `planet_extinction_correction_audit.csv`: every included and excluded
  detection; and
- `extinction_corrected_distance_summary.json`: counts and provenance.

The parent planet-output directory additionally contains
`planet_colour_colour.png`, placing every planet with complete matched RGB
measurements on one `B-G` versus `B-R` diagram. The
symbol identifies the planet, while colour records hours since the latest
Arizona local noon. `planet_colour_colour.csv` preserves the exact joined
corrected magnitudes and derived indices. These products use
`extinction_corrected_distance_magnitude` in all three bands and omit a point
when any corrected band is unavailable.

The same directory also contains
`planet_brightness_matched_stellar_extinction.pdf` and its auditable CSV. For
each planet/night/channel/camera sequence, this diagnostic uses only stellar
measurements from the exact source-image hashes containing that planet. A star
is matched when its median count rate over those images is within 0.5 mag of
the planet's median count rate. Measurements above airmass 5 are excluded
before fitting. The planet and each matched star must then have at least 10
retained measurements and an airmass span of at least 0.5. Independent
Theil--Sen raw magnitude-versus-airmass slopes are measured for the planet and
each star; the plot compares the planet slope with the median and interquartile
range of the matched-star slopes. It also shows the adopted all-reference-star
nightly `k`. Planet colours and camera symbols are the same as in the other
planet figures. The CSV retains sequences that fail a sample, airmass-span, or
matched-star gate with an explicit status, and records how many planet
measurements were removed by the upper-airmass cut.

The standard `plot_ALL_planets.sh` and `go_mmto_photometry.sh` products apply
the two corrections in this order:

```text
m_extinction = m_machine - k_night,band X_planet
m_1,1 = m_extinction - 5 log10(r_sun-planet r_earth-planet)
```

The `--extinction-corrected` command-line mode remains available for a
deliberately extinction-only diagnostic, but it is not the standard batch
product.

The fitted bands are instrumental R/G/B channels, not a transformed
Johnson/Cousins standard system. The formal planet calibration uncertainty is
`X_planet sigma_k`; diagnostic night variability is reported separately.

## Revision note (2026-10-02)

The earlier implementation used a common nightly intercept, effectively
fitting `m_machine - m_catalogue = Z + kX`. That is not the requested system:
catalogue magnitudes are not exact band-specific stellar intercepts, and
between-star brightness differences can bias the slope when stars occupy
different airmass ranges. The current implementation instead solves one
intercept per star and one shared slope per night/band, then applies only the
shared slope to planets. Earlier output directories are preserved as historical
evidence and are not overwritten.

The final real-data calibration is
`results/nightly-extinction/20261002T-fixed-effects-final-code/`, with planet
figures in `results/planet-plots-fixed-effects-final-code/`. It accepted 72
night/band fits and retained 57 insufficient groups, fitted 13,918 stellar
intercepts, and plotted 719 R, 564 G, and 710 B planet measurements. A
row-by-row audit found zero numerical discrepancy from
`m_machine - k X_planet`. The three 2026-09-08 bands are now insufficient
because iterating the image and repeated-star gates leaves fewer than 10
accepted images; no fallback coefficient is substituted.

The correction does not force planet sequences to become flat. In the G data,
the median adopted all-reference-star `k` for the sampled Mars and Saturn
nights is about 0.22 mag/airmass, whereas their raw aperture magnitudes vary by
only about 0.03--0.05 mag/airmass. Their corrected residual trends therefore
have the opposite sign. The brightness-matched diagnostic narrows the
difference: same-frame stars at the planets' count rates have median G slopes
of about 0.04 and 0.03 mag/airmass for Mars and Saturn respectively. Thus the
over-correction is not evidence that `k X_planet` was omitted, nor is it a
generic star-versus-planet difference. It is associated with the measured
brightness regime used to estimate the slope. The diagnostic alone does not
separate detector response from aperture-photometry response.

## Brightness-matched stellar diagnostic (2026-10-08)

The thresholded real-data diagnostic is
`results/planet-brightness-matched-extinction-n10-x5-20261008/`. It audits 273
planet/night/channel/camera sequences after removing 73 planet measurements
above airmass 5. Eighty-seven sequences pass the retained-sample,
airmass-span, and matched-star gates; 175 have fewer than 10 retained planet
measurements, three have less than 0.5 airmass span, and eight have no
qualifying brightness-matched star. The accepted R, G, and B counts are 30,
27, and 30.

Across those accepted sequences, the median raw-planet, brightness-matched
stellar, and adopted nightly slopes are respectively +0.022, -0.052, and
+0.226 mag/airmass in R; +0.038, +0.050, and +0.218 in G; and +0.026, +0.072,
and +0.297 in B. Twenty-nine raw planet slopes and 31 matched-star median
slopes remain negative. Thus the stricter sample and upper-airmass gates remove
short and extreme-airmass fits but do not make negative slopes disappear; the
same behavior is present in equally bright stars. These are sequence medians,
not replacement calibration coefficients. The earlier exploratory four-point,
unbounded-airmass product remains preserved in
`results/planet-brightness-matched-extinction-20261008/`.

## Planet-only nightly airmass correction (2026-10-10)

The direct planet-only diagnostic fits each observing night, channel, planet,
and camera independently.  It reads the raw distance-normalized planet
magnitude, not the stellar-extinction-corrected magnitude or the saved stellar
coefficient.  A Theil--Sen line is accepted only with at least 10 planet
measurements, airmass span at least 0.5, and airmass no greater than 5.  The
accepted correction is referenced to airmass 1:

```text
m_planet_only = m_distance - k_planet,night,band (X_planet - 1)
```

Because one planet track cannot distinguish atmospheric extinction from
detector position, high-signal response, or a time-dependent transparency
change, `k_planet` is recorded as an empirical planet airmass slope rather than
an atmospheric extinction coefficient.  Failed sequences remain in the fit
and measurement audits; no stellar or raw fallback is substituted.

Run the comparison directly from the verified MMTO downloader manifest and
saved blind solutions with:

```sh
./plot_planet_empirical_extinction.sh \
  --database results/stars.sqlite \
  --manifest raw_allsky_samples/manifest.sqlite \
  --output results/planet-empirical-extinction-NEW-UNIQUE-NAME \
  --store-coefficients
```

The v16 `go_mmto_photometry_v16.sh` pipeline always runs this stage with
`--store-coefficients`. The standalone command remains read-only unless that
flag is supplied.

Each R/G/B directory contains `planet_only_airmass_before_after.pdf` and
`planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf`.
The latter reproduces the local-noon-phase view in which the original residual
trend was identified, now using the final planet-only extinction- and
distance-corrected magnitude.  The directories also contain the accepted
corrected measurements, input/correction audits, and the explicitly named
`planet_nightly_empirical_extinction_coefficients.csv`. Its coefficient column
is `planet_empirical_extinction_coefficient_mag_per_airmass`. The 2026-10-10
v16 product is
`results/planet-empirical-extinction-v16-final-snapshot-20261010/`. The manifest
contains 1,530 verified MMTO images; 888 have successful saved blind solutions.
The diagnostic accepts 36 R, 32 G, and 36 B sequences and corrects 687 R, 508 G,
and 687 B measurements.  Image selection no longer depends on an accepted
stellar-extinction sidecar.  The saved stellar-only camera geometry and
photometric zenith are used solely to predict and associate planet positions and
derive planet airmass.  The nightly correction itself uses only each planet's
distance-normalized magnitudes and planet airmasses.

Stored generations are recorded in
`planet_empirical_extinction_generations`; their complete accepted and rejected
fit rows are in `planet_nightly_empirical_extinction_coefficients`. Use
`latest_planet_nightly_empirical_extinction_coefficients` for the newest row per
sequence or `latest_accepted_planet_empirical_extinction_coefficients` for the
accepted subset of those newest rows. This prevents a superseded accepted fit
from appearing current after a newer rejected fit.

At startup, the program makes one standalone SQLite backup named
`input_manifest_snapshot.sqlite` inside the output directory. All three
channels read that same immutable snapshot. Its path and SHA-256 are recorded
in the parent summary and in the database generation, so concurrent downloader
updates cannot mix channel selections or invalidate the recorded provenance.

## Local-noon phase diagnostic (2026-10-03)

The G-band diagnostic in
`results/planet-plots-fixed-effects-local-noon-final-20261003/G/` overlays all
corrected sequences against hours past Arizona local noon and quantifies each
planet/night/camera sequence having at least four points. Of 47 fitted
sequences, 30 have positive and 17 have negative magnitude-versus-hour slopes.
The median slopes are +0.213 mag/hour for Mars (17 nights), +0.040 mag/hour for
Saturn (24 nights), and -0.119 mag/hour for Uranus (6 nights). Thus the
within-night trend is not removed in the planet data. Positive slopes appear
as descending tracks because the magnitude axis is inverted.

## Restored distance-normalized batch product (2026-10-03)

The standard planet batch again applies distance normalization, but only after
the corrected nightly stellar extinction slope has been applied. The verified
real-data output is
`results/planet-plots-fixed-effects-extinction-distance-final-20261003/`.
Its retrievable per-band measurement tables contain 719 R, 564 G, and 710 B
planet rows. Every row stores both `extinction_corrected_magnitude` and
`extinction_corrected_distance_magnitude`, together with the nightly `k`,
planet airmass, both distances, UTC, and provenance. Independent row-by-row
recalculation found zero numerical discrepancy from either correction formula.
