# MMTO nightly extinction calibration

The MMTO extinction workflow is a read-only, repeatable analysis of accumulated
solver results. It derives extinction exclusively from identified stars, writes
new sidecar files, and then lets the planet plotter apply those stellar results
to objects whose intrinsic magnitude is unknown. It does not add columns to or
otherwise modify `stars.sqlite`.

## Run the calibration

From the repository root, with the locked v8a environment available:

```sh
./calibrate_mmto_extinction.sh \
  --database results/stars.sqlite \
  --manifest raw_allsky_samples/manifest.sqlite \
  --output results/nightly-extinction/NEW-UNIQUE-NAME
```

The output directory must be new or empty. Omitting `--output` creates a
timestamped directory beside the database. The command opens the database in
SQLite read-only/query-only mode and works from one transaction snapshot.
Re-run it occasionally as more nights accumulate; do not reuse an old output
directory.

MMTO images and corrected UTC midpoints are selected by exact source-SHA matches
to verified downloader-manifest rows. Nights use the Arizona local-noon bucket.
The calibration uses the saved, blind-solution airmass and never recomputes
airmass from site/time metadata.

For each image and camera channel R, G, or B, the adopted reference fit is

```text
m_machine - m_catalogue = Z_image + k_image X
m_machine = -2.5 log10(count_rate_adu_per_s)
```

Only stars with catalogue magnitude below 4.0, at least 10 valid observations
in that night/channel, known-unsaturated ordinary-aperture photometry, and
saved airmass `X <= 5` enter the adopted fit. Each image needs at least 30 such
stars and an airmass span of at least 1.0. A night/channel needs at least 10
accepted images. Failed gates remain visible as insufficient or excluded rows;
the code does not silently admit fainter stars or reduce the sample thresholds.

Each image is fitted with robust Theil--Sen regression using the joint-median
intercept. The adopted nightly coefficient is the ordinary, unweighted median
of those accepted per-image robust slopes:

```text
k_night = median(k_image)
```

Its scaled MAD records real image-to-image variability and is not divided by
the square root of the image count. Unweighted OLS, repeatability-weighted
bright-star fits, weighted magnitude 4--5 fits, and full-airmass OLS fits are
sensitivity diagnostics only. They never replace `reference_theil_sen` in
corrected magnitudes.

After fixing `k_night`, every accepted image gets a new fixed-slope stellar zero
point from the median stellar offset; its uncertainty uses the scaled MAD. This
keeps a single bad calibrator from shifting every corrected object in the image.
Corrected stellar or planetary magnitudes use

```text
m_corrected = m_machine - Z_fixed - k_night X_object
```

Planets do not enter the image slopes, nightly medians, stellar weights, or zero
points.

## Inspect the outputs

The sidecar contains:

- `calibration_manifest.json`: provenance, exact thresholds, formulae, selected
  run IDs, catalogue checksums, and aggregate statuses;
- `image_extinction_fits.csv`: every image/channel/model slope, intercept,
  uncertainty, RMS, star count, leverage, and acceptance status;
- `nightly_extinction_coefficients.csv`: nightly R/G/B medians, scaled MADs,
  ranges, image counts, and insufficient-data statuses;
- `image_zero_points.csv`: the adopted fixed-night-slope image zero points;
- `calibration_star_measurements.csv`: the complete inclusion/exclusion and
  residual audit trail;
- `corrected_stellar_photometry.csv`: raw and corrected stellar magnitudes with
  coefficient and zero-point provenance;
- `extinction_diagnostics.pdf`: the overall fit-quality dashboard; and
- `extinction_by_band_and_night.pdf`: separate R/G/B time plots of
  every accepted per-image `k`, with nightly median and scaled-MAD error bars,
  plus an aligned curve of nightly scaled MAD for each band.

Rows lacking an accepted nightly coefficient or image zero point have no
corrected value and state why. Consumers must not substitute a raw machine
magnitude into a corrected product.

The catalogue reference is the stored Gaia G / bright Tycho-Hipparcos
supplement, not a native R, G, or B standard-system transformation. Consequently
the fitted channel coefficients can retain colour terms, and the outputs must
not be described as Johnson/Cousins calibrated photometry. Vignetting, clouds,
aperture effects, catalogue mismatch, and near-horizon nonlinearity can also
appear in the image slopes and their scatter.

## Plot calibrated planets

Pass one completed sidecar explicitly:

```sh
./plot_ALL_planets.sh \
  --database results/stars.sqlite \
  --nightly-calibration results/nightly-extinction/NEW-UNIQUE-NAME \
  --output results/planet-plots-nightly-NEW-UNIQUE-NAME
```

The calibrated join is exact in source SHA-256, catalogue SHA-256, observing
night, and channel. The plotter uses only an accepted `reference_theil_sen` nightly
coefficient and its corresponding fixed-slope image zero point. Missing joins,
invalid planet airmass, or unreproducible saved aperture fluxes are written to
`planet_extinction_correction_audit.csv` and omitted. There is no fallback to a
legacy same-image coefficient or raw magnitude.

Each R/G/B directory contains the extinction-corrected, distance-corrected
PDF, the plotted measurement CSV, the full calibration audit, and a JSON
summary. The plotted CSV retains machine magnitude, stellar calibration terms,
planet airmass, corrected magnitude, distance correction, uncertainty
components, and sidecar path. Planetary distance normalization is applied after
the stellar atmospheric correction and remains a separately named quantity.

For extinction-corrected plots, the plotter re-associates the saved detections
downstream at the trusted downloader-manifest UTC carried by the sidecar. It
uses the immutable stellar-only camera solution and saved image-derived zenith;
it does not refit the camera or write the association to `stars.sqlite`. This
metadata-conditioned identification is deliberately separate from the blind
planetary epoch result. A blind `selected_planet_match` belongs to its fitted
historical epoch and is never attached to the image's metadata timestamp.

The exact manifest time is used when available. The MMTO use case only requires
the metadata clock to be right within a few hours, but using its corrected UTC
avoids adding an unnecessary timing approximation. Every plotted identity is
stored as `metadata_time_match`; the writer also verifies that its UTC agrees
within 60 seconds with the sidecar UTC. Identity or time-provenance failures are
explicit audit exclusions.

## Current data audit (2026-09-27 snapshot)

The inspectable run in
`results/nightly-extinction/20260927-robust-theil-sen/` found 39 accepted and 33
insufficient night/channel combinations from 823,778 valid stellar channel
measurements. All accepted reference stars are brighter than magnitude 4.0 and
have at least 10 observations; accepted image fits have at least 30 stars and
an airmass span above 1.0.

The accepted robust nightly medians span 0.179--0.473 in R, 0.175--0.418 in G,
and 0.272--0.560 mag/airmass in B. Across the 39 accepted groups, the median
Theil--Sen-minus-OLS shift is +0.017 mag/airmass, with a range from -0.031 to
+0.095. The band/night plot shows substantial early-night
instability from 4--14 September, including individual negative slopes and
slopes above 1 mag/airmass. The 12 September medians are elevated in all three
bands (R 0.473, G 0.418, B 0.560), and 14 September has unusually large scaled
MADs (R 0.348, G 0.316, B 0.280). Most 17--25 September sequences are tighter,
although 21 September and the B data on 25 September retain appreciable
scatter. These are flags for scientific inspection, not grounds for automatic
clipping or changing the adopted estimator.

Inspection of the first planet batch exposed an epoch-provenance error: its
September points used blind planet identities fitted at unrelated historical
epochs, then attached 2026 timestamps and distances. Those plots are not valid
planet photometry. The corrected metadata-time pass processes all 298 images
with accepted G sidecar rows: 255 images contain at least one associated planet,
43 have no source match, and there are 398 matched detections. Of these, 316 have
usable unsaturated ordinary-aperture G photometry: Saturn 200, Mars 63, Uranus
47, Vesta 5, and Jupiter 1. No Venus detection is present. The source database
also yields 394 usable R points and 388 usable B points. The final plots and
tables are in
`results/planet-plots-extinction-corrected-20260927-robust/{R,G,B}/`. The source
database SHA-256 remained
`cc4a81f8897eba1d111438e7b4d79fdf92a5884101bc1a87e5ae1813dabb89db`
before and after sidecar generation and plotting.
