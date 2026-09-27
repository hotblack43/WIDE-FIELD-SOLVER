# MMTO Nightly Extinction Calibration Design

Date: 2026-09-27

## Purpose

Derive per-image atmospheric-extinction diagnostics and nightly per-channel
extinction coefficients from identified stars in accumulated MMTO images. Use
those stellar solutions to produce catalogue-referenced magnitudes for stellar
and planetary measurements without requiring a known intrinsic planet
magnitude.

This is downstream, repeatable analysis of the run database. It does not alter
the blind solver, its fitted coordinates, a preserved version package, or the
run database.

Success means that an investigator can:

- inspect how the fitted extinction coefficient changes through each night;
- see the nightly median and its robust scatter independently in R, G, and B;
- audit every included and excluded calibration-star measurement;
- regenerate the products as more MMTO images accumulate; and
- plot planets using stellar-derived, catalogue-referenced magnitudes rather
  than raw instrumental magnitudes.

## Scientific model

For one image `i`, stellar source `s`, and stored channel `c`, define

```text
delta_m[s,i,c] = m_machine[s,i,c] - m_catalogue[s]
```

`m_machine` is always recomputed as `-2.5 log10(count_rate_adu_per_s)` from a
positive, ordinary-aperture count rate. It is not the older flux-based value
whose zero point changes with exposure duration.

The per-image reference fit is

```text
delta_m[s,i,c] = Z[i,c] + k[i,c] X[s,i]
```

where `X` is the saved image-derived airmass, `Z` is the image zero point, and
`k` is the image's extinction slope in magnitudes per airmass. R, G, and B are
fit independently. The catalogue magnitude is a heterogeneous Gaia G / bright
Tycho-Hipparcos supplement rather than a native match to every camera channel;
therefore `k` is an empirical channel coefficient with explicit passband and
colour limitations.

The sequence of accepted `k[i,c]` values is the within-night extinction
stability diagnostic. The adopted nightly coefficient is the ordinary median
of accepted image coefficients:

```text
k_night[n,c] = median_i(k[i,c])
```

The output also records the scaled MAD, range, image count, and individual fit
uncertainties. Images are not weighted when taking this median: each accepted
20-minute-cadence image contributes one value.

The scaled MAD describes real image-to-image stability and is not divided by
the square root of the image count or presented as an independent formal error.
Fit covariance, fixed-slope zero-point uncertainty, planet measurement
uncertainty, and nightly coefficient scatter remain separate output columns so
later plots can state exactly which components they combine.

After fixing `k_night`, refit each image's zero point from its stellar
calibrators while holding the slope fixed. The catalogue-referenced magnitude
for any measured object `o`, including a planet with no catalogue magnitude, is

```text
m_corrected[o,i,c] = m_machine[o,i,c] - Z_fixed[i,c]
                     - k_night[n,c] X[o,i]
```

Planet magnitudes never enter either the image fits or the nightly median.

## Input boundary and night grouping

The analysis opens the existing run database read-only and uses one consistent
transaction snapshot. It selects the latest successful run for each distinct
`(source_sha256, catalogue_sha256)` image/catalogue pair before applying
photometry cuts, so reruns cannot inflate the sample or replace a good older
measurement after quality filtering.

MMTO membership and UTC exposure midpoint come from source-hash matches to the
downloader manifest, following the existing MMTO light-curve convention. The
observing night is the Arizona local-noon to following-local-noon bucket. This
metadata is used only after the blind per-image results are fixed and cannot
alter source association, astrometry, physical-zenith inference, or saved
airmass.

The analysis uses saved image-derived airmass. It must not recompute stellar
airmass from known MMTO site coordinates or observation time.

## Reference calibration-star population

Eligibility is evaluated separately for every night and channel. A star enters
the reference pool when all of these hold:

- it has a finite catalogue magnitude below 4.0;
- it has valid measurements in at least 10 distinct images during that night;
- saturation is known and false in the fitted channel;
- the channel measurement method is the ordinary aperture method;
- the channel count rate and saved airmass are positive and finite; and
- its catalogue identifier and catalogue checksum are present.

The ten-observation rule is the primary repeatability requirement. A companion
diagnostic reports the population that would survive a twelve-observation
requirement, but twelve is not the default because it needlessly removes useful
partly accumulated nights.

The magnitude limit is not silently relaxed. A night or image with too few
reference stars is marked insufficient. Measurements remain in audit output
with their exclusion reasons.

The reference image fit uses stars with `X <= 5`. Higher-airmass measurements
remain in the audit table, and a full-airmass sensitivity fit is reported, but
they do not control the adopted linear coefficient. This calibration-stage
choice is separate from the fixed full-horizon sample required by the blind
photometric-zenith fit.

An image fit is accepted only with at least 30 reference stars and an airmass
span of at least 1.0. A nightly coefficient requires at least 10 accepted image
fits in that channel. These gates are fixed and reported; no automatic fallback
admits fainter stars or reduces the repeat-count requirement.

## Reference and sensitivity fits

Unweighted ordinary least squares on the bright reference population is the
authoritative first implementation. It saves the intercept, slope, covariance,
RMS, sample count, airmass range, and every residual.

Two non-authoritative sensitivity products assess whether later weighting or a
deeper sample is beneficial:

1. A repeatability-weighted fit on the same bright population. Per-star scatter
   is estimated from robust, night-centred residuals after the initial image
   fits. Inverse-variance weights have a documented floor and cap so one star
   cannot dominate. The reference OLS result remains visible alongside it.
2. A weighted extension admitting catalogue magnitudes from 4.0 through 5.0.
   It is diagnostic only. It cannot supply `k_night` or corrected magnitudes in
   this first version.

The comparison reports coefficient shifts, formal uncertainty, residual RMS,
and time-series scatter. Moving the weighted or deeper result into the adopted
path requires a later explicit decision supported by these diagnostics and new
regression evidence.

## Sidecar outputs

Each execution creates a new output directory and refuses to overwrite a
nonempty directory. The run database remains unchanged. Outputs include:

- `calibration_manifest.json`: database/manifest provenance, snapshot time,
  selection constants, formulae, catalogue hashes, and aggregate status;
- `image_extinction_fits.csv`: one row per image/channel/model with free `Z`,
  `k`, uncertainties, RMS, counts, airmass leverage, and acceptance status;
- `nightly_extinction_coefficients.csv`: adopted channel medians, robust
  scatter, ranges, image counts, and insufficiency reasons;
- `calibration_star_measurements.csv`: every candidate measurement, input
  values, inclusion flags, exclusion reasons, residuals, and sensitivity
  weights;
- `image_zero_points.csv`: fixed-night-slope image zero points and their
  uncertainty/status;
- `corrected_stellar_photometry.csv`: raw and corrected channel magnitudes,
  airmass, coefficient/zero-point provenance, and uncertainty components; and
- PNG/PDF diagnostics showing `k` and `Z` versus UTC through the night,
  OLS-versus-weighted comparisons, coefficient distributions, residuals versus
  airmass, residual scatter versus catalogue magnitude, and calibrator counts.

Rows without a valid nightly coefficient or image zero point remain in audit
tables with a reason and have no corrected magnitude. No consumer may silently
substitute the raw machine magnitude.

## Planet-photometry integration

The existing planet plotter gains an explicit nightly-calibration input. It
joins an image solution by source checksum, catalogue checksum, night, and
channel, then evaluates the star-derived solution at the planet's saved
image-derived airmass. Planet identity, flux, saturation, exposure, distance
correction, and measurement-uncertainty rules remain unchanged.

The plotter exports both the raw machine magnitude and the new
catalogue-referenced magnitude with provenance. Its corrected plot uses only
the latter. Missing calibration, invalid planet altitude/airmass, or unusable
planet photometry excludes the plotted point with an explicit audit reason.
There is no fallback to the same-image legacy coefficient or raw magnitude in
the nightly-corrected product.

Distance normalization, when requested, is applied after stellar calibration
and remains a separately named value. Atmospheric correction and planetary
distance correction must not be conflated.

## Failure handling and reproducibility

Malformed JSON, conflicting manifest times, duplicate stellar rows, catalogue
checksum changes within a fitted population, or non-finite inputs produce
explicit failures or audited exclusions; they are never guessed. A database
snapshot may contain incomplete nights, which are expected to report
`insufficient_data` without affecting successful nights.

Every numerical output records the formulas, thresholds, channel, catalogue
provenance, selected run IDs, source hashes, and software revision. Ordering is
deterministic. Reprocessing an unchanged database snapshot and manifest must
produce identical CSV/JSON scientific values.

## Tests and acceptance evidence

Unit and integration tests will cover:

- recovery of known per-image `Z` and `k` and the nightly median from synthetic
  stars;
- changing image extinction and changing transparency as distinct effects;
- catalogue/channel colour offsets and the documented residual scatter;
- channel-specific saturation and ordinary-aperture requirements;
- the ten-observation, magnitude, star-count, airmass, and image-count gates;
- no silent faint-star or high-airmass fallback;
- latest-successful-run deduplication before quality cuts;
- weighted sensitivity products that cannot replace the reference result;
- planet correction without any known planet magnitude;
- missing-calibration and invalid-airmass audit paths;
- exact read-only treatment of the source database; and
- coexistence with the current planet-photometry and MMTO light-curve outputs.

Before completion, run the focused extinction/planet tests, the complete frozen
unit suite, the required root unit discovery, and the unique-name demo. Inspect
generated night plots for coefficient stability, sufficient calibrator counts,
and agreement or disagreement between the reference and sensitivity fits.

## Preliminary data evidence

The current database contains a complete 32-image MMTO night on 2026-09-25.
For G-channel clean aperture measurements, requiring at least 10 observations
and catalogue magnitude below 4 leaves 231 recurring stars. Individual images
retain 102 to 147 of them, and their airmass spans range from 2.37 to 5.21.
R and B provide effectively identical population counts. Thus the initial
bright reference path has ample leverage without magnitude 4--5 stars.

Across accumulated nights, a twelve-observation threshold is unnecessarily
restrictive for some partial nights. Nights with fewer than ten accepted image
fits remain uncalibrated until additional images are processed.

## Non-goals

- Do not modify `stars.sqlite` or add calibration columns to its schema.
- Do not change the blind photometric-zenith fit or its required stellar sample.
- Do not use planets to estimate extinction, zero point, or stellar weights.
- Do not claim a transformation to a standard Johnson/Cousins passband.
- Do not overwrite or repoint any preserved launcher or version package.
- Do not hide colour terms, vignetting, clouds, or near-horizon limitations.
