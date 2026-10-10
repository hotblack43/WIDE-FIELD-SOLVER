# V16 Planet-Empirical Extinction Design

## Objective

Version 16 preserves the complete v15 solver and adds an MMTO pipeline stage
that derives nightly empirical airmass coefficients from planets alone.  The
stage writes the existing audit tables and figures, including the local-noon
diagnostic, and stores immutable coefficient generations in the shared
`results/stars.sqlite` database.

V15 and every older runtime and launcher remain unchanged.

## Scientific terminology

The fitted quantity is named
`planet_empirical_extinction_coefficient_mag_per_airmass`.  It is the
Theil-Sen slope of distance-normalized instrumental planet magnitude against
planet airmass, fitted separately for observing night, channel, planet, and
camera.  It is empirical because a single planet track cannot distinguish
atmospheric extinction from detector position, high-signal response, or a
time-dependent transparency change.

An accepted fit requires at least 10 usable measurements, airmass span at
least 0.5, and airmass no greater than 5.  The corrected quantity is

```text
m_planet_corrected = m_distance
                     - k_planet_empirical (X_planet - 1)
```

No stellar photometry, stellar extinction coefficient, or stellar-fit
acceptance selects or fits these coefficients.  Saved stellar astrometry and
photometric zenith remain legitimate geometry for planet association and
planet airmass.

## Shared-database model

The standalone command remains read-only unless explicitly given
`--store-coefficients`.  The v16 MMTO pipeline always supplies that flag.
Database writes occur only after all three channel products have been
successfully generated, in one immediate transaction.

`planet_empirical_extinction_generations` stores one immutable generation:

- generation UUID and UTC creation time;
- method and formula;
- manifest path and SHA-256;
- output path;
- fit gates and aggregate source counts; and
- producer version `0.16.0`.

`planet_nightly_empirical_extinction_coefficients` stores every accepted or
rejected fit row keyed by generation, night, channel, planet, and camera.  Its
coefficient column is named
`planet_empirical_extinction_coefficient_mag_per_airmass`; confidence bounds
use the same explicit prefix.  It also stores fit status, counts, airmass
range/span, intercept, and reference airmass.

`latest_planet_nightly_empirical_extinction_coefficients` exposes the newest
row for each night/channel/planet/camera.  A second view,
`latest_accepted_planet_empirical_extinction_coefficients`, exposes only
accepted rows with finite coefficients.  Historical generations are never
updated or deleted.

The extension tables do not change the solver database application ID or
schema version.  They are downstream evidence and never solver input.

## V16 boundary and pipeline

The complete v15 package is frozen in `docs/v15-runtime.json`.  V16 receives a
self-contained `v16/` package, `go16.sh`, and `go_v0.16.0.sh`; its solver
behavior initially matches v15 apart from version identity.

`go_mmto_photometry_v16.sh` launches
`scripts/run_mmto_photometry_pipeline_v16.py`.  The pipeline:

1. processes the newest incomplete v16 MMTO night with `go16.sh`;
2. rebuilds the existing stellar light curves, stellar nightly extinction,
   and stellar-corrected planet products;
3. runs the planet-only empirical-extinction stage from the verified MMTO
   manifest;
4. writes the coefficient generation to the shared database; and
5. lists all figures, including the airmass and local-noon products.

The new stage is required: failure leaves the pipeline summary failed and no
partial coefficient generation is committed.  Existing v15 pipeline behavior
and receipt selection remain unchanged.

## Outputs and verification

Each channel retains the nightly-fit CSV, corrected measurement CSV, complete
association audits, airmass before/after PDF, and final corrected magnitude
versus hours past Arizona local noon PDF.  Names in CSV, JSON, documentation,
and SQLite use the explicit empirical-planet coefficient terminology.

Tests cover coefficient naming and arithmetic, atomic database persistence,
history and latest views, failed-fit rows, non-mutating default CLI behavior,
v16 receipt selection, pipeline stage wiring, launcher portability, frozen v15
hashes, v16 package independence, and all preserved-version checks.
