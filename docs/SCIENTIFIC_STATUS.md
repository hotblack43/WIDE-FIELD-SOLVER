# Scientific status

## What is established

- Point sources can be detected and associated across complete fisheye images.
- A blind `tetra3` bootstrap can seed the Barghini O/Z camera fit without using
  the observing site, detector orientation or image timestamp.
- Gaia catalogue positions are propagated with proper motion.
- Astrometric residuals are fitted and reported in angular and detector units.
- Native-depth monochrome, RGB and R/G1/G2/B FITS samples are preserved for
  measurement; plot stretches are display-only.
- Instrumental photometry, saturation flags, provenance and partial failures
  are retained rather than silently discarded.

## Representative MMTO evidence

The v0.9.0 run on one colour MMTO image found 1,380 catalogue associations with
0.3267-pixel RMS. The numerical agreement with the operational camera model's
approximately 0.33-pixel whole-night result is encouraging.

It is not yet a controlled model comparison. Our value is a single-image
in-sample residual with no withheld stars; the operational result pools many
detections over a night. A fair comparison would process the same images,
define the same usable sources and evaluate both solutions against an identical
held-out or otherwise independent criterion.

## Important limitations

!!! warning "Do not over-interpret a successful overlay"
    A successful plate solution does not establish a unique image date,
    physical zenith or calibrated photometric solution.

- All detected stars remain eligible for fitting by design. There is no default
  withheld-star split.
- Instrumental ADU or ADU/s values are not calibrated astronomical fluxes.
- The photometric zenith/extinction constraint may be provisional or
  non-identifiable and is not yet jointly fitted with astrometric refraction and
  stellar epoch.
- The specified OLS reference for the zenith regression remains to be compared
  with the implemented robust treatment.
- A single planetary match cannot identify a unique epoch; aliases must remain
  visible.
- The normal v0.9.0 planetary stage may use image-time metadata after the blind
  stellar solution is fixed. Such results are metadata-conditioned, not blind
  epoch determinations.
- Whole-detector FITS WCS export can be unavailable when the fitted radial
  mapping is not invertible over 180 degrees.

The authoritative requirements are in the repository's `GOAL.md`; the complete
implemented/proposed inventory is in `v9/docs/FEATURE_STATUS.md`.
