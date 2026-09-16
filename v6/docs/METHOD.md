# Method notes

The following describes the preserved baseline. For the version 0.3 default
proper-motion and epoch fit, see [the numerical change notes](PROPER_MOTION_V03.md).

The mathematical implementation is a snapshot of the successful point-star
experiment. Packaging changes only import/data paths, command-line annotation
options and cached display-name support; the detector and projection equations
are preserved.

## Pixel measurements and initial identification

`point_star_detection.py` converts RGB to luminance, subtracts a Gaussian local
background and finds significant local maxima. Thresholded intensity moments
measure centroids and shapes. Growing windows retain broad and saturated
objects; duplicate peaks on saturation plateaux are suppressed. Finite windows,
blends, edges and shape cuts limit completeness.

Before those measured candidates are numbered or exposed to catalogue
association, `point_star_footprint.py` looks for a dominant illuminated image
field separated from a darker exterior frame. It uses only finite image
luminance, scale-aware smoothing and connected components. Enclosed dark
structure is filled in the mask so the Milky Way, clouds and dark sky patches do
not become holes. When the contrast or geometry is ambiguous, the full detector
remains valid. This is an image-support boundary, not a morphology or quality
cut: compact, broad and saturated sources inside it remain eligible.

The Boolean footprint is saved in `dots/sky_footprint.npz` and displayed in
`dots/sky_footprint.png`. Frame detections are retained in the rejection audit as
`outside_sky_footprint`; they do not reach bootstrap or fitting. No NaN pixels,
OCR, metadata, catalogue coordinates or fitted zenith enter this step. Text or
graphics inside the accepted field are unsupported. The original decoded image
is unchanged in reports and FITS export. Planet non-detection evidence reuses the
mask, treating its exterior as unobserved rather than empty sky.

In v6, a stricter second use of that saved mask recognises only a closed, broad,
near-circular footprint centred on the detector. Such a full-horizon geometry
supplies the image-centre ray as a provisional physical zenith when the blind
extinction search is not identifiable. The unconstrained photometric minimum is
retained for audit, and the extinction regression is re-evaluated at the adopted
centre so its saved airmasses and coefficients remain consistent. A photometric
solution that passes the existing positive-extinction, angular-information,
airmass-leverage, boundary and radial-response checks overrides the geometric
fallback. Cropped, clipped, elliptical and off-centre masks establish no such
centre prior.

The bootstrap scans a small set of central patches at several sizes. tetra3's
bundled database identifies a pattern using only the new measured centroids.
For the preserved example, the accepted patch is 260 × 260 pixels at x=458,
y=592 and contains 11 seed associations. Its solution supplies the initial
scale and celestial reference rotation. Patch selection is part of the blind
search; it does not use a stored celestial solution.

## Global lens fit

`barghini_model.py` implements the independent O and Z parametrisation of
[Barghini et al. (2019), equations (5), (6), and (11)](https://doi.org/10.1051/0004-6361/201935580).
Its radial fish-eye transform is

```text
u(r) = V r + S [exp(D r) - 1].
```

`BarghiniCamera` maps these local angular coordinates through the fixed
reference rotation into celestial unit vectors. Parameters comprise a
rotation angle, independent O/Z detector coordinates, and V/S/D. The fitter
uses robust least squares in unit-vector space and checks positive radial
slope over the detector. The reported residuals are subsequently calculated
in detector pixels using the inverse projection.

Progressive association increases the spatial radius and catalogue depth,
then reduces the pixel matching gate from 12 to 3 pixels. Associations are
mutual nearest neighbours with exclusive assignments. All measured sources
remain available; the last fit uses all current accepted associations.
Variables historically named `train` denote that complete set, without a
withheld-star split. The synthetic geometry unit test separately checks
recovery at additional coordinates.

## Coordinates and interpretation

Pixel centres have integer coordinates, x rightwards and y downwards; origin
is the upper-left pixel centre. Catalogue RA and Dec are in degrees. Internal
model angles are radians. `result.json` stores both normalised optimisation
parameters and physical pixel/radian parameters with the reference rotation.

Z is a chosen celestial reference direction in this experiment. Without date
and site metadata it must not be interpreted as the geographical zenith.
The frozen catalogue contains reference-epoch positions; the solver does not
propagate them to an observation epoch. No atmospheric refraction correction,
planet classification or calibrated photometry is claimed.

The three-pixel association gate and use of fitted stars must accompany
reported residuals. Local accuracy near field edges, and behaviour on other
lenses, need further tests. A converged solution alone cannot establish that
every source is correctly identified.
