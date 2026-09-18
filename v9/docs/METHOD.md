# Method notes

The following describes the preserved baseline. For the version 0.3 default
proper-motion and epoch fit, see [the numerical change notes](PROPER_MOTION_V03.md).

The mathematical implementation is a snapshot of the successful point-star
experiment. Packaging changes only import/data paths, command-line annotation
options and cached display-name support; the detector and projection equations
are preserved.

## Pixel measurements and initial identification

`point_star_image.py` is the authoritative v6 decoder. It preserves native
samples for integer PNG/TIFF through 16 bits and for FITS physical values after
standard `BITPIX`, `BSCALE` and `BZERO` handling. FITS may be 2-D monochrome,
three-plane RGB, or four-plane `R,G1,G2,B`, stored plane-first, plane-last or in
named extensions. Both native green planes are retained; the existing RGB path
uses the floating derived plane `G=(G1+G2)/2`. NaN and infinite pixels form an
invalid-pixel mask rather than becoming black sky. Camera RAW/Bayer mosaics are
not decoded here.

The loader saves `dots/input_image.json` with the source checksum, decoder,
native dtype/shape, effective-bit-depth evidence, FITS HDU/scaling, channel
mapping, invalid-pixel count, black-level status and per-channel saturation
authority. An explicit `--saturation-level` has priority, then FITS `SATURATE`,
an observed standard clipping ceiling, and finally an explicitly labelled
datatype-ceiling assumption. Floating input without a trustworthy level records
unknown saturation. Existing 8-bit rendered images retain the historical
`>=250` v6 rule. Every later science stage reloads with this recorded policy and
verifies the checksum.

`point_star_detection.py` derives floating luminance directly from those native
samples, subtracts a Gaussian local background and finds significant local maxima. Thresholded intensity moments
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
graphics inside the accepted field are unsupported. Scientific arrays never
pass through a display conversion. Reports use a separate deterministic 8-bit
percentile stretch and label it as display-only. Annotated FITS exports retain
every native source plane; the astrometry.net primary is a labelled
two-dimensional derived luminance image for colour input. Planet non-detection
evidence reuses the mask, treating its exterior as unobserved rather than empty
sky.

In v6, a stricter second use of that saved mask recognises only a closed, broad,
circular footprint centred on the detector. It requires a low-residual boundary
circle fit, complete 72-bin azimuth coverage and fitted-camera boundary rays
whose 5th--95th percentile angular distances from the centre ray lie within
80--100 degrees (with median within 5 degrees of 90). Such a full-horizon
geometry supplies the image-centre ray as a provisional physical zenith when the
blind extinction search is not identifiable. The unconstrained photometric
minimum is retained for audit, and the extinction regression is re-evaluated at
the adopted centre so its saved airmasses and coefficients remain consistent. A
photometric solution that passes the existing positive-extinction,
angular-information, airmass-leverage, boundary and radial-response checks
overrides the geometric fallback. Cropped, clipped, elliptical, off-centre and
round but narrower-than-horizon masks establish no such centre prior.

The bootstrap scans a small set of central patches at several sizes. tetra3's
bundled database identifies a pattern using only the new measured centroids.
For the preserved example, the accepted patch is 260 × 260 pixels at x=458,
y=592 and contains 11 seed associations. Its solution supplies the initial
scale and celestial reference rotation. Patch selection is part of the blind
search; it does not use a stored celestial solution.

Version 0.7.0 also tests the handedness implied by each accepted tetra3 seed.
Normal and one-axis-reflected detectors are represented by an explicit parity
term in `BarghiniCamera`, while the celestial reference matrix remains a proper
rotation. The parity is inferred from pixels and catalogue geometry rather than
file type or metadata. Seed refinement is kept only when its measured pixel RMS
does not worsen, and a seed outside tetra3's existing match-radius scale is
rejected so later blind patch hypotheses can continue. A formally usable seed
with great-circle RMS above 3 arcminutes is retained as a weak fallback rather
than returned immediately. The blind patch search continues and accepts the
first seed at or below that angular threshold; if none exists, it returns the
lowest-angular-RMS retained seed. This keeps difficult fields recoverable while
preventing a loose early answer from hiding a much stronger later hypothesis.

## V7 planetary time routing

Stellar astrometry, stellar epoch, refraction and photometric zenith finish
before observation-time metadata is inspected. The default planet stage selects
an explicit CLI time, FITS `DATE-OBS`/`MJD-OBS`/`JD`, EXIF time, or recognized
filename time in that order and runs the modern positional pipeline inside a
±1-day interval. All parsed alternatives, UTC assumptions and disagreements are
saved. The date remains a fitted positional result inside that interval, so
source competition, exact ephemeris refinement, physical visibility, solar
consistency and missing-bright-planet evidence still apply.

The fitted planetary date is compared with the metadata reference in seconds.
That error is conditional on being given the correct local interval and does not
measure global date/identity ambiguity. `--blind-planets` bypasses metadata and
runs the complete 1850-to-present search; the same full search is the automatic
fallback for undated inputs.

Planet/source acceptance and ranking use great-circle separation, with a
30-arcminute ordinary gate and a 3-arcminute positional-uncertainty floor. The
coarse index converts that angle to a unit-sphere chord; interpolated and exact refinement,
one-to-one assignment, constellation recruitment and metadata-time association
all minimize or gate on angular residuals. Both a predicted planet and its
proposed measured source must be above the image-derived horizon. Projected
pixel residuals are retained only as sampling diagnostics.

After the fitted stellar and photometric results are fixed, an unmatched
metadata-predicted planet can trigger a narrow audit of detector maxima rejected
only as `too_sharp` or `too_small` in the detector pass actually selected for
the solution. Peaks outside the saved footprint or overlapping an accepted
detection are excluded. Recovery requires significance in at least two recorded
colour channels (one for monochrome), uses the same angular gate, and does not
add the recovered maximum to the stellar astrometric sample. The
measured centroid, original morphology rejection and targeted origin are saved,
and ordinary per-channel aperture or saturated-wing photometry is then appended.

## Global lens fit

`barghini_model.py` implements the independent O and Z parametrisation of
[Barghini et al. (2019), equations (5), (6), and (11)](https://doi.org/10.1051/0004-6361/201935580).
Its radial fish-eye transform is

```text
u(r) = V r + S [exp(D r) - 1].
```

`BarghiniCamera` applies its saved detector parity and maps these local angular
coordinates through the fixed reference rotation into celestial unit vectors. Parameters comprise a
rotation angle, independent O/Z detector coordinates, and V/S/D. The fitter
uses robust least squares on each star's two-dimensional tangent-plane residual
in arcminutes. A rotationally invariant radial pseudo-Huber/`soft_l1` transform
with a 3-arcminute scale is evaluated before linear least squares, so equal
great-circle errors receive equal weight regardless of tangent direction. The
fit also checks positive radial slope over the detector. Great-circle RMS,
median and 90th-percentile residuals are the primary accuracy measures.
Corresponding inverse-projection pixel residuals remain in the products as
detector-sampling diagnostics.

Progressive association increases the spatial radius and catalogue depth,
then reduces the physical great-circle gate through 30, 24, 20, 16, 11 and 8.1
arcminutes. Each stage also has a one-fitted-pixel angular sampling floor,
calculated from the median local Jacobian of the current Barghini camera. Thus
a coarse detector is not required to localise below one sample, while cameras
with different pixel counts or plate scales no longer receive different sky
gates merely because the old constants were expressed in pixels. Associations
are mutual nearest neighbours with exclusive assignments. All measured sources
remain available; the last fit uses all current accepted associations.
Variables historically named `train` denote that complete set, without a
withheld-star split. The synthetic geometry unit test separately checks
recovery at additional coordinates. `result.json` records the physical and
resolved gates, fitted plate-scale samples and robust-loss scale; diagnostics
and coordinate exports retain both angular and pixel residuals.

## Coordinates and interpretation

Pixel centres have integer coordinates, x rightwards and y downwards; origin
is the upper-left pixel centre. Catalogue RA and Dec are in degrees. Internal
model angles are radians. `result.json` stores both normalised optimisation
parameters and physical pixel/radian parameters with the reference rotation and
the adopted detector parity.

Z is a chosen celestial reference direction in this experiment. Without date
and site metadata it must not be interpreted as the geographical zenith.
The frozen catalogue contains reference-epoch positions; the solver does not
propagate them to an observation epoch. No atmospheric refraction correction,
planet classification or calibrated photometry is claimed.

The resolved angular association gate and use of fitted stars must accompany
reported residuals. Local accuracy near field edges, and behaviour on other
lenses, need further tests. A converged solution alone cannot establish that
every source is correctly identified; a residual distribution concentrated at
the gate remains evidence of weak or chance-dominated associations.
