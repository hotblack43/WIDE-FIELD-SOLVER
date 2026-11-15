# Find Planet v1: controlled anonymous-orbit experiment

This independent runtime asks a deliberately narrow first question: if the
MMTO measurements belonging to one known moving object are selected first,
can their measured centroids alone constrain and predict a heliocentric orbit?
The selector is knowingly non-blind. After selection it writes `Object A`
directions and passes no object name, predicted coordinate, known distance,
known element, or Horizons value to the fitter.

Run the pinned controlled experiment from the repository root:

```sh
./go_find_planet_controlled_v1.sh \
  --audit results/photometry-runs/v23-20261027T050447Z/planet-empirical-extinction/B/planet_only_airmass_correction_audit.csv \
  --database results/stars.sqlite
```

Every invocation creates a new directory under `results/find-planet-v1/` and
refuses an existing run name. It reads the audit and SQLite database without
modifying them. `answer_key_selection.csv` retains the explicitly revealed
selection; `fit_input_manifest.json` and `observations.csv` describe the
separate identity-free input.

## What is fitted

- Saved Barghini cameras turn unchanged measured centroids into vacuum ICRS
  unit directions. Integrated refraction is removed exactly once.
- Exposure midpoints are converted from UTC to TDB. The observer state uses
  ERFA `epv00` for Earth and the fixed MMTO topocentre; no general planetary
  ephemeris is available to the fitter.
- Deterministic range/range-rate seeds cover declared bound-orbit limits. A
  robust nonlinear fit propagates a heliocentric Cartesian state with
  Sun-only two-body dynamics and iterative one-way light time.
- Every fifth chronological observing night is withheld whole. The orbit is
  scored on those same rows and uncertainties as a fixed-direction baseline
  and a constant-angular-velocity baseline.
- The primary uncertainty uses the saved stellar RMS with a one-arcminute
  floor. Half- and double-sigma fits are sensitivity checks only. Local
  covariance rank and a deterministic whole-night bootstrap are reported;
  weak geometry is labelled unresolved instead of receiving spurious digits.

## Interpret the status, not optimizer completion

`predictive` means the selected orbit family beats both held-out baselines and
has supported uncertainty. `not_predictive` means a fit exists but fails that
prediction gate. `unresolved` means no admissible family or no defensible
uncertainty statement was obtained. All three are valid scientific outcomes
and return operational success when the evidence package is complete.

Inspect `orbit_sky_track.png`, `orbit_residuals.png`, and
`heliocentric_orbit.png` beside their exact backing CSV files. Residuals are
shown at ×1 with no cosmetic shifts. `candidate_orbits.csv`,
`orbital_elements.csv`, `covariance.csv`, `bootstrap_elements.csv`, and
`fit_summary.json` carry the numerical result. `seal.json` hashes every product
and the input provenance; `verify_seal` detects later mutation.

This stage cannot by itself identify Object A as Mars or claim blind
rediscovery. Known-object comparison belongs to a later, separately executed
stage after the anonymous result is sealed. The existing `go.sh`, `go4.sh`
through `go23.sh`, all `v4/` through `v23/` runtimes, databases, MMTO inputs,
and historical reference products are outside this runtime and remain
untouched.
