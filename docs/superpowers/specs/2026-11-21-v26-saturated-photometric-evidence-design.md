# V26 saturated-source photometric evidence design

## Intent

Use every scientifically interpretable measurement from saturated compact
sources in blind planet inference.  Replace the binary usable/excluded view
with explicit evidence types so a clipped aperture is retained as a lower
bound and a successful unsaturated-wing fit is retained as a model estimate.

## Goals

- Preserve frozen v25 and implement the change only in v26.
- Keep measured pixels, centroids, astrometry, and positional costs unchanged.
- Prefer direct unsaturated count rates, then accepted wing-model count rates.
- When a wing model is rejected, retain the clipped aperture count rate as a
  one-sided lower bound on flux rather than dropping the source.
- Compare candidate planet V magnitudes with the image-derived G-channel zero
  point and extinction model using deliberately broad method-dependent scatter.
- Save the evidence kind, rate, predicted and measured instrumental magnitude,
  residual, scatter, and cost for every matched source and candidate.
- Use summed soft evidence cost to order otherwise comparable planet aliases;
  never turn this photometry alone into a unique-date claim.

## Non-goals

- Do not alter the Barghini fit, measured centroids, source associations, or
  the Sun/Moon gates.
- Do not treat camera G as calibrated Johnson V.
- Do not admit saturated sources to the physical-zenith/extinction regression
  in this first step; that requires a separate held-out empirical calibration.
- Do not assume CCD bleed-charge conservation for the MMTO detector.

## Constraints

- The solve remains blind: no site, timestamp, filename date, or saved identity
  enters the evidence calculation.
- Catalogue and fitted image photometry may supply the zero point, extinction,
  and deliberately broad residual scale.
- A saturated aperture rate is a lower bound, not a symmetric flux estimate.
- A rejected wing model never silently becomes a valid wing measurement.
- Missing or non-finite inputs are reported as unavailable, not described as
  scientific evidence.

## Approaches considered

1. Continue dropping saturated magnitudes.  Rejected because it discards useful
   wing and lower-bound information and caused the motivating failure mode.
2. Substitute every Moffat-wing total as if it were direct aperture photometry.
   Rejected because failed or misspecified wide-field PSFs can be badly biased.
3. Use typed, uncertainty-weighted evidence.  Selected: direct and accepted
   wing estimates receive symmetric robust residuals; clipped aperture rates
   receive a one-sided residual that penalizes only candidates too faint to
   explain the measured lower bound.

## Calculation

For a candidate planet with predicted Johnson V magnitude `V`, use the saved
G-channel photometric model to predict instrumental magnitude

`m_pred = V + zero_point + extinction * airmass + radial_coefficient * r2`.

For a positive count rate `f`, `m_measured = -2.5 log10(f)`.  Direct and accepted
wing estimates use a symmetric residual `m_measured - m_pred`.  A clipped
aperture lower bound implies `m_true <= m_measured`, so its residual is
`max(0, m_pred - m_measured)`.  Each standardized residual contributes a
soft-L1 cost.  Floors remain intentionally broad: 1.5 mag for direct aperture,
1.8 mag for accepted wing models, and 2.0 mag for lower bounds, combined with
the fitted photometric RMS.

## Validation

- Unit tests must fail first for accepted-wing use, one-sided lower-bound use,
  unavailable evidence, and candidate reordering.
- Existing v25 files and launchers remain byte-for-byte untouched by this work.
- Run the v26 focused tests, full v26 suite, repository suite, and versioned demo.
- Record numerical changes and evidence fields in v26 documentation.

## Literature basis

- Su et al. (2022), *Accurate Photometry of Saturated Stars Using the
  Point-Spread-Function Wing Technique with Spitzer*, demonstrates calibrated
  relative photometry from unsaturated PSF wings (doi:10.3847/1538-3881/ac3b5e).
- The WISE profile-fitting pipeline likewise fits only the unsaturated parts of
  saturated-source profiles, provided enough usable pixels remain.
- HST/ACS work shows that bleed-trail charge can support custom-aperture
  photometry when the detector conserves charge into identifiable pixels. V26
  deliberately does not assume that behaviour for MMTO; without a detector-
  specific validation, its clipped aperture remains only a lower bound.
- Bohlin & Gilliland (2004), *Absolute Flux Distribution of the SDSS Standard
  BD +17°4708* (doi:10.1086/425880), is the directly relevant Gilliland paper
  cited by the Spitzer wing-photometry study for recovery of saturated CCD
  charge. This may be the remembered surname, but that inference is not treated
  as a confirmed identification of the paper the investigator had in mind.

The literature search did not establish the exact Chris Flynn co-authored paper
recalled by the investigator; that attribution remains open rather than being
guessed into the provenance.
