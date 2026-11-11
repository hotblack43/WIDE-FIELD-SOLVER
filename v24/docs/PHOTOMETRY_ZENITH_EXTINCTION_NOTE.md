# Deferred experiment: RGB photometry, zenith and atmospheric extinction

Recorded: 13 September 2026. Idea proposed by Peter Thejll.
Status: research proposal for later investigation; no photometric measurements,
zenith optimisation or extinction estimates have yet been produced.

## The idea to preserve

The visible horizon in the fisheye image supplies information about the local
zenith even when the observing location and time are unknown. In addition,
stars at the same true altitude should experience similar atmospheric
extinction in a sufficiently uniform atmosphere. After accounting for their
catalogue magnitudes and colours, discrepancies around rings of equal assumed
airmass could therefore help reject incorrect zenith estimates.

Peter's proposed test is to vary the assumed zenith and minimise those
discrepancies. It is worth testing whether this constrains the zenith and
supports basic extinction measurements in the three image channels. Success
and attainable precision remain to be demonstrated. A fisheye's broad altitude
and azimuth coverage makes the test particularly promising; adequate sky
coverage, rather than the lens label alone, is the essential requirement.

## Preserved inputs and provenance

- Image: `examples/milky_way/input.jpeg`, 1569 × 1444 pixels.
- Original local filename:
  `/home/pth/Skrivebord/StarTrails/FishEye_MilkyWay_no_trails.jpeg`.
- Image SHA-256:
  `f06569c1397e92d60740d55cf9910113418f8bfc01ee0d9b24aa6cd1f8d467c2`.
- Existing associations: `examples/milky_way/reference/star_coordinates.csv`
  contains 3,653 fitted catalogue matches. The preserved camera is in
  `examples/milky_way/reference/result.json`.
- ExifTool inspection of both JPEG copies found no EXIF or XMP: no observing
  timestamp, GPS, exposure, camera, author or source URL. Basic JPEG/JFIF
  information identifies 8-bit data with 4:2:0 chroma subsampling. Filesystem
  dates do not establish the exposure date.
- Photographer, observing site/time and original online source remain unknown.
  Peter intends to look for the source later.
- Candidate source checked and rejected as a match:
  <https://www.ayton.id.au/wp02/?p=9190>. Its linked photograph shows a rocky
  ocean foreground and a different sky scene. Do not transfer that page's
  camera settings, date or attribution to this image.

### Subsequent source clues, still unconfirmed

Peter recalled the written clue "Parmonas, 5 July 2008", then suggested the
spelling "Parnonas". A search found Frank Ryan Jr (StargazerMan) photographs
whose captions explicitly give Mount Parnon Starparty, Greece, 5 July 2008:

- [Summer milky way on Mount Parnon, Greece](https://www.flickr.com/photos/franks_astrophotography/2662600584/).
- [Summer milky way on Mount Parnon, Greece 2](https://www.flickr.com/photos/franks_astrophotography/2662600098/).
- [Milky way wonders](https://www.flickr.com/photos/franks_astrophotography/2662603486/).

Their public page metadata and image previews were inspected. They show
rectangular views with wooded horizons (one includes an observer), rather
than our circular image with dome-like buildings. The captions corroborate
the date/place clue for those photographs, but do not establish our image's
origin. Do not adopt their Canon EOS 350D/12 mm settings for our input.

Peter also pointed out the apparent telescope domes as a potentially stronger
site-identification clue. Greek observatories to investigate include Skinakas
(Crete), Helmos/Chelmos and Kryoneri (Peloponnese), and Penteli and Thissio
(Athens). Compare historical layouts if the date is retained as a hypothesis;
modern installations may differ. Neither Greece nor 2008 is confirmed for
our image. Official starting points:

- <https://skinakas.physics.uoc.gr/en/home/>
- <https://www.astro.noa.gr/en/ypodomes/>
- <https://kryoneri.astro.noa.gr/en/>

## Geometry: horizon first, photometric consistency second

The current Barghini fit maps image pixels to celestial directions. Its
reference direction named Z is an arbitrary celestial reference; it is not a
measurement of terrestrial zenith. Neither the optical axis nor the geometric
image centre should silently be substituted for zenith.

Identify plausible astronomical-horizon segments, with uncertainties. Buildings,
domes, hills and other obstructions can rise above the astronomical horizon;
the circular image boundary need not be the horizon either. Refraction and an
elevated observer also affect the apparent horizon.

In ideal geometry, celestial unit vectors h along a level astronomical horizon
satisfy n · h = 0, where n is the zenith unit vector. Several well-separated
horizon directions can constrain this plane and its normal. Select the normal
pointing into the visible sky. Limited or obstructed horizon coverage should
produce a range of plausible zeniths rather than a forced precise answer.

For each candidate n and stellar unit vector s, altitude is
`a = asin(n · s)` and zenith distance is `z = 90 degrees - a`. Compute airmass
with a documented approximation and validity range. Avoid the immediate
horizon, where simple sec(z), refraction, obstructions and atmospheric
inhomogeneity become especially troublesome.

## Proposed photometric experiment

1. Measure background-subtracted aperture fluxes separately in R, G and B at
   the measured stellar positions. Save instrumental magnitudes
   `m_inst = -2.5 log10(flux)` for positive fluxes, with an arbitrary zero point.
   Record aperture/background choices and flags for saturation, blending,
   edge truncation, low signal and non-positive flux. Keep measurements and
   flags for as many associated stars as possible.
2. Retrieve catalogue photometry with provenance and uncertainties. Distinguish
   Tycho BT/VT, Johnson-Cousins UBVRI and Gaia G/BP/RP. SIMBAD measurements can
   have heterogeneous origins. The existing catalogue's single magnitude
   column mixes Tycho VT with a bright-star Hipparcos V supplement. It is
   insufficient for an explicit multi-band colour calibration on its own.
3. Plot instrumental magnitudes against plausible catalogue bands and examine
   colour terms. Camera R/G/B do not equal Johnson R/V/B or Gaia RP/G/BP by
   definition. Use empirical transformations and state their applicable range.
4. For each candidate zenith, fit catalogue-relative dimming against airmass
   in each channel, including a zero point and necessary stellar-colour terms.
   A starting diagnostic model is
   `m_inst,c - m_cat,b = Z_c + C_c(colour) + k_c (X - 1) + V_c(x,y) + residual`.
   Here k is atmospheric extinction in magnitudes per airmass only if the
   response and nuisance terms justify that interpretation; V represents a
   specified, constrained instrumental spatial response.
5. Inspect scatter and systematic azimuthal structure within equal-airmass
   bands. Compare candidate zeniths using consistent stars, weights and sky
   coverage, so that a candidate cannot win by discarding difficult stars.
   Prefer continuous residual diagnostics alongside bins; report populated
   sectors and gaps. Catalogue- and colour-corrected dimming is the quantity
   being compared, not raw brightnesses of different stars.
6. Map the objective over candidate zeniths, including deliberately poor
   guesses. Report a broad minimum or non-identifiability honestly. Compare
   channel results, horizon constraints and sensitivity to aperture, stellar
   colour, quality flags, altitude limits and assumed lens response.

Use all usable stars for fitting by default. No withheld-star split is requested.
Physically unusable photometry may be flagged out of a fit, with explicit counts
and reasons; retain those sources in the measurement table. Large saturated
objects remain detectable even when their fluxes are unsuitable for calibration.

## What could and could not be inferred

- A wrong zenith can mix actual altitudes within an assumed equal-airmass ring,
  leaving azimuth-dependent extinction residuals. Detectability requires a
  sufficient extinction gradient, precision and sky coverage. A flat objective
  would provide little photometric information about zenith.
- Vignetting can mimic extinction, especially when the optical axis is near
  zenith. Ring consistency alone can favour the centre of instrumental
  symmetry. A well-constrained zenith does not automatically identify k.
- A freely flexible spatial correction could absorb the extinction signal or
  compensate for a wrong zenith. Compare explicitly constrained alternatives;
  do not use a free correction surface to manufacture agreement.
- Clouds, aerosol gradients, sky-background structure, crowding and spatially
  varying stellar colours can also produce azimuthal residuals.
- JPEG tone curves, clipping, processing and chroma subsampling complicate
  flux linearity and RGB colours. These are initially JPEG instrumental
  measurements. An assumed inverse sRGB response would itself require a
  sensitivity test; it cannot recover unknown processing or saturated flux.
- Three channels provide useful consistency checks, but their processing and
  lens effects can be correlated. Agreement is supporting evidence, not an
  independent proof of atmospheric extinction.

Independent flat-field/lens-response information, a less-processed original,
or suitable additional exposures could strengthen the extinction inference.
Finding the source remains useful, but is not a prerequisite for trying the
horizon-constrained consistency experiment.

## Resume here

First preserve the current astrometric baseline and implement photometry as a
separate analysis using its saved coordinates. Produce the RGB measurement
table and catalogue comparisons before optimising zenith. Test the proposed
zenith objective on synthetic cases with known extinction, vignetting and
cloud structure, including cases where it should fail to identify zenith.

Desired outputs: instrumental-versus-catalogue plots; horizon and candidate
zenith overlay; dimming versus airmass; residuals versus azimuth within altitude
bands; a zenith-objective map; and a short account of degeneracies and sensitivity.
Keep actual measured and predicted astrometric positions unchanged. Any later
astrometric correction must enter the Barghini model and exported coordinates.

This note records a deferred experiment, not a measured zenith or an extinction
result. No implementation, report/Overleaf update or remote push is part of
this note-taking task.
