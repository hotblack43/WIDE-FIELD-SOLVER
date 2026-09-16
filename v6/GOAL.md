# Scientific goal: blind wide-field point-source solving

Owner: Peter Thejll. Scientific intent clarified on 14 September 2026.
Read this before designing, editing, reviewing or declaring this project complete.
This is the durable statement of intent; implementation status belongs in
`docs/FEATURE_STATUS.md`, not in guesses based on filenames or report headings.

## Primary objective

Apply the Barghini O/Z fisheye model successfully to wide-field point-source
images. Detect and identify stars from pixels, fit the camera/lens model, apply
catalogue proper motions, and infer a stellar epoch from astrometry when the image
contains sufficient information. Save the actual fitted camera and consistent
coordinates. A stellar epoch may be very uncertain; report the uncertainty and
unresolved cases rather than manufacturing a precise date.

## Atmospheric refraction and coupled fitting

Include atmospheric refraction in the forward astrometric model used with the
Barghini lens model, and propagate the fitted correction into saved coordinates.
A downstream refraction diagnostic alone does not meet this objective. Keep
physical refraction distinct from lens distortion and assess their degeneracies.

Refraction, physical zenith, lens parameters and stellar epoch may require joint
or iterative fitting. The conceptual sequence of identification, astrometry,
refraction and photometric zenith must not become a rigid single pass that ignores
their coupling. Complete these fits before revealing validation metadata.

## Photometry and colour

Measure stellar photometry and extract useful colour information where the image
and catalogue support it. Preserve available channel measurements and quality
flags. Distinguish instrumental RGB measurements from calibrated magnitudes or
colours; account for passband differences when interpreting extinction and colour.

## Supporting physical-zenith constraint

Estimate physical zenith from the image's stellar photometry. For each trial
zenith, calculate preliminary airmasses for a fixed set of usable point sources.
Use ordinary least squares (OLS) to regress instrumental (machine) magnitude
minus catalogue magnitude against those airmasses. Fit zero point and extinction
slope as nuisance parameters, then vary zenith to minimise the residual sum of
squares on that fixed sample. OLS is the specified reference method; any robust
alternative must be identified explicitly and compared with it, not silently
substituted. The minimum identifies the best candidate under the photometric
model; it does not alone establish that the physical zenith has been recovered.
Incorrect zenith mixes true altitudes and can produce azimuth-dependent scatter,
including on opposite sides of the sky.
Extinction is used as a constraint; obtaining a calibrated extinction coefficient
is not the primary goal. Test vignetting, colour, clouds, limited sky coverage and
weak extinction, and acknowledge non-identifiability.

The Barghini coordinate reference called Z must not silently be interpreted as
physical zenith. Astrometric-refraction fitting and photometric-zenith fitting
have different objectives; implementing one does not implement the other.
Any fitted constraint that changes the astrometry must change the model and saved
coordinates, not plotted symbol positions.

## Separate planetary-epoch objective

Identify planets from measured point sources and use their positions to infer a
separate epoch, potentially much more tightly constrained than the stellar epoch.
This is valuable because the stellar proper-motion clock can be weak. Check planet
identifications and competing dates before claiming a clear epoch determination.
Keep stellar and planetary epoch estimates, their assumptions and their
uncertainties separately inspectable. A metadata-centred ephemeris lookup is not
a blind planetary epoch solution. Do not call this objective complete until the
blind search and its ambiguities have been implemented and tested.

## Blindness and validation boundary

- Do not use observing site, latitude/longitude, timestamps, EXIF, filename dates,
  manifest entries, saved solutions or cached identities to seed, constrain,
  select or tune a blind astrometric, photometric-zenith or planetary epoch fit.
- A local reference catalogue and catalogue proper motions are legitimate inputs.
  Catalogue reference epoch is distinct from an image observation timestamp.
- Names are display-only. Maintain blind pattern bootstrap from measured pixels.
- Metadata may be revealed only after the blind results are fixed, for an
  explicitly separate comparison. Never tune a fit after revealing the answer
  while continuing to describe that experiment as blind.
- Latitude can be checked afterward from the angle between the determined
  physical zenith and the celestial pole appropriate to the epoch. Polaris is
  an approximate pole marker; its offset must not be silently ignored. This
  site comparison is supporting validation, not the primary objective.
- Known-epoch runs are explicit non-blind controls, never substitutes for the
  blind default or evidence that it succeeded.

## Current catalogue depth and labels

Use magnitude limit 7.5 until Peter requests otherwise (Gaia G or Tycho VT,
with the passband difference explicit). Defer deeper magnitude experiments.
Use ordinary star names/designations for plot labels, rather than long Gaia
source IDs. Retain catalogue IDs in numerical records. Name caches and external
alias lookups are display-only and must never seed or change an astrometric fit.
If no ordinary alias is available, retain the source marker without inventing a
name or printing its long numeric identifier on the image.

## Preserve working behavior and honest status

Keep the historical v0.1.0 tag, example input, frozen catalogue and reference
products. Develop new behavior under a distinct version/branch and preserve
checkpoints. Never relax regression thresholds to hide failures. Runtime code
and data remain local to this independent point-source repository.

All detected stars remain eligible for association and astrometric fitting;
there is no default withheld-star split. Keep large/saturated detections even
when their photometry is unusable. Saturation must not disqualify a source from
astrometric association or fitting. Flag saturated sources explicitly and exclude
their magnitudes from photometry and subsequent extinction/zenith regression;
raw fluxes may remain as flagged diagnostics. Use all identified unsaturated
sources with finite catalogue magnitude and positive usable flux for the fixed
photometric sample, including stars down to the horizon. Do not impose a 10-degree
altitude cutoff, an angular cap, or a separate morphology/residual cut on this
sample. Retain every measurement row and its exclusion reason; never change
sample membership as trial zenith varies.

Distinguish recorded proposals, prototypes, tested components, integrated paths
and validated scientific results. A plot or helper function is not evidence
that a constraint enters the solve. Update the feature-status record and relevant
regression tests when behavior changes. No new feature may silently displace an
existing requirement. Gaia catalogue work follows verified proper-motion handling;
it does not replace these objectives.

## Preserve launcher behavior

Do not repoint or overwrite an existing launcher such as `go.sh` when adding a
version. Keep its established behavior and add a separate versioned launcher.
Changing an existing launcher requires Peter's explicit request.

Peter explicitly designated `go4.sh` to follow the latest v4 release. Keep
`go.sh` pinned; version-specific launchers also retain their established versions.

## Visibility and the causal date ceiling

An existing image cannot have been observed in the future. Capture the current
system time once at the start of a blind run and use it as the upper limit of
both stellar and planetary epoch searches. Record that ceiling. This causal
bound is explicitly allowed; the image timestamp/site metadata still must not
seed or constrain the blind fits. Explicit fixed-epoch controls remain controls.

Planet candidates must have nonnegative measured and predicted altitude relative
to the adopted image-derived zenith, and valid detector projections. That zenith
is the photometric result when the extinction evidence is identifiable; v6 may
otherwise use the detector-centre ray only when a closed circular footprint and
the fitted camera independently establish a full 90-degree horizon. The Barghini
reference Z is not a substitute for that zenith. Keep the limit at the horizon,
not 10 degrees. Record source altitudes, zenith provenance and visibility
rejection reasons. When no adopted image-derived zenith is available, report
visibility as unresolved and do not present unchecked matches as visible planet
detections.

The investigator-facing PDF must explicitly identify the stellar catalogue used
by that solve (Gaia or Tycho-2/Hipparcos), including reports from both `go.sh`
and `go4.sh`. Derive this label from saved catalogue provenance, not from the
launcher name or an assumed default.
