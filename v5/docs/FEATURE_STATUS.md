# Point-source feature status, version 0.5.0

This inventory distinguishes implemented behavior from recorded proposals. A new
version must preserve implemented behavior or document an explicit change, and
must not describe a proposal as working merely because related products exist.

| Capability | Implemented status | Evidence / limitation |
|---|---|---|
| Bright-planet absence evidence | Integrated in v0.5.0 | Candidate-specific local pixel/witness checks for Mercury through Saturn; faint planets neutral; conservative ranking, not calibrated odds. See [PLANET_NONDETECTIONS.md](PLANET_NONDETECTIONS.md) |
| Lossless PNG output speedup | Preserved | Compression level 1; decoded pixels unchanged; report PDFs retain native PNG resolution |
| Ordinary plot names | Enabled by the versioned go launcher | Local display-only aliases, then SIMBAD after fitting; unresolved numeric labels omitted, source markers retained |
| Point-source detection, including large/saturated sources | Preserved | Historical demo and detection tests |
| Image-only sky-footprint masking | Integrated in v0.5.0 development | Conservative connected illuminated field; dark exterior frame excluded before association; no OCR or semantic masking inside the field; ambiguous images use the full detector |
| Blind pattern bootstrap and Barghini lens fit | Preserved | Fresh pixels and bundled pattern database; no saved associations |
| Proper-motion propagation in the final astrometric solution | Added in 0.3.0 | Shared catalogue propagation, synthetic recovery and exported-coordinate checks |
| Stellar epoch fitted with all associations; final camera saved | Added in 0.3.0 | All-star robust profile; conditional or provisional date status |
| RGB instrumental photometry | Implemented | Aperture fluxes and flags retained in stellar_photometry.csv |
| Extinction as nuisance regression in blind zenith search | Added in 0.3.0 using robust regression | Fixed membership; no site/time-derived airmass; G plot uses the exact fitted line. The OLS reference specified in GOAL.md and its comparison remain unimplemented |
| Zenith estimated by minimising photometric regression scatter | Added in 0.3.0; conditional component | Synthetic recovery and degeneracy tests; real example remains unresolved under the radial-response check |
| Zenith fitted through astrometric refraction residuals | Implemented downstream diagnostic | Different objective from photometric zenith; does not establish that photometric proposal works |
| Joint photometric zenith/extinction and astrometric epoch constraint | **Not implemented** | Not part of the 0.3.0 proper-motion bugfix; must be designed and tested explicitly |
| Blind planetary epoch | Candidate search implemented in 0.4.2 | Past-only positional search capped at recorded run time, with measured/predicted horizon checks; alternatives retained and single-planet results ambiguous |
| Post-fit metadata comparison, including pole–zenith latitude | Added in 0.3.0 | Explicit `--compare-metadata`; no refit, uncertainty/status retained |
| Gaia reference catalogue | Added in 0.4.0 as an opt-in alternative | Native DR3 epochs/PM, 36,663 Gaia rows plus 78 labelled bright supplements; `go_v0.4.0.sh` explicitly selects Gaia; bare solve/analyse CLI defaults remain Tycho/Hipparcos |
| Independent same-image catalogue comparison and paired spatial resampling | Added in 0.4.0 | Different associations allowed; 32 explicit spatial deletion refits; conditional sensitivity, not independent validation |

## Photometric zenith proposal: provenance and implementation

Commit 8247c33 (13 September 2026, 13:16 CEST) records Peter's proposed outer loop:
for each candidate physical zenith, calculate airmasses; regress instrumental
minus catalogue magnitude on airmass; compare residual scatter on consistent
stars and adjust zenith to minimise it. Extinction slope and zero point are
nuisance fit parameters in this zenith constraint. The original note explicitly
labels the work deferred and prescribes tests for extinction, vignetting and
cloud degeneracies.

Commit a3317ec (14 September 2026, 10:26 CEST) introduced point_star_science.py.
It obtains altitudes from site/time metadata and regresses dimming on those
fixed airmasses. There is no outer photometric zenith search. The v2 catalogue-
depth branch does not add one either. No deletion of such a working loop was
found in the available point-source repository history; versions or work outside
that history have not been established. The new version 0.3.0 implementation now supplies the missing outer loop in
`point_star_zenith.py`, called by `measure_photometry`. It preserves all measurement
rows while fixing the eligible photometric sample before the search.

Synthetic tests recover a known zenith with unknown zero point and extinction,
and reject weak extinction, insufficient coverage, coincident/nearly collinear
rays, a search-boundary solution and vignetting-only data. Metadata-independence
tests alter or poison the date/site and assert identical photometric products.
The historical v0.3.0 example fit used 2432 photometric sources but remains unresolved because
the radial-response sensitivity solution reaches the altitude boundary. General
colour, cloud and lens-response biases still require scientific validation.

This is an integrated downstream photometric constraint, not a joint photometric/
refraction/epoch solution. If its future coupling changes astrometry, that change
must propagate into the saved Barghini camera and coordinates. See `GOAL.md` for
the durable scientific requirements.


## September 15 implementation audit

The v0.4 branch includes commits 66bbbc4 (lossless PNG speedup), 0833bee
(proper-motion/epoch loop and saved-camera fix), c2f0afc (blind photometric zenith)
and 94ca721 (Gaia comparison). Epoch trials propagate coordinates and refit the
camera; an outer loop reassociates until stable, then saves that fitted camera.
Photometric zenith and atmospheric refraction remain downstream. Their joint
coupling is unfinished; it must not be described as covered by the epoch bugfix.
The separate v2 magnitude-depth experiment is not merged. Use magnitude 7.5 until
Peter requests a change, as recorded in GOAL.md.

## Extinction zenith on the sky report

The report sky overlay projects the saved photometric zenith vector through the
saved Barghini camera and marks it with a red X. Conditional and provisional
candidates are explicitly distinguished; absent or off-image candidates get a
text notice rather than an invented or clamped position. This is the extinction
regression candidate, not the lens reference Z or refraction diagnostic zenith.
No astrometry, photometry, selection thresholds or numerical results change.
The PDF planet row distinguishes an unattempted search from a completed search
with no match. The metadata-assisted routine remains available in code; the
blind replacement remains unfinished, so the normal launcher skips that search.

## v0.4.1 horizon and saturation correction

The photometric sample now includes every identified unsaturated source with
positive finite G flux and a finite catalogue magnitude. The former compact-only,
1.5-pixel residual and 75-degree geometric cuts are removed. Saturated sources
remain eligible for astrometry and in exported rows; photometric magnitudes are
unavailable and their exclusion reason is `saturated`. Raw aperture fluxes are
retained only as diagnostics. Other exclusions have explicit per-row reasons.

Trial zeniths must keep this fixed sample at or above the horizon (0 degrees),
replacing the former 10-degree boundary. The existing finite airmass expression
includes zero altitude; only sub-microdegree numerical roundoff is tolerated.
The fit still reports a horizon-boundary candidate as provisional and never
silently drops low stars to obtain a solution. Robust regression is unchanged;
OLS comparison and a blind planetary epoch search remain unfinished.

Synthetic checks cover near-horizon recovery, horizon airmass, saturation in
astrometric exports, photometric exclusions and exact red-X projection. The
previous v0.4.0 runtime and launcher remain available in their original worktree.

The same Warwick image rerun is recorded in `ZENITH_V041_RESULTS.json`: all 415
astrometric matches (including 182 saturated sources), camera parameters and
exported coordinates are unchanged. All 233 unsaturated matches enter the new
photometric sample, versus 214 previously. The candidate is conditional with
angular sigma 1.92 degrees and minimum fitted altitude 8.42 degrees; this is not
an independent physical-zenith validation. Previous outputs were preserved.

## v0.4.2 blind planetary candidate search

The default analysis now searches reference trajectories of Mercury, Venus, Mars,
Jupiter, Saturn, Uranus and Neptune across Julian years 1850–2150 TDB. The range is
fixed independently of site/date/filename and the fitted stellar epoch. The saved
camera is held fixed; the stellar epoch does not serve as a planetary date prior.
Ephemerides are geocentric apparent GCRS from the installed Astropy builtin model,
with a local validated reference-only cache under `results/ephemeris-cache`.
[Astropy get_body](https://docs.astropy.org/en/stable/api/astropy.coordinates.get_body.html)
and [ephemeris conventions](https://docs.astropy.org/en/stable/api/astropy.coordinates.solar_system_ephemeris.html)
describe the coordinate/light-time assumptions. Topocentric parallax, refraction,
annual-aberration/frame differences and ephemeris errors limit precision.

The search scans daily spherical segments with a 0.1-degree curvature guard,
refines against exact ephemeris evaluations, and checks overlaps between individual
acceptance windows. Distinct close minima and one-to-one source assignments are
tested. Geometric ranking does not supply a calibrated false-alarm probability.
Single-planet results are always ambiguous; aliases and conflicting identities
remain in `planet_candidates.csv`, `planet_source_candidates.csv` and JSON.
Candidate symbols are plotted at measured positions. Sky labels show the planet
identity assigned in the displayed best candidate; candidate status is identified
in the legend or title. Identities from other dates remain in the candidate records
and are not combined into slash-separated sky labels. The PDF omits the routine
below-horizon rejection-count sentence. These presentation changes do not alter
the search, candidate ranking, visibility checks or saved numerical results.

All detections are considered, including saturated/broad objects. A previous
catalogue association is a competing explanation: for an associated source a
planet must improve positional chi-square by at least 9, using the astrometric RMS
with a 0.5-pixel floor, in addition to the 3-pixel planet gate. This is a documented
candidate-selection heuristic, not a posterior odds or significance calculation.
The catalogue ID/residual and improvement remain in the planet records; this
stage does not change the astrometric association or camera. This prevents a poor
catalogue assignment from hiding a plausible planet while retaining well-fitted
stellar explanations. No planet brightness/identity or known image date is supplied.

The first Warwick investigation found source 63 (saturated), previously associated
with a magnitude 7.497 catalogue star at 2.675 px residual. The blind search retained
103 positional date/identity candidates: 90 Mercury, 8 Saturn, 5 Mars. A Saturn minimum
near 2026-09-14T23:01TDB has 0.240 px residual, but another Saturn pass in 1938 fits
more closely. This establishes candidate recovery and exposes the association
conflict; it does not establish a unique planetary epoch or confirm planet identity.
Historical statements above about a disabled search describe releases before 0.4.2.
OLS reference regression and joint astrometric/refraction fitting remain unfinished.

The console prints the complete candidate epoch list, also saved as
`planet_epoch_candidates.txt`. `planet_epoch_candidates.png` shows all retained
dates and positional residuals with local time-error bars. The PDF adds a third
page with the plot and a compact table; complete machine-readable lists remain
available in CSV/JSON.

That three-page layout remains historical behavior in the preserved v4 runtime.
The v5 PDF omits the crowded epoch-candidate appendix and its redundant metadata
placeholder title line. The standalone PNG, TXT, CSV and JSON evidence remains
available in the run directory; the useful sky-position overlay remains in the
two-page report.

Final same-image evidence is saved in `PLANETS_V042_RESULTS.json`. The complete
v0.4.2 run preserves byte-identical astrometric coordinates, stellar epoch,
photometric zenith and stellar photometry from v0.4.1. 99 tests and the unchanged
historical demo pass. The normal go4.sh path produces a three-page report.

## v0.4.3: physical visibility and a causal upper epoch limit

The previous planet stage never received the fitted photometric zenith. In the
03:16 Warwick image it therefore accepted two logo-area detections as planetary
candidates: sources 32 and 7 have measured altitudes -48.48 and -45.47 degrees.

The planet stage now checks every measured source and every exact ephemeris
prediction against the image-derived photometric zenith. Negative altitude,
outside-detector coordinates and non-invertible detector projections cannot
count as planet matches. The minimum altitude is zero degrees, with only
1e-7-degree numerical roundoff tolerance; no 10-degree cutoff is introduced.
The check operates during refinement and assignment, not merely on plotted
symbols. `planet_visibility.csv` retains all source altitudes/rejection reasons,
and accepted match rows record measured and predicted altitudes. Missing zenith
information yields `visibility_unresolved`; a provisional zenith cannot support
a unique planetary date claim. This relies on the photometric zenith rather than
assuming the Barghini reference Z or a fitted optical centre is physical zenith.

Peter explicitly authorised a causal present-time upper bound: the image already
exists. The default stellar fit captures one system-clock instant and saves it
as `causal_epoch_ceiling` in result and stellar epoch products. Stellar profile
bounds are capped at its Julian year; the planet stage reuses its exact TDB Julian
date, clips the reference grid, and inserts an exact final endpoint. No candidate
may exceed that instant. Image timestamps, sites and filename dates remain unused.
Fixed-epoch controls and the historical catalogue-mode demo remain explicit controls.

The reference-only cache still covers 1850–2150 for reuse; its future entries are
not candidate dates. The actual search endpoint and causal cutoff are saved and
printed. Existing v0.4.2 run folders and launchers remain preserved. Only go4.sh
selects the new v0.4.3; go.sh retains its established version.

The 0.4.3 validation also exposed a pre-existing JSON export failure when the
stellar optimum lies exactly at a search boundary. Endpoint profile costs now
use ordinary Python scalars, just as interior optima do; this changes no fit
numerics and allows the unresolved boundary result to be saved. Planetary time
refinement minimises raw positional residuals before checking visibility, with
rise/set crossings considered as constrained boundary candidates. Off-detector
rays outside the radial inverse domain are rejected individually.

A fresh v0.4.3 solve of the affected `warwick_20260915T031637Z_c84a1e387bb5.jpg`
retains 400 astrometric associations (RMS 0.610010 px), rejects 61 below-horizon
sources from the planet search, and retains 52 past-only positional alternatives.
The former false candidates at detection IDs 7 and 32 occur in none of these
alternatives. A Saturn alternative is retained; this is not a unique planetary
epoch. The stellar profile reaches the causal upper bound and is explicitly
unresolved. Both launcher reports identify the fitted catalogue from its saved
content checksum; the current Gaia catalogue includes a bright Tycho-2/Hipparcos
supplement.


## Bootstrap recovery after broad-search exhaustion

The established patch search is preserved, with a zero-local-distortion fallback
added only after all original attempts fail. A measured-pixel regression exercises
real blind pattern identification and Barghini fitting after simulated timeout.
No sources are withheld and no metadata or cached identities seed the search.
See `BOOTSTRAP_FAILURES.md` for the measured failure and controlled diagnosis.

## Planet display at the fixed candidate epoch

After the blind fit is fixed, the Gaia report and planet-candidate image project
other searched planets through the saved camera at that exact candidate epoch.
Only valid detector projections above the image-derived horizon are displayed.
Thick hollow stars mark measured matches; thin hollow stars labelled predicted
mark expected, unmatched positions. Predictions are recorded separately as
`predicted_planets` in `planet_epoch.json` and do not alter matches, ranking or
epoch inference. Ambiguous epochs and provisional zenith limitations still apply.
Synthetic checks verify the common epoch, visibility, unchanged fit records and
faithful, distinct symbols in both plots. Gaia PDFs are named `report.pdf`.

## ZPN FITS export and embedded DS9 overlays

The v5 analyser exports the fixed camera as a validated ZPN WCS in two products.
`solution.fits` is a conventional two-dimensional primary image for programs
such as Astrometry.net `solve-field`; RGB inputs become Rec. 709 luminance.
`solution_annotated.fits` preserves decoded monochrome/RGB pixels and adds a
native REGION table plus embedded UTF-8 region text for basic geometry and full
styled annotations. `view_fits.sh` loads the annotated product with show/hide
controls; native FITS-region import alone does not preserve labels or styles.
This split fixes the former RGB product's empty primary HDU, which Astrometry.net
0.93 rejected as `NAXIS = 0`; the annotation extensions were not responsible.
The export must pass a 0.05-pixel maximum additional error check over the whole
detector. It does not refit astrometry, use validation metadata or change planet
ranking. See [FITS_EXPORT.md](FITS_EXPORT.md) for layout, limitations and tests.

## v0.5.0 development: framed fisheye support

The detector now infers a conservative Boolean sky footprint from image pixels
before assigning detection identifiers. A dominant illuminated circular,
elliptical, cropped or mildly irregular field can be separated from a darker
frame; ambiguous images retain the complete detector. This is not OCR and does
not attempt to recognise text or obstructions inside the stellar field. The
original pixels are never replaced or set to NaN. `sky_footprint.npz`,
`sky_footprint.png`, the detection JSON and rejected-candidate table retain the
decision and its evidence. Broad and saturated sources inside the footprint
remain eligible for association. Outside pixels are masked, not treated as
negative evidence, when checking for missing bright planets.

The motivating Espenak image previously admitted five broad copyright-line
detections near y=910 as accidental Gaia associations. The image-only footprint
accepts 67.5911% of the detector and rejects 31 frame detections. A fresh blind
run retains 1,137 associations with 0.561218-pixel RMS, compared with 1,144 and
0.577054 pixels before masking. Its fixed 1,079-star photometric sample now
supports a conditional zenith (0.555-degree conditional uncertainty, minimum
altitude 4.389 degrees) and an extinction fit. This does not validate the zenith
against hidden metadata or establish a unique planetary epoch.

The same investigation exposed an independent FITS validation control-flow
defect: an intermediate order-7 ZPN approximation returned non-finite corner
coordinates and reached the Barghini numerical inverse before it could be
rejected. Non-finite trial transforms are now recorded and skipped. The unchanged
camera validates at order 13 with 0.012976-pixel maximum added export error,
below the existing 0.05-pixel threshold; no astrometry is refitted.

The planet stage still under-classifies the same image because Mars detection 22
has a plausible but poorer Gaia association. A full-range diagnostic that lets
that source enter the joint search finds one and only one three-body candidate:
Mars, Jupiter and Saturn on 2018-04-16, with 0.3543-pixel RMS. The evidence,
root cause and proposed constellation/relative-brightness work are recorded in
[PLANET_CONSTELLATION_NOTES.md](PLANET_CONSTELLATION_NOTES.md). This is a design
note, not a claim that the joint scoring change is already implemented.

Single-planet date/identity aliases no longer select or display an epoch after
the absence-evidence stage. They remain intact in the JSON and CSV candidate
lists, but the final status is `planet_epoch_not_identifiable`, its selected
matches and epoch are empty, and no unmatched-planet constellation is projected
onto the image. This prevents an arbitrary closest one-body crossing from
looking like a recovered planetary arrangement. Conditional multi-planet
candidates retain the measured and predicted overlays.
