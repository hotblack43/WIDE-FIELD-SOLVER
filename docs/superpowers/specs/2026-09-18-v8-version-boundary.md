# V8 preservation and scientific-upgrade design

**Date:** 2026-09-18

**Status:** Approved through the user's corrected scope: v8 must be v7 plus
Ceres/Vesta identification, exposure-normalized count rates, and improved
saturated-pixel handling. A boundary-only clone is explicitly not sufficient.

## Version boundary

Freeze `go7.sh`, `go_v0.7.0.sh`, and every file in `v7/`. Record their SHA-256
digests in `docs/v7-runtime.json`. Four historical images already named and
hashed by `v7/SOURCE_MANIFEST.json` must be tracked without changing their
bytes so a clean Git export contains the evidence. Root legacy, v4, v5 and v6
remain unchanged.

Create a self-contained `v8/` runtime and `go8.sh` / `go_v0.8.0.sh` launchers.
V8 owns its catalogue, code, lockfile, reference data and manifest and must run
without a branch or `.worktrees` path. Work is performed on detached HEAD; no
branch is created.

## Count-rate photometry

Preserve aperture photometry as the primary detector measurement. Save raw
background-subtracted aperture counts and, when a positive finite exposure is
available from FITS `EXPTIME`/`EXPOSURE` or EXIF `ExposureTime`, save count rate
in ADU/s. ADU/s is instrumental and must not be described as calibrated
physical flux.

Measure every detected source before identity assignment in
`source_photometry.csv`. Retain the stellar view in `stellar_photometry.csv`,
join the same measurement to every planet candidate in `planet_candidates.csv`,
and write `identified_source_photometry.csv` for catalogue stars and planet
identity alternatives. A single-planet alias remains a candidate, not a
confirmed identity.

## Saturated pixels

Treat saturation independently in every native channel. Do not convert the
scientific image to NaNs. A saturated aperture sum is retained and labelled a
lower bound. Mask saturated and invalid samples only within a robust circular
Moffat wing fit, saving its modelled total, ADU/s estimate, centroid, RMS,
shape, and usable-pixel count separately from measured aperture values.

Modelled wing flux must never silently replace measured counts or enter the
photometric-zenith/extinction sample. Saturated detections remain eligible for
astrometric association exactly as in v7. A failed or weak fit remains an
explicit quality status, never a manufactured value.

## Ceres and Vesta

Search numbered minor planets `1;` (Ceres) and `4;` (Vesta) alongside the seven
major planets. Astropy's builtin ephemeris does not contain them, so ship a
versioned local 1850--2036 JPL Horizons table. Positions use Earth-geocentric
ICRF vectors with down-leg light-time and stellar aberration (`LT+S`) on the
same daily TDB grid as the inherited reference. Apparent V magnitudes use
Horizons quantity 9 and support the conservative missing-bright-object screen.

Runtime is network-free. The builder records target IDs, JPL solution labels,
frame, time scales, corrections and content digest. Daily cubic interpolation
must be tested against withheld direct Horizons sub-day epochs. Do not imply
support for arbitrary minor planets.

## Verification

Keep every inherited scientific regression threshold. Add unit tests for FITS
and EXIF exposure provenance, direct count rates, clipped-wing recovery,
all-detection measurement, star/planet joins, offline minor-planet positions,
brightness, and withheld-epoch interpolation. Run the complete v8 suite and a
real MMTO FITS analysis, then run repository preservation tests and the required
root suite and demo before committing.
