# Image-derived nighttime and solar consistency for planetary candidates

Status: architecture approved and implementation requested by Peter on 16 September 2026.
Peter subsequently specified the operating rule: an identified stellar field
counts as nighttime. The v6 implementation uses the conservative outer
stellar-horizon region described below. See
[implementation details](../../../v6/docs/PLANET_SOLAR_CONSISTENCY.md).

Implementation refinement: use a global geometric superset of photometrically
admissible zeniths to make hard exclusions without inventing a photometric-loss
cutoff. The existing OLS reference and any calibrated soft photometric penalty
remain separate future work. Solar-boundary date alternatives are refitted and
audited; a sampled failure to find one is never proof of interval infeasibility.

## Purpose and scientific boundary

Reject planet/date explanations that imply daylight for an image independently
classified as a nighttime stellar exposure. Preserve dawn/dusk Mercury and
Venus, uncertain classifications, competing dates and the existing stellar,
photometric and planet constraints. The user explicitly requires nighttime
classification before applying this restriction.

Use image pixels, freshly fitted stellar associations, the local catalogue and
local reference ephemerides. Freeze image classification and zenith evidence
before evaluating candidate dates. Do not use filenames, EXIF, observing site,
image timestamps, cached identities, or the fitted stellar epoch as a date
prior. Reuse the existing run-clock causal upper date bound.

All runtime work belongs in v6. Preserve root, v4 and v5 runtimes. The present
v6 includes a checked centred-full-horizon geometric fallback; retain its
provenance and provisional status alongside the photometric trial. Neither a
circular detector edge alone nor the Barghini reference Z establishes zenith.

## Why this adds information

At candidate epoch t, let s(t) and p(t) be normalized Sun and planet directions,
u the measured source direction, and n an admissible physical zenith, all in
explicitly compatible coordinate conventions. Compute:

    predicted elongation = acos(s(t) . p(t))
    measured elongation  = acos(s(t) . u)
    solar altitude       = asin(s(t) . n)
    source altitude      = asin(u . n)

A correct ephemeris already keeps inferior planets close to the Sun. Comparing
measured and predicted elongations is a useful audit but largely repeats the
positional fit: do not count it as independent likelihood evidence. The new
information is the compatibility of predicted solar altitude with image-derived
nighttime evidence.

The spherical inequality |h_planet - h_sun| <= elongation gives an inexpensive
necessary condition. For example, a hypothetical planet at altitude 80 degrees
with elongation 25 degrees requires solar altitude at least 55 degrees. If the
Sun is below the horizon and elongation is 25 degrees, the planet cannot be
higher than approximately 25 degrees, subject to observational uncertainties.
Use each epoch's actual elongation for final decisions. Clock midnight and a
fixed number of hours after sunset are unnecessary and can mislead at high
latitudes.

Apply the solar test to every candidate epoch, including outer-planet-only
constellations. It is a consistency test of the whole exposure.

## 1. Recognize the stellar exposure

Use Peter's explicit operating assumption: a successfully identified stellar
field is nighttime for this solver. The existing accepted blind stellar solve
supplies the evidence and activates `night_supported` before planet dates are
examined. Use the existing astrometric acceptance criteria, with no additional
faint-star counts, spatial quotas, background classifier or training dataset.
Unidentified dots alone are not identified stars. Without an accepted stellar
field, return `unresolved` and leave this filter inactive.

Record `basis=identified_stellar_field`, the solve status and association count,
and `policy=user_requested_stellar_field_implies_night`. This is the declared
operating assumption for these images, not a measured classifier probability.
It supports the below-horizon solar requirement without requiring astronomical
darkness or Sun below -18 degrees. Twilight remains admissible.

The classification is fixed independently of proposed epochs. All measured
sources remain eligible under the established fitting and association rules.

## 2. Represent admissible zeniths

Build the zenith evidence once, independently of candidate epochs. Retain the
full fixed photometric sample required by GOAL.md. Refit extinction and zero
point at each trial zenith. Include the specified OLS reference and separately
labelled existing robust and radial-response sensitivity fits. Their raw losses
are not interchangeable chi-square statistics.

For an identifiable zenith, use a profile region with explicitly calibrated
coverage and model sensitivity. For unresolved extinction, retain the broad
set of zeniths compatible with the established stellar-horizon constraints;
do not interpret a local covariance or the existing small plotting grid as a
complete uncertainty region. Conflicting credible model variants broaden the
region rather than eliminating inconvenient alternatives.

The existing checked full-horizon geometry is additional evidence with its own
uncertainty and provenance. A provisional geometric vector must not silently
become exact or replace photometric evidence. If no defensible bound on zenith
uncertainty is available, report `solar_unresolved`.

Every candidate uses one common zenith for the Sun and all measured/predicted
planet altitudes. Numerical optimizers failing to find a feasible direction
are not proof that none exists. Hard rejection needs a conservative global
bound or verified coverage of the admissible region. An incomplete search
yields `solar_unresolved`.

## 3. Test solar compatibility across dates and zeniths

Use local Sun ephemerides at each proposed date, in the same apparent/geometric
convention as the planetary calculation. Add a dedicated Sun-vector interface;
the Sun must not become another point-source identity in the planet assignment.
Evaluate the Sun even when it projects outside the detector.

The standard level-horizon sunset convention puts the geometric solar centre
at -0.8333 degrees (approximately solar radius plus average refraction). Treat
this as a reference convention, not an exact universal physical threshold.
Represent radius, refraction, coordinate-model error and horizon uncertainty
explicitly. Borderline cases remain unresolved; no blanket -6, -12 or -18 degree
cut is justified by a generic nighttime classification. Terrain hiding the Sun
alone does not establish a nighttime sky.

For each positional candidate, retain all connected date intervals satisfying
its existing positional and assignment gates. Ask whether some date in those
intervals and some admissible common zenith allow the solar disc below the
reference horizon, with all existing planet visibility requirements satisfied.
Check interval boundaries and solar crossings as well as positional minima.

- `solar_consistent`: a supported compatible configuration exists.
- `solar_inconsistent`: the stellar-field nighttime rule and a conservative
  bound exclude every compatible configuration, including stated uncertainties.
- `solar_unresolved`: classification, zenith, physical margins or numerical
  coverage do not support either conclusion.

Reject only `solar_inconsistent`, conditionally on the recorded nighttime and
zenith assumptions. Preserve its original fit and exclusion evidence. If a
different date in the same positional interval is required, retain the original
minimum and a separately recorded constrained candidate; recompute all of its
positions, residuals, visibility and existing absence evidence at that date.
Do not attach a solar penalty evaluated at a different date to an unchanged fit.

Keep candidate-specific compatible zeniths as diagnostic witnesses. They do not
overwrite the saved physical zenith, Barghini camera or stellar coordinates.
A later coupled astrometric fit would be a separate implementation step subject
to the saved-model consistency requirements in GOAL.md.

## 4. Combine with existing restrictions

The existing causal limit, detector/horizon checks, one-to-one assignment,
catalogue-star competition and two-anchor constellation recruitment continue
to apply. Solar consistency cannot rescue a candidate failing those rules.

Use this order for final selection:

1. Exclude solar-inconsistent hypotheses from selection, retaining them in audit
   products. Solar-unresolved is neutral and must not be treated as a failure.
2. Apply the existing conservative missing-bright-planet evidence at the final
   candidate date. Unknown detectability remains neutral.
3. Preserve the existing ordering by absence evidence, matched planet count and
   positional residual among eligible candidates.
4. Record any increase in photometric loss needed for solar compatibility.
   Enable it as a ranking penalty only after calibration and comparison across
   OLS/robust/radial variants; until then it is a diagnostic. Never add raw
   magnitude loss directly to squared pixel residuals or multiply correlated
   evidence as if independent.

Thus the first validated filter can remove physically incompatible aliases
without needing an uncalibrated combined score. A later calibrated penalty can
separate marginal survivors. Single-planet results still cannot establish an
epoch; surviving multi-planet candidates retain their conditional/ambiguous
status. If all are excluded, report no supported planet epoch and clear the
selected overlay. Update surviving versus rejected identity lists separately.

## Audit and presentation

Save a proposed `night_classification.json` with the stellar solve status,
association count, class, policy version and stated operating assumption. Save proposed
`planet_solar_evidence.json` with each candidate's original identity/date,
tested intervals, Sun vector/convention, elongations, solar-altitude bounds,
compatible zenith witness, photometric-loss change, uncertainty margins, search
coverage and decision/reason. Extend candidate CSV/JSON rather than deleting
rejected rows. Mark which results were diagnostic-only versus selection-active.

The PDF needs a short explanation such as: "Nighttime supported from the stellar
field; 37 candidate dates imply incompatible solar altitude; 12 remain unresolved
because zenith is uncertain." These numbers are illustrative, not measurements.
Solar plots, if useful, use actual positions and labelled uncertainty. A missing
on-detector Sun marker does not mean a below-horizon Sun.

## Regression and validation requirements

- An accepted stellar solve activates the nighttime rule; raw unidentified dots
  and failed stellar solves do not. Classification is independent of candidate
  dates, and no additional classifier calibration is required.
- Synthetic near-zenith Mercury/Venus requiring a high Sun is rejected when the
  nighttime rule is active and the zenith bounds support rejection.
- Genuine dawn/dusk planets survive; astronomical-darkness and clock-midnight
  assumptions are absent, including high-latitude examples.
- A wrong provisional zenith cannot reject a candidate compatible with another
  admissible zenith. An unresolved fit and optimizer failure remain unresolved.
- A compatible date away from the positional minimum survives; uncertainty
  intervals straddling sunset and disconnected passages are handled.
- All planets in a constellation share the same date and zenith. Outer-planet
  dates receive the same exposure-level solar check.
- Elongation agreement adds no duplicate positional evidence. Existing gates,
  bright-planet absence checks, alternative identities and saturation behavior
  remain covered by their current tests.
- Metadata poisoning leaves classification and decisions unchanged. Local Sun
  ephemerides work offline. Saved camera/stellar coordinates stay unchanged by
  this screening stage; any constrained date gets fresh planet predictions.
- Validate zenith coverage and solar geometry on independent simulations.
  Use the inspected Subaru result only as an
  integration example, not an independent test or threshold-selection target.
- Before committing implementation, run the mandated unittest and fresh demo;
  before publication test all four runtimes and deliberately update the v6
  source manifest. This design-only draft does not change runtime behavior.

## Reference

[US Naval Observatory: Rise, Set, and Twilight Definitions](https://aa.usno.navy.mil/faq/RST_defs)
documents the upper-limb convention, the standard -0.8333-degree solar-centre
altitude and the limitations from refraction, terrain, height and twilight.
