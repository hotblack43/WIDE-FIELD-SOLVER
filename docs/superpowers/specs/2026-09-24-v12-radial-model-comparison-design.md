# V12 Nested Radial Model Comparison Design

## Purpose

Determine whether residual radial structure in previously solved point-source
images justifies extending the present eight-parameter Barghini camera model.
The comparison must charge every added radial coefficient as a fitted degree of
freedom, distinguish in-sample improvement from spatial prediction, and retain
all failures. A lower fitted RMS alone is not sufficient evidence.

The study uses as many suitable saved solutions as are available. The current
inventory contains 432 unique source-image checksums with saved Barghini cameras
and association tables. All 432 retain catalogue coordinates and 431 also
retain the proper-motion-propagated coordinates used by their solve.

## Version and preservation boundary

V11 and every earlier runtime, launcher, catalogue, example, and reference
product remain byte-for-byte unchanged. New runtime code, tests, launchers,
documentation, and study products belong to `v12/`, new root v12 boundary tests,
or a new results directory. V12 owns its local runtime files and data; it never
imports runtime code from another project.

The extended family is experimental. The ordinary v12 blind-solving path uses
the inherited eight-parameter model unless a later, separately documented
decision changes that default. No study result silently changes historical or
normal solver output.

## Camera family

Let the existing radial mapping be

```text
u0(r) = V r + S [exp(D r) - 1].
```

For image-shape scale `R = hypot(height, width) / 2`, define `rho = r / R`.
The nested model with `q` additional parameters is

```text
uq(r) = u0(r) + sum(c_j rho^(2j+1), j=1..q),  q in 0..5.
```

Thus `M0` is exactly the existing model and `M1` through `M5` add powers
`rho^3` through `rho^11`. Coefficients are angles in radians. The full camera
has `8 + q` fitted camera parameters. Every extended parameter starts at zero, so
each higher-order fit contains the preceding fit as its starting solution.

The correction is part of the Barghini forward mapping, its inverse, saved
camera record, fitted sky coordinates, and detector predictions. It is never a
plot-only displacement. The implementation checks the radial derivative on a
dense grid covering the largest detector-corner radius. A non-positive or
non-finite derivative makes the model invalid. The antipode check is applied at
the largest fitted-source radius because real images can have unused black
rectangle corners outside the illuminated lens circle. Inverse projection
independently requires detector-wide monotonicity and brackets every requested
target; it must round-trip to the existing camera-test tolerance.

## Saved-solution discovery

The comparison command accepts one or more files or directories. Directories
are searched recursively for `result.json` files with sibling
`star_coordinates.csv` files. Successful records with a serialised Barghini
camera and at least 20 fitted associations are candidates.

Records are deduplicated by `source_sha256`. The selected record is the highest
semantic solver version and then the newest result-file modification time, with
the resolved path as a deterministic final tie-break. Selection and rejection
reasons are written to the audit output.

Targets use `propagated_ra_deg` and `propagated_dec_deg` when both are present
and finite. Otherwise the exact saved `catalog_ra_deg` and `catalog_dec_deg`
used by the historical result are used and the fallback is labelled. The tool
does not redetect sources, reassociate stars, infer names, or use observation
metadata. Every model for an image receives the identical fixed association
rows. All fitted associations are used in the full-data fit.

## Fitting and numerical measurements

Each candidate model is fitted from the selected saved camera under an ordinary
isotropic-Gaussian tangent-plane likelihood. This fit directly minimises the RSS
used by AICc and BIC, rather than applying a Gaussian information criterion to a
different robust objective. `M0` is fitted first and each extended fit starts
from the preceding converged model. Full-data products record unweighted
great-circle/tangent-plane RSS and RMS in angular units and faithfully inverted
detector RMS in pixels.

The saved current solution and its RMS remain in the output. After statistical
order selection, refit `M0` and the selected order with the solver's current
rotationally invariant soft-L1 angular objective. These operational fits show
whether the statistically selected extra terms help the actual robust solver;
they do not enter the Gaussian AICc calculation. Association-yield comparison
uses these robust operational fits.

Each fit records optimizer status, evaluations, parameter count, numerical
Jacobian rank and condition number, minimum radial derivative, round-trip error,
and failure reason. Failure of one order does not abort the image or batch.
Orders after a failed lower-order fit may start from the latest valid lower
model with intervening coefficients set to zero, and that recovery is audited.

## Complexity-adjusted comparison

For `N` stars, `n = 2N` tangent-plane coordinate observations. The camera has
`8 + q` parameters and the Gaussian likelihood also fits its variance, so the
information-criterion count is `K = 9 + q`:

```text
AIC  = n log(RSS / n) + 2K
AICc = AIC + 2K(K + 1) / (n - K - 1)
BIC  = n log(RSS / n) + K log(n).
```

Non-positive RSS, `n <= K + 1`, or non-finite inputs produce an explicit
undefined statistic rather than an invented value. Per-image output includes
delta AICc, delta BIC, and Akaike weights over valid `M0` through `M5` fits.
An extended order has strong information-criterion support over `M0` when its
AICc is at least 10 lower. BIC is the conservative sensitivity check, not a
replacement for predictive validation.

## Spatially blocked validation

The study uses deterministic eight-fold spatial validation. Around the saved
optical centre, split radius-ranked stars into inner and outer halves, then
split each half into four contiguous angle-ranked blocks. Each holdout is an
annular wedge that removes a spatial region from training. `M0` and every
full-data extension that passes the necessary delta-AICc/BIC gate are refitted
on seven folds and evaluated on the held-out fold without reassociation or
clipping. Extensions already excluded by that gate retain explicit
`penalised_criteria_not_supported` fold rows; validation could not make them
selectable under the predeclared decision rule.

Outputs retain each fold's star count, pixel RMS, angular RMS, fit validity, and
failure. Per-image validation RMS pools held-out squared residuals so every star
is counted exactly once. A paired spatial block bootstrap of the eight fold
differences supplies a deterministic confidence interval for the extended-minus-
baseline validation RMS. The fixed fold definition and seed are saved.

Cross-validation is a model-comparison diagnostic only. It does not introduce
withheld stars into normal blind solving; the final camera fit continues to use
all associations.

## Association-yield comparison

Plate terms do not change point-source detection, which occurs before catalogue
fitting. They can change whether an already detected source receives a valid
catalogue association, especially near the detector edge. The study therefore
keeps accuracy selection and association yield as two separate questions.

After model order is selected from the fixed-association statistics, rerun
mutual-nearest-neighbour association for `M0` and the selected extended model
using the exact same complete `dots/star_candidates.csv`, catalogue bytes,
propagated coordinate epoch, and saved final angular gate. Catalogue files are
resolved by their recorded SHA-256, never by an assumed launcher default. The
current inventory has a detection table and the exact catalogue for all 432
unique sources. Three historical results do not record their final association
gate; those comparisons are reported unavailable rather than assigned a default.

Record total associations and counts gained, lost, and changed relative to
`M0`, both overall and in normalized radial bins. A gained association is a
previously unmatched detection now mutually matched inside the unchanged gate.
A lost association is the converse. A changed association has the same measured
detection but a different catalogue identifier; it is reported separately and
never counted as an unqualified gain. Compare the residual distributions of
common and newly gained pairs. The batch summary must state explicitly that
these are newly associated detections, not newly detected image sources.

Major-planet and Ceres/Vesta evidence is evaluated separately from catalogue
stars. For every retained historical planet-candidate row, keep the measured
detection, body identity, and candidate epoch fixed; use the bundled exact
ephemeris to project that body through the robust `M0` and selected cameras.
Record baseline/selected pixel and angular separation, normalized detector
radius, major/minor classification, and whether either separation passes the
unchanged saved planet gate. If the sidecar did not record a gate, residual
changes remain available but gate membership is explicitly unavailable; no
default is substituted. This answers whether edge candidates become better
positional fits without changing identities or dates after seeing the answer.
It is a conditional astrometric comparison, not a new blind planetary search.

## Decision classification

For each image and extended order, classify the result as:

- `supported`: delta AICc is at most -10, BIC improves, validation RMS improves,
  the bootstrap upper confidence limit is below zero, and the fit is valid;
- `in_sample_only`: penalised in-sample criteria improve but validation does not;
- `unsupported`: the valid fit lacks the required penalised support;
- `worse_prediction`: validation RMS increases;
- `failed`: optimisation, rank, monotonicity, inversion, sample-size, or input
  validation fails.

The best supported order is the smallest supported order within two AICc units
of the minimum supported AICc. This avoids selecting an unnecessary higher order
when support is effectively tied. No supported model is a valid and reportable
outcome.

## Aggregate inference and dependence

Frames sharing a detector geometry and source-series signature are correlated.
The aggregate report therefore gives both raw image counts and group-aware
summaries. Groups use detector shape plus a normalized source-path family; the
exact group assignment is exported for audit. Within every group and overall,
report model-order counts, failures, median and quartile RMS changes, and the
fraction in every decision class.

A deterministic cluster bootstrap samples groups, not individual frames, to
give confidence intervals for the median relative validation-RMS change. The
report must not claim that hundreds of sequential frames are hundreds of
independent instruments.

## Failure and sensitivity evidence

Every discovered source appears in `solution_inventory.csv`, including rejected
or shadowed duplicates. Every selected image and model order appears in
`model_comparison.csv`, including failed fits. `validation_folds.csv` retains
fold-level evidence. `association_yield.csv` retains baseline/selected counts,
gained/lost/changed identities, radii, gates, and residuals.
`planet_residual_comparison.csv` retains fixed-identity/fixed-epoch major and
minor planet comparisons. JSON contains the same records plus configuration
and software provenance.

The summary explicitly identifies:

- optimizer failures and evaluation limits;
- non-monotonic or non-invertible radial mappings;
- rank-deficient or ill-conditioned fits;
- sparse images for which AICc or validation is unavailable;
- orders that improve fitted RMS but worsen held-out RMS;
- camera/source groups where the preferred order differs;
- images where no extension is supported;
- images where a supported extension gains no associations, loses associations,
  or changes identities, especially near the field edge.

Plots show radial residual profiles, fitted versus validation RMS change by
order, delta AICc/BIC, and failure counts. Actual centroids and model predictions
remain at their numerical locations; any residual-vector magnification is
labelled and never changes measured overlays or statistics.

The v12 identified-source image and investigator sky plot both permit 40
spatially distributed star labels by default. This display change does not alter
association, fitting, ordinary identifiers, or the numerical study.

## Tests and acceptance

Tests first establish exact nesting at zero coefficients, forward/inverse
round trips, derivative validation, and rejection of non-monotonic extensions.
Synthetic fields then establish recovery of a known radial term, refusal of
unnecessary degrees of freedom, and exposure of an overfit through blocked
validation. Discovery tests cover duplicates, malformed inputs, propagated and
catalogue-coordinate paths, deterministic ties, and continuation after failure.

Association tests use controlled detections near and far from the optical axis
to prove that source-detection counts are unchanged, genuine edge recruitment is
counted as gained, identity swaps are not gains, and the exact saved gate and
catalogue checksum are enforced.

Planet tests hold identity and epoch fixed while changing only the camera,
exercise both a major planet and a minor planet near the edge, and verify gate
crossing and residual-improvement classifications. A report test verifies that
40 distinct catalogue labels can appear on the v12 sky plot.

Acceptance requires the complete unit suite, the preserved historical demo,
the v12 boundary checks, and a completed batch run over all usable unique saved
solutions. Numerical findings and their reasons are documented without relaxing
any regression threshold.
