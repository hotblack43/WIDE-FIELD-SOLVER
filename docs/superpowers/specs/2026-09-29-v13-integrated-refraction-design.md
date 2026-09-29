# V13 Integrated Refraction Design

## Purpose

Create a self-contained v13 solver that fits atmospheric refraction inside the
robust Barghini astrometric loop and propagates that fitted model into saved
coordinates and projections. Preserve every earlier runtime, including the
experimental v12 radial-model study, byte for byte.

## Version and workflow boundary

- Add the complete existing v12 snapshot to `main` as versioned code and freeze
  it with a runtime hash manifest. Do not modify its contents.
- Develop the new behavior only in `v13/`, with `go13.sh` and
  `go_v0.13.0.sh`.
- Work directly on `main` because the investigator explicitly prohibited
  development branches. Never overwrite an earlier version or historical
  example/reference product.
- Use robust radial soft-L1 least squares throughout. OLS is not part of the
  v13 astrometric, refraction, or validation path.

## Coupled model

Once blind pattern matching has supplied associations, the fitted parameter
vector contains the eight Barghini O/Z lens-and-attitude terms, two angles for
the physical refraction zenith, and the two coefficients in
`R(z) = A tan(z) + B tan(z)^3`.

For each trial parameter vector, detector centroids are mapped through the
Barghini equations to apparent camera rays. Catalogue directions are rotated
into the same camera frame and refracted towards the fitted physical zenith.
Their two-dimensional angular differences supply one rotationally invariant
soft-L1 contribution per star. Lens monotonicity and the valid atmospheric
domain remain explicit constraints.

The bootstrap remains refraction-free because it has neither reliable
identities nor physical-zenith information. The first stable full-field
association seeds the joint model. Every subsequent camera refinement,
proper-motion epoch profile, and reassociation iteration co-fits refraction.

## Authoritative coordinates

The v13 camera serialization records the zenith and both refraction
coefficients. `project()` applies refraction before the Barghini detector
projection. `to_sky()` removes it before producing catalogue-frame directions.
Thus CSV coordinates, residuals, FITS/WCS products, planet projections and
overlays all use one model. Measured centroids never move.

Refraction is adopted only when deterministic spatially blocked robust
validation improves over the nested zero-refraction model and the solution is
inside its bounds. Otherwise v13 records an unresolved result and refits with
exactly zero refraction; failure never silently falls back to a nonzero model.

## Tests and real-image evidence

Synthetic tests cover exact zero refraction, injected A/B recovery, forward and
inverse projection consistency, serialization, outliers, saved-coordinate
propagation, and zero-model fallback.

Real-image comparison uses already-solved, full-fisheye solutions from four
independent families: MMTO, APICAM, Subaru/Maunakea and the historical full-sky
fisheye examples. It excludes the 488x652 Zenodo frames, Rubin camera frames,
and other small or non-fisheye fields. Selection uses saved source checksums and
footprint/field coverage, never metadata-derived site or time.

For each family, compare the inherited model and integrated-refraction model on
association count, robust full-sample angular residuals, deterministic held-out
spatial-block residuals, convergence, fitted parameter bounds and within-family
stability. Retain every failure and do not relax existing regression thresholds.

## Success boundary

V13 is successful when synthetic refraction is recovered without bias from
outliers, zero-refraction data returns the nested zero model, saved coordinates
and projections use the adopted correction, preserved runtimes remain unchanged,
and the multi-family report honestly shows improvements, neutral cases and
failures. The evidence need not show that every camera benefits.
