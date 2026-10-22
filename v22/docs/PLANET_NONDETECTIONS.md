# Bright-planet absence checks in v0.5.0

`go5.sh` keeps the blind positional search and joint fits from v0.4.3, then
checks each retained candidate at **its own epoch**. A candidate predicting a
bright planet in locally supported blank sky ranks below an uncontradicted
candidate. The positional fits, source membership and camera remain unchanged.
This is a conservative consistency screen, not a calibrated likelihood or a
proof that the surviving epoch is correct.

## Which planets and brightness model?

Mercury, Venus, Mars, Jupiter and Saturn are assessed. Uranus and Neptune remain
in the positional search, but their absence is neutral. Pluto is not searched.
There is no new catalogue-depth limit: the bundled catalogue remains Gaia G 7.5
with its existing bright-star supplement.

The V-magnitude estimates use the distance/phase polynomials in Mallama & Hilton
(2018), [Computing apparent planetary magnitudes for The Astronomical Almanac](https://arxiv.org/abs/1808.01973),
equations 2–4, 6, 8 and 11. Positions, light-time distances and phase angles use
local Astropy/ERFA builtin ephemerides. Saturn uses the globe-only estimate,
conservatively omitting ring brightening. Mars rotation/season corrections are
omitted. Formula-domain failures are inconclusive. V is not the camera's
passband or Gaia G; the comparison below includes a two-magnitude guard.

## When can a blank location count against a candidate?

All of the following must hold:

- The planet is unmatched, above the fitted photometric horizon and on the
  detector. No image date, location or stellar-epoch estimate enters this check.
- No saved detection lies within the probe, regardless of saturation, morphology
  or stellar association. The probe radius is the larger of twice the positional
  gate (normally 6 pixels) and three median stellar PSF sigmas.
- The raw probe has no peak above four times its local noise, and its highest
  pixel is at most three times that noise before absence can be concluded.
- The complete probe and background annulus are available. Nonfinite/masked
  pixels, image edges, black regions, a dark core, strong background gradients
  or a background inconsistent with surrounding stars are inconclusive.
- At least five reliable measured stars surround the position within the larger
  of 40 pixels and 5% of the detector diagonal. Up to 24 nearest reference stars
  are considered. They must surround it in angle, not all lie on one side.
- These witnesses are unsaturated, compact, have positional residual at most
  1 pixel, peak SNR at least 8, and catalogue magnitudes at least **two magnitudes
  fainter** than the predicted planet's V magnitude.
- Their lower-quartile measured peak exceeds six times the target location's
  noise. Thus an intrinsically bright planet alone does not establish that the
  image could detect it there.

Noise is 1.4826 times the median absolute deviation in an annulus from two to
three probe radii, with a 0.5 ADU floor. A core/background deficit above three
noise units, quadrant background range above four noise units, or background
difference exceeding the greater of three witness-background scatter units and
three witness-noise units makes the result inconclusive.

These witness cuts affect only this diagnostic. All detections remain available
for astrometry, planet association and the established photometric fitting rules.
RGB pixels use the existing luminance weights; there is no new channel fit.

## Ranking, files and display

Candidates sort by: uncontradicted first; missing bright-planet count; matched
planet count descending; original positional cost; epoch. `positional_rank`
retains the previous order. An already ambiguous result stays ambiguous even if
absence checks leave one candidate. If every candidate is contradicted, the
status is `planet_epoch_inconsistent`, with no supported epoch or planet overlay.

`planet_non_detections.json` records each check, its reason, the local noise,
reference stars and magnitude guard. `planet_epoch.json` and
`planet_candidates.csv` retain every positional trial with its missing planets.
The PDF marks contradicted candidates in its diagnostic table. Main image and
FITS overlays use only the highest-ranked uncontradicted candidate, with other
planets reprojected at that same epoch. Original source centroids do not move.

## Validation and limits

Synthetic tests cover a bright missing planet, faint/poor-depth neutrality,
saturated detections, raw detector-missed sources, source wings, dark nonzero
obstructions, noisy/cloudy patches, masks, edges and insufficient star coverage.
A two-epoch, two-matched-planet test checks independent ephemeris evaluation,
visibility, preservation of fits/camera, reranking, audit output and regenerated
overlays. The pipeline metadata-poison test now includes actual image pixels.

The full `go5.sh` run on `warwick_20260915T001639Z_a891a111f4e8` contradicted
16 of 65 candidate dates but left the original Mercury/1927 candidate ambiguous.
Its predicted Jupiter position has little signal within 3 pixels, but a pixel
peak 5.85 pixels away triggers the wider conservative source veto. This is
**not** evidence that the Mercury identification is correct. The rule was not
narrowed to force the desired answer on this image.

Release checks: 48 legacy/package tests, 131 preserved-v4 tests and 147 v5 tests
passed, including real DS9 checks on a private virtual display. All three fresh
pixel demos recovered 3653 associations at 0.397892-pixel RMS with 40 labels.
The Warwick run generated `report.pdf`, the absence audit and `solution.fits`;
its ZPN validation error was below 0.001 pixel across 22057 detector positions.
These establish integration/regression behavior, not a unique planetary epoch.

Local witnesses/backgrounds are not a complete cloud or obstruction mask. Small
clouds, unrecognised structure, blends, passband differences and model errors
limit the interpretation. Conversely, an unrelated source or PSF wing can leave
a wrong epoch uncontradicted. A future independently tested source-centroid and
brightness model could improve this discrimination. No calibrated false-alarm
probability or complete recovery of the true epoch is claimed here.
