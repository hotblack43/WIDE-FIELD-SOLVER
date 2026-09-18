# Nighttime and solar consistency

The v6 planet stage treats an accepted blind stellar-field solution as nighttime,
as requested by Peter. This operating assumption is recorded in
`night_classification.json`. Unidentified dots or a failed stellar solve do not
activate it. No separate image classifier or brightness threshold is introduced.

At every candidate date the local Astropy/ERFA ephemeris supplies the Sun in the
same apparent geocentric GCRS convention as the planets. The stage records the
Sun's altitude and the measured/predicted Sun–planet angular separations.
Elongation agreement is not added to the positional score: it would duplicate
existing evidence. Solar altitude is tested for all planet identities, including
outer planets, whether or not the Sun projects onto the detector.

## Conservative handling of uncertain zenith

The solar check uses the entire hemisphere-feasibility region of the fixed
photometric sample. This encloses every photometrically admissible zenith without
requiring a new cutoff in photometric loss. It also encloses the checked
full-horizon geometric fallback when that fallback passes the existing stellar
horizon requirements. A poor provisional zenith therefore cannot by itself
reject a date. Adopted-zenith solar altitude is an explicitly labelled diagnostic.

For unit stellar rays r, every allowed zenith n obeys r.n >= 0. With g the
normalized sum of rays, all feasible n have g.n > 0 if the rays span 3D. Write
n = normalize(g + B p), where B spans the tangent plane. The horizon inequalities
become linear constraints on the two components of p. Four linear programs find
their global bounds. A rectangle enclosing the feasible region defines four
spherical corner rays; a cap containing those rays contains the whole region
when its radius is below 90 degrees. Primal/dual checks and outward numerical
padding precede use of these bounds. Unbounded, degenerate, infeasible or failed
calculations yield `solar_unresolved` rather than a rejection.

The cap radius includes a one-degree angular guard. The solar comparison uses
the conventional -0.8333-degree geometric solar-centre sunset threshold with
another one-degree guard. These are explicit conservative model margins, not
statistical confidence intervals. The threshold does not require astronomical
darkness. Borderline dawn/dusk cases remain possible.

At each retained positional minimum, the search now saves an enclosing interval
from its independently eligible sources' connected acceptance windows. Extra
constellation recruits can only shrink this interval. A conservative Sun-motion
bound of two degrees per day expands the altitude bounds over that interval.
Hard rejection requires daylight across the whole interval and every enclosed
zenith. The bound is for the shipped geocentric Sun over 1850–2036, not solar
motion for a fixed terrestrial observer.

When an individual minimum requires daylight but its interval could cross the
solar boundary, the search proposes additional constrained date fits. A
quarter-day mesh brackets crossings of the conservative cap boundary; roots
are refined, and the positional fit is repeated on allowed subintervals.
Original minima remain audited. Every additional candidate must pass the same
source, pixel, horizon, catalogue-competition and constellation gates. All
planet positions and missing-bright-planet evidence are evaluated at its actual
new date. An exact daylight minimum requiring such a refit is not selectable.
Sampling never establishes infeasibility: an unlocated passage stays unresolved.

## Selection and outputs

Solar-inconsistent dates cannot win through having more positional matches.
Remaining candidates follow the existing missing-bright-planet, matched-count
and residual ordering. Solar uncertainty remains neutral; it cannot support a
unique epoch claim. A single planet still does not establish a date. If there
is no eligible candidate, selected matches, epoch and predicted overlays are
cleared. No measured centroid, saved camera, stellar coordinate or photometric
sample is changed by this stage.

`planet_solar_evidence.json` records the zenith envelope, systematic margins,
candidate intervals, Sun vectors, altitude bounds, elongations and decisions.
`planet_epoch.json` retains those records and separates surviving from
solar-excluded source identities. Candidate CSVs include solar status, reason,
selection eligibility and the solar-boundary-refinement flag. The console and
PDF explain solar rejections; rejected rows remain available for inspection.

Tests cover daylight rejection, twilight preservation, uncertain and rotated
zenith regions, failed optimizers, metadata independence, local Sun conventions,
solar-motion bounds, constrained date alternatives, selection, audit exports
and report wording. The existing OLS photometric-zenith reference requirement
remains unfinished; this change adds no photometric-loss penalty and makes no
claim to complete that separate requirement.

Reference: [USNO rise/set definitions](https://aa.usno.navy.mil/faq/RST_defs)
describe the solar upper-limb convention and horizon/refraction limitations.

## Validation on 16 September 2026

A fresh pixel-to-report run through `go6.sh` on the Subaru example was saved in
`results/runs/subaru_maunakea_20260916T124004Z-v0.6.0-20260916T145632Z-WjIUpZ`.
It recovered 3,567 stellar associations at 1.071157-pixel RMS. The 591-source
fixed photometric sample gave a conservative enclosing zenith radius of 26.317
degrees, including its one-degree guard. Solar consistency rejected 258 of 338
retained date hypotheses; 68 were unresolved and 12 consistent. Three unresolved
positional minima needed a date refit and were not eligible for selection at
their original epoch. The final result was `planet_epoch_not_identifiable`, with
no selected planet matches or epoch. All candidates remain in the audit.

The former leading Venus/Saturn candidate at 1882-06-18T00:18:18 TDB requires
solar altitude at least 11.741 degrees throughout its positional interval and
throughout the enclosing zenith region. Its rejection therefore does not depend
on choosing the provisional photometric zenith or the image-centre fallback.
This is regression evidence for excluding that candidate, not a recovered date.

The root, preserved v4, preserved v5 and active v6 suites ran 70, 131, 161 and
219 tests respectively, without failures. Each versioned suite skipped the
opt-in DS9 display test. Fresh root and v6 historical demos both recovered
3,653 associations at 0.397892-pixel RMS with the unchanged regression limits.
