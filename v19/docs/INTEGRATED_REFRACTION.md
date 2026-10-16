# Integrated atmospheric refraction in v13

V13 carries atmospheric refraction inside the authoritative Barghini camera.
Every mature camera and epoch trial jointly refits the eight lens/pose parameters,
the physical-zenith direction, and the two coefficients in
`R(z) = A tan(z) + B tan(z)^3`. Forward projection applies refraction and inverse
sky coordinates remove it. Saved coordinates, residuals and eligible ZPN FITS
exports therefore use the selected camera state. Refraction outside the supported
horizon domain is rejected rather than extrapolated.

The astrometric objective is rotationally invariant radial soft-L1 least squares.
The photometric extinction line and image-horizon circle fit are robust too;
ordinary least squares is neither a reference nor a fallback in v13. A coupled
candidate is adopted only after deterministic angular-block validation improves
the same robust objective in enough held-out sectors and all physical checks pass.
Otherwise the nested model is saved with exactly `A = B = 0`.

## Existing-image replay, 29 September 2026

The replay used exact `result.json` and `star_coordinates.csv` bytes retained by
the append-only evidence database. Saved associations define this historical
comparison only; site and time metadata do not enter the refits. Two images each
from MMTO, APICAM, Subaru and historical fisheyes supplied 27,998 fitted
associations. Their fitted angular diameters span 155.1 to 172.8 degrees. A
488-by-652 Zenodo small-field control was rejected by geometry before fitting.

No real-image candidate passed the conservative physical checks, so all eight
full-fisheye replays retained exact zero refraction. Five candidates reached the
upper `A = 180 arcsec` boundary and three reached the zero boundary; one also
reached the `B` boundary. Three candidates put fitted directions outside the
supported horizon domain. Candidate in-sample RMS sometimes improved, but those
boundary solutions are lens/refraction degeneracies, not evidence for detected
atmospheric refraction. They were not promoted and no saved historical solution
was changed.

Synthetic injected-refraction regressions still demonstrate recovery, robust
outlier resistance, forward/inverse consistency, refitting during epoch trials,
and exact-zero fallback. The real replay establishes the more important present
limit: a single unconstrained image does not yet separate refraction reliably
from fisheye distortion across these camera families.

Primary evidence is in
`results/integrated-refraction-v13-final3-20260929/`: the PNG compares zero and
selected RMS plus validation gain; `comparison.csv` retains every image and
parameter; `summary.json` retains physical checks; and `report.md` is the compact
human-readable table.

## Best next improvements

The strongest next experiment is a multi-image camera model with lens terms
shared within each physical camera while zenith/refraction varies by exposure.
That directly attacks the observed degeneracy. A second useful constraint is the
already image-derived photometric zenith, propagated with its uncertainty rather
than treated as exact. Both should keep the same held-out angular blocks, robust
loss, exact-zero nested fallback and metadata boundary.
