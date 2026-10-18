# V11 joint stellar/planetary epoch — development handoff

Launch with `../go11.sh IMAGE` or `../go_v0.11.0.sh IMAGE`. The package owns its
catalogues, ephemerides, dependency lockfile and runtime. V10 is untouched;
`../../docs/v10-runtime.json` freezes committed v10 in its top-level hashes and
retains the exact working parent under `working_tree_parent_snapshot`, including
its pre-existing uncommitted exposure-rate change. This is a development checkpoint,
not a claim of completed precision dating.

## Implemented numerical changes

The full 1850-to-run-start causal planet search is now used irrespective of
observation metadata. Optional metadata-assisted proposal acceleration was not
implemented: metadata is only a separate validation and cannot affect selection.

Every multi-body global hypothesis is profiled with a common Barghini camera,
proper-motion stars and exact planet directions. Bodies and detections are
one-to-one. Claimed planets cannot also enter the stellar fit. All other sources
remain eligible during up to six reassociation/profile iterations. Every final
membership and profile is recorded; changing membership requires refitting.

Radial soft-L1 residuals use per-source angular scales, with the real-data scale
`max(3 arcmin, initial stellar RMS)`. There is no source replication or star-count
normalization. The nominal conditional 95% profile contour uses delta cost
1.9207294. It is not calibrated interval coverage including model systematics.

Candidate ranking retains the inherited matched-count hierarchy. Within the
maximum-count tier, objectives on identical stellar memberships can exclude
competitors beyond delta cost 4.5. Different memberships are incomparable and
conservatively remain competing hypotheses regardless of raw cost. Ranking is
not a calibrated look-elsewhere or false-alarm probability.

Positive brightness evidence uses the common native channel with most usable
unsaturated measurements. Predicted V magnitudes are compared with instrumental
count-rate magnitudes after profiling one zero point. Soft-L1 with a 1.5-mag
scatter floor accommodates passband/colour/extinction/vignetting mismatch.
Saturated, unknown and missing measurements are neutral. This can order
positional peers, but cannot alone resolve their ambiguity. The existing local
depth/bright-planet absence screen is rerun at each joint candidate camera/date.

The inherited exposure-rate patch passed already-normalized rates to a helper
that divides by exposure again. V11 corrects its callers to pass raw counts,
so normalization occurs exactly once. A two-second, 3600-count aperture now
has instrumental magnitude -2.5 log10(1800), not -2.5 log10(900). Same-image
zero-point shifts do not provide independent timing information.

## What is authoritative

Only a unique, data-bounded, converged, physically checked candidate is eligible
for adoption. Photometry/refraction diagnostics are regenerated with the candidate
camera and visibility/solar checks repeated before recoverable file publication.
The initial stellar fit and products remain archived. Explicit fixed/catalogue
epoch controls are preserved rather than overwritten by a joint result.

Ambiguous, insufficient, inconsistent or failed profiles leave the stellar
camera/coordinates authoritative. PDF, FITS overlays and identified photometry
share the same joint candidate identity/date view; timestamp matches stay
separate validation records. Initial global hypotheses remain in
`global_planet_proposals.json`; refined hypotheses are in `joint_epoch.json`.

## Uncertainty: truncated is not infinite

`interval_95_jd_tdb` contains data-measured contour crossings, or null when a
crossing was not reached. `allowed_interval_95_jd_tdb` gives the finite portion
inside the search domain. Its boundary labels distinguish a data crossing,
the causal present-time ceiling, ephemeris start and a local profile limit.
An absent upper crossing does NOT mean the planets provide no epoch constraint.
The report shows the finite interval and its truncation explicitly.

## MMTO clock validation clue

The motivating file has `DATE-OBS=2026-09-19T04:59:55.670400`,
`DATE=2026-09-19T12:00:17.769900`, and `EXPOSURE=20` seconds. The difference is
seven hours plus 22.0995 seconds. Interpreting the filename and DATE-OBS as
Arizona local time is consistent with creation shortly after exposure, despite
the header's UT comment. This is strong evidence of a clock-label problem, not
an automatic timestamp correction. File creation is not exposure start.

Arizona at MMTO uses MST (UTC−7) without summer daylight saving; see
[NIST time-zone/DST guidance](https://www.nist.gov/pml/time-and-frequency-division/local-time-faqs).
The resolver already prioritizes explicit input, FITS/EXIF and then filename.
Unqualified EXIF dates are not inherently UTC. The new post-fit header clock
audit preserves raw values, flags near-integer-hour offsets and never alters
the epoch fit or source metadata.

## Remaining limitations and deliberate conservative decisions

Global proposals use the initial stellar camera, not an exhaustive joint
camera/date search. Geocentric apparent planet directions retain inherited
frame/aberration limitations relative to catalogue ICRS directions. Topocentric
parallax and integrated atmospheric refraction are not corrected. The 3-arcminute
floor is an uncertainty assumption, not a correction. Physical zenith may remain
unresolved, and the original OLS zenith/reference requirement is still unfinished.
No high-precision UTC or definitive planet identification is claimed from these
conditional fits alone. Missing-exposure photometry remains unavailable for
count-rate calibration; missing metadata is not invented.

The final reviewer identified six important issues: different-membership cost
comparisons, fixed/catalogue controls, failed product regeneration, FITS/PDF
authority mismatch, stale metadata identities in adopted photometry, and the
initial-versus-current coordinate epoch label. Regression tests cover the fixes.
The review's request for numerical interval limits was also addressed after the
investigator challenged the word "unbounded". Adoption still uses the inherited
40-label offline annotation default (minor; custom label/cache propagation deferred).

The execution plan/ledger is
`../../docs/superpowers/plans/2026-09-19-v11-joint-epoch.md`.

## Verification and visible acceptance

351 v11 tests pass (1 skipped). Root and v11 historical demos pass. Three new
version/manifest/preservation checks pass, including byte-for-byte v10 retention.
The working checkout has pre-existing v9/v10 preservation mismatches belonging
to another window; those files are not included in this commit. Publication
checks run on the exact staged tree, with committed preserved runtimes.

The fresh MMTO run contains 1128 global hypotheses and 32 joint multi-body
profiles, without profile failures. The best four-body common-camera candidate
is 2026-09-19 13:04:23.755 UTC. Its finite allowed conditional interval is
08:31:46.200–16:05:24.834 UTC, with the upper end set by the causal run-start
ceiling. Physical zenith remains unresolved, so the scientific stellar camera
is retained. This is a real joint candidate fit, not an adopted precise epoch.

[Acceptance report, joint-fit audit on page 4](../../results/v11-final-20260919/runs/2026_09_19__05_00_17.fits-v0.11.0-20260919T160524Z-pJDF70/analysis/report.pdf)
and [comparison image](../../results/v11-final-20260919/runs/2026_09_19__05_00_17.fits-v0.11.0-20260919T160524Z-pJDF70/analysis/joint_epoch_comparison.png).

### Readability correction, 19 September

The investigator found that stacked crosses hid the source cores and the word
`candidate` obscured whether planets actually constrained the fit. The revised
report labels the four bodies `used in joint epoch fit` and separately states
whether the joint solution is adopted. Paired crops show unmarked pixels above
the identical pixels/scale with hollow markers; no legend covers a crop. The
full-sky overview likewise uses hollow rings/squares with `joint fit` labels.
Predictions and measured centroids stay at their saved coordinates. No fit,
identity, adoption status, uncertainty or numerical product changes.

The [revised PDF](../../results/v11-readable-20260919/analysis/report.pdf) and
[paired-crop image](../../results/v11-readable-20260919/analysis/joint_epoch_comparison.png)
are re-rendered from the same saved MMTO fit; the original report is preserved.

The subsequent label-collision correction adds
[adjustText](https://adjusttext.readthedocs.io/en/stable/) 1.4.0 to the v11-only
dependency lock. Star and planet source labels are placed together at 190 DPI,
with fixed marker/legend/notice obstacles. Actual label-frame extents are
checked after optimisation, and a nearest-clear local translation handles
residual collisions without moving anchors or dropping text. The layout audit
records any unresolved overlap rather than claiming arbitrary fields are solved.
The MMTO redraw has 28 labels and zero recorded conflicts. Leader lines show
which source owns each relocated label; source pixels and fit data are unchanged.

[Collision-corrected PDF](../../results/v11-label-layout-20260919/analysis/report.pdf)
and [sky overlay](../../results/v11-label-layout-20260919/analysis/report_sky_overlay.png).

## Fisheye zenith policy update — 19 September 2026

Peter explicitly requested image centre as the default zenith. V11 now adopts
the camera ray through `((width-1)/2, (height-1)/2)` without requiring a detected
closed horizon. It is recorded as `assumed_zenith`, source
`image_centre_assumption`, with metadata unused. The report explicitly says
this is **not an extinction measurement**. This is an upright/centred-fisheye
instrument assumption; it is not justified for arbitrary crops or tilted cameras.

An extinction result overrides centre only with at least 50 usable stars,
>=10-sigma positive extinction in both primary and radial-response sensitivity
fits, <=1-degree conditional angular uncertainty in each, <=1-degree separation
between the two zeniths, and all existing full-rank, airmass-span and non-boundary
checks. These are conservative operational thresholds, not calibrated odds.
The robust regression is unchanged; an OLS reference remains unimplemented.

Weak trials remain saved separately. All stars remain in astrometry and the fixed
zenith-search sample; any falling below the assumed horizon have undefined
airmass, retain their measured coordinates, and are counted explicitly. The
centre ray follows each trial camera and the regenerated adopted camera. Planet
visibility and solar checks may pass conditional on this explicit assumption;
the solar region is a point at the assumed zenith, retaining the existing solar
guard. No location or timestamp supplies this direction. Epoch confidence
intervals exclude uncertainty in the instrument assumption.

Adoption also checks that regenerated photometry retained the candidate's zenith
authority and direction (numerical roundoff tolerance only). If it changes,
v11 conservatively retains the stellar solution rather than publishing stale
altitudes, solar or absence evidence. Joint re-profiling under a changed
extinction-derived zenith remains a limitation; the assumed centre follows the
same candidate camera exactly and does not suffer this transition.

Regressions cover weak/empty photometry, below-horizon stars, strong versus
moderate extinction, camera-dependent centre projection, solar/visibility
authority, and truthful report labels. Adopted-epoch predictions of unmatched
bodies (including Ceres/Vesta when visible) are retained in report/export views;
stale predictions from another epoch are not. These predictions are not matches.

### Fresh MMTO acceptance

The from-pixels rerun of `2026_09_19__02_20_01.fits.bz2` with the final policy
adopts a joint solution: 1,409 stars plus Mars, Saturn and Uranus; stellar RMS
2.543360 arcmin and planet RMS 2.673188 arcmin. The exact centre projects to
(710.5, 705.0) pixels. Two retained stars lie below the assumed horizon.
The best epoch is 2026-09-19 02:09:26 UTC, with conditional 95% interval
2026-09-18 20:10:53 to 2026-09-19 08:26:49 UTC. Metadata did not select it.
Ceres, Vesta and Neptune remain visible as unmatched predictions, not detections.

[Final report](../../results/v11-centre-final-20260919/runs/2026_09_19__02_20_01.fits-v0.11.0-20260919T190829Z-xmWUN7/analysis/report.pdf)
and [sky image](../../results/v11-centre-final-20260919/runs/2026_09_19__02_20_01.fits-v0.11.0-20260919T190829Z-xmWUN7/analysis/report_sky_overlay.png).
All 362 v11 tests complete successfully (one skipped). The historical v11 demo
retains 3,611 associations, 0.370165-pixel RMS and 40 labels. Final saved camera,
zenith projection, planet altitudes, prediction epoch and code hashes were
checked for consistency; the sky-label audit reports zero conflicts.
