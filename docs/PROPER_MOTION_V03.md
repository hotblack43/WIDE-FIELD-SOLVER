# Version 0.3.0: proper motion in the saved point-source solution

This development version is isolated on `feature/proper-motion-v0.3`. Version
0.1.0, the original checkout, the catalogue CSV, example image and historical
reference products remain unchanged. The separate magnitude-depth experiment
has a v2 branch; version 0.3.0 identifies this proper-motion work.

## Running it

From this version's checkout:

```sh
./solve.sh image.jpg --output results/new-epoch-fit --offline
./solve.sh image.jpg --output results/new-fixed-epoch --offline \
  --epoch-mode fixed --epoch-year 2026.7
./analyse.sh image.jpg --output results/new-science-report --offline
./demo.sh --output results/new-baseline-replay
```

The first and third commands infer stellar epoch without using an image timestamp.
The second uses an explicitly supplied Julian year. The fourth tests the preserved
native-catalogue method. Outputs must be new directories unless `--overwrite` is
explicitly supplied. Historical example/data trees and input-containing outputs
remain protected even with that flag. No detection, name, cached association or saved solution is
used to bypass blind bootstrap.

## Numerical changes and reasons

`point_star_epoch.Catalogue` propagates every valid proper-motion pair from its
own reference epoch. The calculation is a Cartesian linear tangential displacement,
normalised back onto the unit sphere. `pm_ra_cosdec_mas_per_year` already includes
cos(dec). All positions remain in ICRS axes; propagation does not rotate the
coordinate frame. Tests compare with Astropy space-motion calculations, including
near-pole positions, RA wraparound and mixed 1991.25/2000/2016 reference epochs.
This seven-column catalogue does not supply parallax or radial velocity, so annual
parallax, radial/perspective motion and catalogue covariance are not modelled.

Both missing components and partially missing proper-motion pairs are flagged.
Such stars use a stationary approximation; they are not removed or assigned a
fictitious measured zero motion. Non-finite astrometry is rejected.

In fitted-epoch mode, progressive initial matching uses positions propagated to
J2000.0. Each epoch profile then uses all current associations with the existing
Barghini robust unit-vector objective. Camera parameters are refitted at each
trial year; detection membership stays fixed within a profile. Twenty-one coarse
epochs span the user-supplied interval (default 1850–2150), followed by bounded
refinement of sampled minima, including one-sided endpoint brackets. Difficult
trial fits may use up to 2000 optimizer evaluations; failure remains explicit.

The profile scorer includes the same soft-L1 loss and radial monotonicity penalty
as the camera optimizer. It evaluates the equivalent stable expression
`r²/(sqrt(1+r²)+1)` rather than subtracting nearly equal numbers. The plotted
profile is this robust objective, not a different RMS objective. Pixel RMS is
also retained numerically. Parameter bounds and baseline regression thresholds
are unchanged.

An approximate 95% conditional interval uses an increase in robust cost of
`1.920729410347062 × fitted residual variance`. Residual variance uses the robustly
weighted squared vector residuals and `2N−9` nominal degrees of freedom. This is
an approximate local likelihood interpretation, not a calibrated guarantee for
heteroscedastic wide-field images. The interval assumes the associations, catalogue
motions and lens model; catalogue errors, refraction, blending and model bias are
not included. Closed single-component profiles away from the boundaries are
labelled `conditional_epoch`; open, boundary, flat and competing profiles remain
`not_identifiable`. For unresolved cases with a non-flat profile the saved solution retains the
numerical minimum and marks the adopted epoch as provisional, not a measured date.
Zero-motion and numerically flat profiles explicitly adopt J2000.0. This separates
the best numerical camera fit from the strength of the stellar-date claim.

Between profiles all detections are reassociated using propagated positions.
The process must reach identical associations within six profiles or fail explicitly.
No stars are withheld. The retained camera is the fit at the epoch actually used
for the final stable associations. No astronomical position or measured centroid
is shifted cosmetically.

## Saved-coordinate contract

- `result.json`: version, final camera, fit residuals, coordinate frame/epoch,
  and the same `stellar_epoch` record written to `stellar_epoch.json`.
- `catalog_ra_deg`, `catalog_dec_deg`: original, unmodified catalogue coordinates.
- `propagated_ra_deg`, `propagated_dec_deg`: catalogue positions actually used by
  the final camera; `coordinate_epoch_jyear` records the adopted epoch.
- `reference_epoch_jyear`, `proper_motion_available`: source epoch and motion flag.
- `measured_ra_deg`, `measured_dec_deg`: inverse projection of measured centroids
  through that final camera.
- Predicted pixels and residuals are computed directly from propagated catalogue
  positions and that camera. Large/saturated-source coordinates use the same camera.

The regression test reloads the saved camera, independently regenerates the
propagated sky using Astropy, and reproduces the exported pixels and residuals.
Science analysis consumes this solution, including its propagated positions for
refraction targets and airmass. It does not rerun the old split-sample epoch fit.
Atmospheric and planetary analyses remain conditional downstream diagnostics;
this change does not claim they remove the systematic errors of the stellar clock.

## Validation

The historical demo passes with 3653 associations, RMS 0.397892 px, 40 labels and all
unchanged baseline thresholds. A fresh blind version 0.3 solve of the same image
also yields 3653 associations, RMS 0.397811 px. It uses a conditional stellar epoch
J2024.96, with approximate conditional 95% interval 2002.62–2046.93. That broad
interval is not an independently verified date for the example photograph.
Of its associations, 3488 have complete proper-motion pairs and 165 have flagged
missing motion. All 3653 are fitted. The small RMS change alone is not proof of
improved physical accuracy.

Synthetic checks recover a known stellar epoch and distorted camera, cover fixed
and unresolved modes and minima just inside search boundaries, and verify saved
coordinate consistency and output protection. The full unit suite and fresh
historical demo are required before committing this version. Gaia remains future
work; neither Gaia data nor new runtime dependencies have been introduced.
