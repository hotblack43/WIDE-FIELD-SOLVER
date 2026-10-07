# Topocentric Moon corroboration in v14

## Scientific role

The Moon is independent evidence about retained planet-date candidates. It is
not added to the point-source catalogue, the Barghini objective, the joint epoch
fit, or the saved coordinate solution. Its frequently saturated disk and halo
make a point-centroid treatment both unnecessary and unsafe.

For each retained date, v14 combines that date with the already-fixed
image-derived zenith. Transforming the zenith into the Earth-fixed frame yields
an implied observer latitude and longitude without reading site or timestamp
metadata. Astropy's pinned builtin ephemeris then supplies an offline
topocentric apparent Moon direction. Observer height is unknowable from a
direction alone and is fixed to sea level; its sub-arcsecond lunar effect is
well inside the explicit 0.75-degree positional guard.

The calculation is offline. It uses Astropy's bundled Earth-orientation table,
allows that pinned table beyond its predictive-age freshness check, and uses
Astropy's mean-polar-motion fallback outside the table. That approximation is
at arcsecond scale and is recorded in each prediction; it remains far inside
the 0.75-degree guard.

## Evidence rules

The image is classified before evaluating dates. Every unidentified broad or
saturated detection has its minor-axis angular diameter calculated through the
fitted camera. It is a possible Moon only when that diameter is at least 0.5
degrees and its centre is at least 5 degrees above the derived horizon. Thus a
small saturated star is not a Moon candidate.

If no possible Moon is present, a date is contradicted when all of the following
hold:

- illuminated fraction is at least 0.25;
- predicted altitude relative to the fixed image-derived zenith is at least 5 degrees;
- the predicted disk plus the positional guard has a valid detector projection;
- every tested pixel is inside the recorded scientific and sky-footprint masks;
- no resolved Moon-sized image object occurs at the prediction.

If a possible Moon is present, its measured direction must agree with the
topocentric prediction within 0.75 degrees. A date that predicts no detectable
Moon or places it elsewhere is contradicted. Ordinary stars and raw point-source
signal do not cancel the lunar absence constraint.

## Candidate ranking and limits

Solar contradictions remain strongest, followed by missing bright planets and
missing expected Moon evidence. Planet match count remains ahead of positive
lunar support. Lunar support can break an otherwise comparable ordering, but
the pre-lunar ambiguity state is retained: the Moon cannot turn an ambiguous
planet search into a unique epoch claim. Every original positional candidate
and rank remains in the audit.

The calculation uses no hidden observation site, timestamp, filename date,
saved identity or metadata-derived airmass. It does not model cloud physics,
lunar surface brightness, camera blooming, atmospheric refraction of the Moon,
or observatory height. Those limitations are why uncertain cases are neutral.

## Outputs

- `lunar_evidence.json`: image-level Moon classification plus per-candidate ephemeris, geometry and constraint result;
- `planet_candidates.csv`: lunar status, ranking effect, phase, altitude and pixels;
- `report.pdf`: a plain-language summary of dates rejected by the Moon constraint.

Regression coverage includes topocentric parallax, derived observer location,
angular-size rejection of saturated points, resolved-object support, catalogue
star non-substitution, Moon absence, phase/horizon/mask handling, ambiguity
preservation, pipeline integration and report rendering.
