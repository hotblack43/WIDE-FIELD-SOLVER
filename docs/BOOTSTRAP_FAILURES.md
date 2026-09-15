# Blind-bootstrap failures in point-source wide-field images

Recorded: 14 September 2026.

This note records the diagnosis of repeated
`RuntimeError: No blind catalogue bootstrap from the measured training dots`
failures. It is the canonical troubleshooting record for **point-source**
wide-field images. It does not describe the separate star-trail solver or its
phase-resolved atmosphere and photometry model.

## Conclusion

The Barghini point-source solver and its downstream science analysis remain
functional. The exception means that source detection completed, but the
current tetra3 bootstrap could not infer an initial sky orientation and scale.
The Barghini fit cannot start without that seed.

This is a real robustness and generalisation limitation in blind
initialisation. It is not evidence that the Barghini fit, RGB aperture
measurements, zenith/refraction code, or report generator has been deleted.
An image that fails here may still be astrometrically solvable in principle.

The stages are:

```text
point-source detection -> tetra3 blind bootstrap -> Barghini fit
                       -> photometry/refraction/epoch analysis -> report
```

A bootstrap exception stops at the second stage. No catalogue association,
camera solution, or later scientific product exists for that run.

## Confirmed working controls

The checked-in regression image remains the portable astrometric control:

```sh
./demo.sh --output results/check-unique-name
```

On 14 September 2026 it freshly produced 3,653 catalogue associations at
0.397892-pixel RMS. Because `examples/milky_way/input.jpeg` has no trustworthy
observation time or site, it cannot test an airmass-based extinction fit. Its
report must not describe the absence of airmass as absence of measured RGB
fluxes.

The following external OMRcam point-source image was also rerun with the current
checkout and completed the full CLI analysis:

```sh
./go_solve_wide.sh \
  /dmidata/projects/nckf/earthshine/OMRcam/warwick/warwick_20260914T052851Z_59199463f99f.jpg
```

Its SHA-256 is
`59199463f99f541c306b85e8c04a75a44b4b6213fe7f2935cda1e223ef46ad92`.
The controlled offline rerun found 832 candidates, obtained a 14-star tetra3
seed, fitted 775 catalogue associations at 0.596624-pixel RMS, retained 559
usable stars for the airmass selection, and fitted extinction. Its timestamp
and the ORM site came from the adjacent OMRcam `manifest.jsonl`.

These controls establish that a later failure on another image is not, by
itself, a global regression of the point-source solver.

## What the bootstrap currently tries

`point_star_barghini.bootstrap` uses tetra3's bundled default database and:

- tests square patches with side lengths 18%, 25%, and 14% of the shorter
  image dimension;
- tests only the centred patch and four offsets of one eighth of the full
  width or height at each scale (15 attempts in total);
- preserves detector brightness order and passes at most 80 measured sources;
- lets the first 20 sources generate tetra3 patterns;
- requests at least eight matched stars, a false-positive probability below
  `1e-6`, a match radius of `0.012` times the patch field, and radial distortion
  between -0.2 and +0.2; and
- requests a nominal five-second solve timeout per attempt.

The pinned default tetra3 database declares a 10--30 degree field-of-view
range. The small fisheye patches operate near this local scale, but arbitrary
camera projections, severe off-axis distortion, foreground structure, dense
fields, saturation, and image processing can prevent a valid pattern match.
The tetra3 timeout is not checked during every expensive internal operation;
one diagnostic attempt exceeded its nominal timeout while enumerating
patterns.

There is currently no fallback to a wider patch search, an alternative pattern
database, a different projection hypothesis, or an optional externally known
sky/date/site seed.

## Diagnosed Paranal failure

The failing file was `potw1413a_paranal.jpg`, SHA-256
`47e7433bbec233a044f85d01aa50ad6a8c5c727d6aee568e5bc4d634fabb8274`.
It is ESO image `potw1413a`, a processed 3648 x 3648 fish-eye/fulldome view of
Paranal containing the observatory, Moon, Venus, and a dense Milky Way field:
<https://www.eso.org/public/images/potw1413a/>.

Detection succeeded with:

- 7,913 candidates;
- 7,086 compact detections and 827 broad blobs;
- 2,084 detections flagged saturated; and
- 8,505 local maxima, of which 592 were rejected by the detector.

All 15 standard patches returned no tetra3 match. Each contained hundreds of
detections and was truncated to 80. In every patch, all of the first 20 pattern
sources were saturated; 13--20 of those 20 were broad blobs. By contrast, the
successful Warwick patch contained 46 detections, including 11 compact,
unsaturated sources among its first 20, and returned 14 matches.

Candidate contamination is therefore demonstrated, but it is not yet proven
to be the sole cause. A diagnostic that reordered the Paranal candidates to
use compact sources still failed across the tested central and offset patches.
Projection mismatch, local field scale, processed stellar profiles, and the
limited patch search remain live explanations. Do not claim that filtering
saturated or broad sources alone fixes this case.

## A separate misleading-report condition

Successful bootstrap and astrometry do not guarantee an extinction fit. The
science analyser always measures instrumental R, G, and B aperture fluxes, but
its extinction subset additionally requires a finite airmass. Airmass requires
an observation time and site, either supplied explicitly or recovered from an
OMRcam filename/manifest.

For `examples/milky_way/input.jpeg`, 3,653 RGB measurements were written and
2,698 matched sources were unsaturated and compact, but no star had a finite
airmass. The report consequently displayed `rgb; 0 usable stars`. That phrase
conflates "usable for the airmass/extinction fit" with "usable instrumental
photometry" and is misleading. It is independent of blind-bootstrap failure.

## Requirements for a future bootstrap fix

A fix should improve only the blind seed search before changing the fitted
science model. It should:

1. preserve every detected source for later association and Barghini fitting;
2. use source-quality filtering or reordered subsets only as bootstrap
   hypotheses, never as permanently withheld stars;
3. search patch location, scale, source count, and projection assumptions
   systematically, recording every attempt;
4. retain strict false-match controls and validate any seed through the global
   Barghini refinement;
5. add the Paranal image or a redistributable equivalent as a failing
   regression before implementation;
6. preserve the historical Milky Way thresholds rather than weakening them;
   and
7. report `bootstrap_failed` with actionable diagnostics instead of implying
   that point-source detection or later science analysis was attempted.

Any correction to astrometric coordinates must remain in the Barghini model
and propagate to saved coordinates. Bootstrap improvements must not introduce
cosmetic shifts, cached identities, saved solutions, or hidden catalogue
associations.
