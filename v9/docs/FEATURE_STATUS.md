# Point-source feature status, version 0.9.0

This inventory distinguishes implemented behavior from recorded proposals. A new
version must preserve implemented behavior or document an explicit change, and
must not describe a proposal as working merely because related products exist.

| Capability | Implemented status | Evidence / limitation |
|---|---|---|
| Unobtrusive zenith marker | Added in v0.9.0 | The exact saved zenith remains a red X and retains its conditional/provisional identity in the legend, but no marker-attached text box obscures nearby sources. Missing, invalid, off-image and unavailable-image notices remain explicit. Regression: `test_point_star_report.py`; no coordinates or numerical products change |
| Portable results storage | Added in v0.8.0 | The `go9.sh` launcher supports `--results-dir`, `WFS_RESULTS_DIR` and a host-specific user preference; run folders and SQLite stay together. Other machines retain the repository-local default. Missing configured storage fails explicitly. Regression: root `test_v9_launchers.py`; no numerical changes |
| Lossless bz2-compressed FITS input | Added in v0.8.0 | `.fits.bz2`, `.fit.bz2` and `.fts.bz2` use the same Astropy reader as plain FITS in both scientific loading and post-fit metadata reading. RGB values, scaling, exposure, saturation masks and header provenance match plain FITS; input bytes remain unchanged. Regression: `test_point_star_image.py` and `test_point_star_metadata.py`. No model or numerical-fit changes |
| Ceres and Vesta positional search | Added in v0.8.0 | Both numbered minor planets are searched with the seven inherited major planets. A committed 1850--2036 daily JPL Horizons reference uses geocentric ICRF LT+S directions and approximate apparent V magnitudes; cubic interpolation differs by less than 0.002 arcsec at three withheld Horizons epochs per body. Runtime is offline. This does not extend the search to arbitrary asteroids |
| Exposure-normalized source count rates | Added in v0.8.0 | `source_photometry.csv` measures every detection, while `stellar_photometry.csv`, `planet_candidates.csv`, and `identified_source_photometry.csv` retain identity-specific views. Positive FITS `EXPTIME`/`EXPOSURE` and EXIF `ExposureTime` supply seconds. Raw aperture ADU remain saved; ADU/s is instrumental count rate, not calibrated physical flux |
| Saturated-wing photometry | Added in v0.8.0 | Saturation is evaluated independently per native channel. Clipped aperture counts are labelled lower bounds. A robust circular Moffat fit masks saturated/invalid pixels and saves a separate modelled total, count rate, centroid, RMS and usable-wing count. Modelled flux never replaces measured counts or enters the photometric-zenith/extinction sample. The MMTO regression recovered all four saturated G sources and the one saturated B source from their wings |
| Blind detector-parity selection | Added in v0.7.0 | The tetra3 seed determines whether detector rays use normal or one-axis-reflected parity from measured centroids and catalogue geometry alone. Parity is a saved Barghini-camera term used by forward/inverse astrometry, reports, catalogue comparison and ZPN export. Seed refinements are retained only when they improve or preserve the measured seed RMS; seeds outside tetra3's existing match-radius scale are rejected. The APICAM 4096-pixel FITS regression recovered 4,711 associations at 0.618660-pixel RMS with `mirrored` parity; v6 forced a proper-only transform and retained four associations |
| Automatic SQLite run storage | Inherited from working v6 | Every go9 analysis appends all available text products and CSV rows, including reruns, saturated/unusable sources, and partial failed runs. No deduplication or quality cut; never read by the solver. See [DATABASE.md](DATABASE.md) |
| Native-depth raster and stacked FITS input | Added in v6 | One authoritative loader preserves 8/12/14/16-bit PNG/TIFF samples and FITS physical values for detection, photometry, planet evidence and export. It accepts 2-D monochrome, RGB and `R/G1/G2/B` stacks in either axis order or named extensions; G1/G2 remain separately measured while G is their floating mean. `input_image.json` records checksum, dtype/bit-depth evidence, `BITPIX`/`BSCALE`/`BZERO`, HDU/channel mapping, invalid pixels, black-level status and saturation authority. NaN/Inf pixels are masked. Plot stretches are display-only. RAW/Bayer demosaicing remains deferred |
| Nighttime solar consistency for planetary dates | Added in v6 | Accepted stellar field implies nighttime by investigator policy; local Sun ephemerides and a global enclosing region for stellar-horizon-compatible zeniths exclude daylight aliases. Twilight boundary refits and all rejected alternatives are audited. See [PLANET_SOLAR_CONSISTENCY.md](PLANET_SOLAR_CONSISTENCY.md). No photometric-loss penalty or classifier calibration is required |
| Faster blind planetary epoch search | Added in v0.6.0 | Bundled 1850--2036 proposal table, cubic proposal interpolation, batched exact refinement, deterministic per-planet workers and telemetry. Exact vectors retain final authority. See [PLANET_SEARCH_PERFORMANCE.md](PLANET_SEARCH_PERFORMANCE.md) |
| Bright-planet absence evidence | Extended in v0.8.0 | Candidate-specific local pixel/witness checks for Mercury through Saturn plus Ceres/Vesta using bundled Horizons apparent V; Uranus/Neptune remain neutral. Conservative ranking, not calibrated odds. See [PLANET_NONDETECTIONS.md](PLANET_NONDETECTIONS.md) |
| Lossless PNG output speedup | Preserved | Compression level 1; decoded pixels unchanged; report PDFs retain native PNG resolution |
| Ordinary plot names | Enabled by the versioned go launcher | Local display-only aliases, then SIMBAD after fitting; unresolved numeric labels omitted, source markers retained |
| Point-source detection, including large/saturated sources | Preserved | Historical demo and detection tests |
| Audited undersampled-source detection fallback | Added after the v0.6.0 release | If the standard pass finds fewer than 100 sources and `too_small`/`too_sharp` rejections dominate, a 0.8-pixel Gaussian recognition pass is accepted only when it finds at least 12 sources and doubles the count. Native pixels retain flux and peak authority; the selected pass, blur scale and initial counts are recorded. Zenodo 3736793 trials recovered 159 R and 138 G candidates |
| Image-only sky-footprint masking | Integrated in v0.5.0 development | Conservative connected illuminated field; dark exterior frame excluded before association; no OCR or semantic masking inside the field; ambiguous images use the full detector |
| Blind pattern bootstrap and Barghini lens fit | Preserved | Fresh pixels and bundled pattern database; no saved associations |
| Angular astrometric association and fitting | Added in v7 | After the blind bootstrap, mutual-nearest-neighbour gates and rotationally invariant robust Barghini residuals are measured on the celestial sphere in arcminutes rather than detector pixels. Progressive physical gates end at 8.1 arcminutes, the smallest tested floor preserving the historical demo with the radial loss, with a one-fitted-pixel angular floor for coarse sampling. Reports lead with great-circle RMS/median/p90 while retaining pixel diagnostics. After the weak-bootstrap acceptance correction, the 4096-pixel APICAM 2018-09-16T00:13:55 trial gives 8,032 associations at 1.912 arcmin RMS (0.702 px), with 97.2% inside half its gate. On the 915-pixel Espenak-derived FITS, whose 11.24-arcminute sampling floor controls the final gate, it gives 1,072 associations at 4.019 arcmin RMS (0.339 px), with 85.2% inside half the gate; this improves the previous 6.220-arcminute result while retaining most detections. These are fitted residuals, not independent validation |
| Proper-motion propagation in the final astrometric solution | Added in 0.3.0 | Shared catalogue propagation, synthetic recovery and exported-coordinate checks |
| Stellar epoch fitted with all associations; final camera saved | Added in 0.3.0 | All-star robust profile; conditional or provisional date status. If six proper-motion reassociation profiles do not settle, v6 now records `not_converged` and retains the last camera with the exact membership used to fit it rather than failing or pairing a camera with unfitted membership |
| RGB instrumental photometry | Extended in v0.8.0 | Aperture counts, exposure-normalized count rates, per-channel saturation and separate wing models are retained for all detections and identified sources |
| RGB-versus-catalogue report diagnostics | Preserved from final v0.5.0 | Third PDF page compares camera R/G/B instrumental magnitudes with Gaia RP/G/BP for finite unsaturated Gaia matches; passband mismatch and lack of calibration are explicit |
| Extinction as nuisance regression in blind zenith search | Added in 0.3.0 using robust regression | Fixed membership; no site/time-derived airmass; G plot uses the exact fitted line. The OLS reference specified in GOAL.md and its comparison remain unimplemented |
| Zenith estimated by minimising photometric regression scatter | Added in 0.3.0; conditional component | Synthetic recovery and degeneracy tests; real example remains unresolved under the radial-response check |
| Centred full-horizon geometric zenith | Added in v6 | A closed, broad circular boundary must pass circle-residual, complete-azimuth and fitted-camera 90-degree horizon checks before supplying the provisional image-centre zenith when extinction is not identifiable; crops, ellipses and round vignettes do not qualify. A photometric zenith that passes the existing strong-evidence checks retains authority |
| Zenith fitted through astrometric refraction residuals | Implemented downstream diagnostic | Different objective from photometric zenith; does not establish that photometric proposal works |
| Joint photometric zenith/extinction and astrometric epoch constraint | **Not implemented** | Not part of the 0.3.0 proper-motion bugfix; must be designed and tested explicitly |
| Metadata-conditioned planetary analysis | Default in v7 | After stellar astrometry, refraction and photometric zenith are fixed, v7 selects an explicit time, FITS `DATE-OBS`/`MJD-OBS`/`JD`, EXIF original/digitized/image time, or a recognized filename time in that priority order. It runs the complete modern planet pipeline inside ±1 day, records every parsed candidate and disagreement, and saves fitted-minus-metadata timing error. This measures conditional local accuracy, not global blind identifiability |
| Blind planetary epoch | Preserved opt-in and fallback | `--blind-planets` forces the inherited past-only 1850-to-run-time positional search. The same search runs automatically when no usable metadata time exists. Measured/predicted horizon checks and alternatives are retained; single-planet results remain ambiguous |
| Coherent planet-constellation Gaia reassignment | Added in v6 | Two independently eligible planets may recruit a third or later detected planet only inside the ordinary gate and only when the joint epoch refit beats its saved Gaia residual; all compatible one-to-one alternatives are tested, while isolated and two-body gates are unchanged |
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

The report sky overlay projects the saved adopted zenith vector through the
saved Barghini camera and marks it with a red X. Conditional extinction and
provisional geometric candidates are explicitly distinguished; absent or
off-image candidates get a text notice rather than an invented or clamped
position. This is never the lens reference Z or refraction diagnostic zenith.
The unconstrained extinction minimum remains separately recorded as
`photometric_trial` when full-horizon geometry supplies the adopted vector.
The PDF planet row distinguishes an unattempted search from a completed search
with no match. The metadata-assisted routine remains available in code; the
blind replacement remains unfinished, so the normal launcher skips that search.

The Subaru Maunakea 2026-09-16 image supplies the motivating v6 regression. Its
saved footprint is closed, has bounding-box aspect ratio 0.997797 and circular
fill fraction 0.778648, and its bounding-box centre is 15.81 pixels from the
centre of the 3672-pixel square detector. Its boundary circle has 0.01220-radius
RMS residual and 0.02577-radius 95th-percentile absolute residual, with every
azimuth bin populated; fitted-camera boundary angles have 5th, median and 95th
percentiles 88.18, 91.47 and 92.65 degrees from the centre ray. The former
unconstrained minimum lay
about 416 pixels from image centre, placed one fitted star on the horizon, and
gave k=0.011121±0.007939 mag/airmass with 0.378125-mag RMS. It remains
`not_identifiable`. The adopted detector-centre ray projects to
(1835.5, 1835.5) pixels; on the unchanged 716-star sample it gives minimum
altitude 8.830 degrees, airmass 1.0002--6.2664,
k=0.018872±0.012887 mag/airmass and 0.378854-mag RMS. Thus the geometric value
changes provisional airmasses and downstream visibility, but no detections,
associations, camera parameters or saved astrometric coordinates.

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
with the release's historical 0.5-pixel floor, in addition to its historical
3-pixel planet gate. V9 supersedes those detector-unit constants with the angular
rules documented below. This is a documented
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
prediction against the adopted image-derived zenith. Negative altitude,
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

V7 now measures every formally usable seed's great-circle RMS. A seed at or below
3 arcminutes is accepted immediately. A looser seed is retained as an emergency
fallback while the remaining blind hypotheses continue, and the best retained
seed is used only if no strong candidate appears. This prevents a loose first
tetra3 answer from suppressing the existing zero-distortion fallback. On the
APICAM 2018-09-16T00:13:55 frame, the former 15-star seed at 6.252 arcminutes is
retained but displaced by a 23-star fallback seed at 0.251 arcminutes; the normal
pipeline then recovers 8,032 associations at 1.912 arcminutes RMS and the common
Mars/Jupiter/Saturn candidate. The decision uses measured pixels and catalogue
geometry only; no instrument, site, time or saved camera enters the bootstrap.

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

The v6 planet stage now repairs the under-classification exposed by Mars
detection 22 and its plausible but poorer Gaia association. Two independently
eligible planet matches may propose a third or later source inside the ordinary
planet gate; the common epoch is then refitted, and a Gaia-associated proposal
survives only when its final planet residual is smaller than its saved catalogue
residual. The unchanged Espenak camera and detections recover the sole three-body
candidate at 2018-04-16T07:37:57.194 TDB: Mars, Jupiter and Saturn with
0.354307-pixel RMS. Mars is 0.099625 pixels from detection 22 versus the saved
1.125722-pixel Gaia residual. The override and both residuals are retained in
JSON and CSV. Isolated and two-body catalogue-competition gates are unchanged;
the result remains conditional because no calibrated look-elsewhere probability
has been implemented. See
[PLANET_CONSTELLATION_NOTES.md](PLANET_CONSTELLATION_NOTES.md).

## RGB catalogue comparison page

The investigator PDF has a third page comparing instrumental camera R, G and B
magnitudes with the nearest available Gaia DR3 catalogue passbands: RP, G and BP
respectively. The plots retain every finite unsaturated Gaia/channel pair,
including photometric outliers, and show an ordinary least-squares diagnostic
line without a potentially misleading one-to-one reference line. The three
channels share one landscape row. Both magnitude axes are inverted, so brighter
(numerically smaller) magnitudes appear toward the upper right. Bright
Tycho-2/Hipparcos supplements without Gaia BP/RP measurements are not silently
assigned invented colours.

The page is explicitly diagnostic rather than a photometric calibration. Gaia
and camera/JPEG passbands differ, and colour terms, extinction, vignetting and
the encoded camera response remain unmodelled. This report-only addition does
not change detections, associations, the photometric-zenith sample, astrometry
or saved coordinates.

Single-planet date/identity aliases no longer select or display an epoch after
the absence-evidence stage. They remain intact in the JSON and CSV candidate
lists, but the final status is `planet_epoch_not_identifiable`, its selected
matches and epoch are empty, and no unmatched-planet constellation is projected
onto the image. This prevents an arbitrary closest one-body crossing from
looking like a recovered planetary arrangement. Conditional multi-planet
candidates retain the measured and predicted overlays.

## Exact supplied-time planet/source association

After the blind stellar solution and image-derived zenith are fixed, a selected
FITS, EXIF, filename or explicit observation time now drives a separate exact
planet/source association. This is not epoch inference. Each of the nine
searched bodies is projected at the supplied TDB instant, one-to-one source
assignment uses the ordinary 30-arcminute great-circle gate and angular Gaia
competition rule, and an
accepted detection is stored as `metadata_time_match`. Visible bodies with no
accepted detection remain distinct `predicted_no_detected_source` overlays.

For `MMTO.fits`, source 1 is 0.172115 pixels from Jupiter at the FITS
`DATE-OBS`; every other body is hundreds of pixels away. It is therefore
labelled `Jupiter — FITS-time match` while the independent epoch result remains
`planet_epoch_not_identifiable`. The identified-source CSV uses the exact
metadata epoch and retains its 20-second R/G/B count rates and saturated-wing
models. This numerical change corrects presentation and identity bookkeeping;
it does not change detections, the Barghini fit or the blind-epoch evidence.

## V9 angular planet gates and targeted recovery

V9 removes detector-pixel gates from planet/source decisions. The blind search,
exact ephemeris refinement, one-to-one assignment, catalogue competition,
constellation recruitment and supplied-time association all use great-circle
separation. The ordinary gate is 30 arcminutes and the uncertainty floor is
3 arcminutes; pixel residuals remain in JSON, CSV, plots and reports only as
detector-sampling diagnostics. Interpolated proposals and authoritative passage
refinement minimize great-circle residuals as well. Reports lead with angular
separation, and both the predicted body and proposed measured source must lie
above the fixed image-derived horizon.

If a metadata-time prediction has no ordinary source, v9 can reconsider a nearby
local maximum rejected only as `too_sharp` or `too_small` by the detector pass
actually selected for the solution. Peaks outside the saved sky footprint and
peaks overlapping an already accepted detection are excluded. The maximum must be
significant in at least two channels of a colour image (or the single channel of
a monochrome image), pass the same angular planet gate and survive one-to-one
assignment. It is recorded as `targeted_planet_recovery` with its detector
rejection reason and measured centroid. It is not admitted to the stellar
astrometric fit and neither centroid nor ephemeris symbol is cosmetically moved.
Its channel aperture measurements, exposure-normalized count rates and any
saturation/wing diagnostics are appended to `source_photometry.csv` and
`identified_source_photometry.csv`.
