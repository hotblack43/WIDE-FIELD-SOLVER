# Sky-footprint mask for framed fisheye images

## Purpose

Restrict v5 source detection and every downstream scientific use of detected
sources to the photographed sky footprint.  A circular or elliptical fisheye
field may be surrounded by a black frame containing a photographer credit,
date, copyright notice, or other graphics.  Those frame pixels are not sky and
must not be offered to star association merely because a graphic resembles a
point source.

This feature does not perform OCR or text detection.  Text or graphics inside
the stellar field make the input unsuitable at the user's risk.  The original
image remains unchanged in reports and FITS products.

## Scientific boundary

The footprint is an image-domain validity mask, not a star-quality cut.  Every
detected compact, broad, or saturated source whose measured centroid lies in
the valid sky footprint remains available for association and astrometric
fitting.  No source is withheld for validation, morphology, saturation,
photometry, residual, catalogue identity, altitude, or inferred epoch.

The mask must be inferred only from image pixels.  It must not use observing
site, time, filename, EXIF, catalogue positions, saved solutions, source names,
or a fitted physical zenith.  It therefore preserves the blind-solving
boundary.

## Footprint inference

Implement footprint inference in a focused v5 module using the already pinned
NumPy and SciPy dependencies.  Convert RGB input to luminance and use a heavily
smoothed copy only to find the large-scale transition between an illuminated
field and a dark exterior.  Candidate foreground regions are connected
components above low-end thresholds derived from the image itself.  Select the
dominant coherent component representing the image field, close small boundary
gaps, and fill enclosed dark holes so stars, Milky Way structure, clouds, or
local dark patches do not punch holes in the usable field.

Accept an inferred mask only when it is a large, coherent region and the
outside has demonstrably lower large-scale luminance.  If those conditions are
not established, use the whole image and record that no framed footprint was
identified.  This fallback is correct for ordinary rectangular photographs
whose entire detector area is sky and avoids manufacturing a boundary from a
dark star field.

The inferred boundary may be circular, elliptical, cropped, or mildly
irregular; it must not assume a perfectly centred circle.  Do not identify
semantic obstructions within the field.

## Detection integration

Keep the existing finite-pixel detector and its background/noise calculations.
Do not represent excluded pixels as NaN and do not replace the source image.
Run the established detector on the finite original pixels, then retain only
candidates whose measured centroids lie within the inferred footprint.  Audit
discarded candidates in `rejected_candidates.csv` with reason
`outside_sky_footprint`.  Assign final detection identifiers after footprint
filtering so all downstream products refer only to in-footprint detections.

This placement deliberately prevents changes to existing centroid, broad-blob,
and saturation behaviour within the sky field.  Bootstrap, association,
Barghini fitting, epoch fitting, photometry, and planet matching continue to
consume `star_candidates.csv`; consequently they cannot receive frame sources.

## Saved evidence and propagation

Save a Boolean mask in `dots/sky_footprint.npz` and an investigator-facing
`dots/sky_footprint.png` showing the original image, accepted field, and fitted
boundary.  Extend `dots/detection.json` with the method/status, valid pixel
fraction, rejected frame-source count, and an explicit statement that no OCR
or inside-field text handling was attempted.  Show the boundary on the normal
candidate overlay.

Pass the saved mask to the bright-planet non-detection checker.  Pixels outside
the footprint are unknown/unobserved, never evidence that a predicted bright
planet is absent.  Photometry needs no independent source exclusion because it
only receives catalogue matches derived from the filtered detection table.

## Failure handling

Footprint inference must fail safe: malformed inputs still use the detector's
existing validation, while an ambiguous boundary produces an audited
`full_image` mask instead of an arbitrary crop.  A successfully inferred mask
that leaves too few stars follows the existing no-source/bootstrap failure path.
No metadata-assisted fallback is allowed.

## Regression evidence

Add deterministic synthetic tests demonstrating that:

1. a round illuminated field in a black rectangular frame is recovered;
2. bright point-like marks and a simulated copyright line in that frame never
   enter the returned detections;
3. compact, broad, and saturated sources inside the footprint are retained;
4. an ordinary full-frame star image remains entirely usable;
5. an off-centre or edge-cropped footprint is handled without assuming the
   geometric image centre;
6. saved mask/audit products agree with the returned detection table; and
7. planet absence checks treat outside-footprint pixels as masked.

Run the v5 unit suite, the repository-required frozen unit suite and historical
demo, and a fresh Espenak solve.  The Espenak evidence must show that the bottom
frame detections near `y = 910` do not enter association, while the sources in
the circular sky field remain available.  Do not relax existing astrometric or
historical comparison thresholds.

## Version boundary and documentation

Modify only v5 runtime behavior and its documentation.  Do not change `go.sh`,
`go4.sh`, `go_v0.4.3.sh`, the root preserved solver, or the frozen `v4/`
package.  Update `v5/docs/FEATURE_STATUS.md`, relevant method documentation,
and `v5/SOURCE_MANIFEST.json` deliberately after implementation.  Keep
`v5/uv.lock` committed; this design adds no dependency.

The independent FITS-export NaN control-flow defect discovered during the same
Espenak investigation is not part of footprint inference.  It may be repaired
as a separate tested bugfix, without changing the fitted camera or numerical
astrometry.
