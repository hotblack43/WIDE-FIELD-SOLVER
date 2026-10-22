# V22 Better Planet Photometry

Date: 2026-10-22
Status: design approved; implementation not started

## Aim

Build v22 without changing v21. Use stars in each image to estimate the total
unwanted brightness pattern caused by haze, airmass, vignetting, PSF changes,
aperture loss, and background. Subtract that estimate from planet measurements.

The result is **relative instrumental planet photometry**, not calibrated
planet magnitudes and not a claim to have measured physical extinction alone.

## Why v21 is not enough

V21 fits one nightly stellar coefficient times airmass. In a fisheye image,
airmass and distance from the centre change together. Detector and PSF effects
therefore enter the same fitted coefficient. Similar-brightness stars help with
count level, but do not guarantee the same colour, PSF, or detector path as a
planet.

The zenith estimate is not the main problem: it is close enough to the image
centre for this data set.

## Methods to compare

1. Raw aperture photometry.
2. The existing v21 stellar-extinction correction, as a control only.
3. A robust local-star correction using other stars in the same exposure.
4. Random forest.
5. Gradient-boosted trees.
6. A small neural network.

The simplest method that passes the tests wins. Neural networks receive no
preference. No convolutional network or raw-pixel model is included initially.

## Information the models may use

- image `x`, `y`, radius, azimuth, and image-derived airmass;
- a star's training-derived normal brightness;
- source shape, aperture size, background, uncertainty, and exposure time;
- median and scatter of other stars in the exposure;
- median, scatter, and count of nearby comparison stars at several distances;
- stellar colour for diagnosis.

The planet-deployable model may not assume a Gaia stellar colour for a planet.
It may not use target identity, sky coordinates, observing night, expected
planet behaviour, future data, or the target's current magnitude as a feature.

## Fair test

Treat selected stars as fake planets:

- keep whole nights out of training;
- keep each fake planet's identity out of training;
- exclude the fake planet from all same-image comparison summaries;
- tune models only on training and validation data;
- open the final test once, after the method is fixed.

Also inject known trends and sinusoidal signals into fake planets. The
correction must preserve their amplitude; median attenuation must be below 5%.

## Pass conditions

A method may be applied to planets only if it:

- improves held-out error and robust scatter over raw data and v21 in R, G,
  and B;
- improves the brightness and image-radius ranges occupied by planets;
- reduces residual trends with airmass, radius, colour, brightness, PSF, and
  background;
- has a statistically supported improvement, not only a better point value;
- preserves injected signals;
- flags unsupported cases instead of extrapolating silently.

Numerical thresholds other than the 5% signal test will be fixed on development
data before the final test is opened. They will not be weakened after failure.
If nothing passes, v22 reports that no defensible correction is available.

## Planet output

Train only on stars. After the test is frozen, apply the winning model to
planets and retain, side by side:

- raw aperture magnitude;
- v21 correction for comparison;
- v22 relative corrected magnitude;
- optional observer-distance normalization, kept separate.

Network failure must not destroy completed photometry. Cached ephemerides are
used when present; unavailable distance correction gets an explicit status.

## Version and products

Create a separate `v22/` runtime, lockfile, catalogue, ephemeris data, source
manifest, and `go22.sh`, `go_v0.22.0.sh`, and
`go_mmto_photometry_v22.sh`. Preserve all earlier versions byte for byte.

The first v22 stage is a read-only benchmark using the existing database. It
writes the exact input run list, exclusions, fixed train/test assignments,
model metrics, fake-planet predictions, signal-recovery results, and diagnostic
figures. It writes corrected planet curves only when a method passes.

Every corrected point has one status: `corrected`,
`insufficient_local_stars`, `out_of_domain`, `invalid_measurement`, or
`model_unavailable`. Raw measurements are always retained.

## Verification

Tests must prove there is no target or night leakage, the database is read-only,
splits and results are reproducible, injected variability survives, unsupported
cases are labelled, and frozen versions remain unchanged. Completion also
requires the full unit suite, root demo, v22 demo, and a read-only benchmark on
the current MMTO database.
