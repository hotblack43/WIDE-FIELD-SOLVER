# Current development feature status

The published checkpoint remains v0.11.0. Historical runtime boundaries through
v22 are frozen by their manifests. V23 is the active aperture-photometry test
line.

## V23 in development

- Preserves v22 and tests aperture and local-sky radii read-only on native FITS.
- Uses held-out nights and requires one radius rule to improve R, G and B.
- The 71-image, 36-night test retained the v22 production rule. A 4-sigma
  aperture reduced scatter, but introduced held-out magnitude/PSF trends.
- Annuli scaled to detected blob width did not improve all three channels;
  the existing aperture+3 to aperture+7 pixel annulus remains the control.

## V22 frozen implementation

- Preserves the final v21 runtime and its transient Horizons retry behavior.
- Adds a read-only benchmark of local stellar ensembles, random forests,
  gradient boosting, and a small neural network.
- Selects the simplest method passing leakage-resistant validation before one
  final pseudo-planet test; a failed final test publishes no correction.
- Keeps all outputs as relative instrumental photometry and preserves raw and
  v21-control values beside any v22 result.
- Runs the benchmark as the final v22 photometry stage. Scientific rejection is
  recorded separately from operational failure and does not fail the pipeline.
- The corrected 2026-10-22 MMTO benchmark used 50,803 rows jointly held out by
  night and star identity and rejected all four methods. Blue-channel gains and
  PSF-width trends still failed, so corrected planet values remain unavailable.

## V21 frozen implementation

- Reuses verified local MMTO downloads before fetching a selected missing file.
- Checks the current MMTO observing night and any intervening nights missed
  since the previous invocation before filling remaining capacity from local
  unfinished work and the durable older-night cursor.
- Lists at most one observing night per remote request and preserves the
  per-invocation image cap.
- Reprocesses earlier-version receipts; only a v21 receipt suppresses v21 work.
- Parses old and new MMTO header generations, computes the exposure midpoint,
  rejects contradictory clocks, and never falls back to filename time.
- Reuses the existing append-only results and manifest databases.
- Forces the automated planet analysis to remain blind.
- Adds read-only post-fit MMTO site/time, airmass, refraction-direction, stellar
  epoch and secondary planet-candidate comparisons.
- Fits constrained per-exposure grey transparency terms with shared nightly
  extinction and fixed sample membership, using an exact sparse Jacobian so
  production-sized star networks do not require a dense SVD.
- Produces distinct-night same-sidereal-time differential transmission maps at
  unchanged measured centroids with no interpolation.
- Retries the derived planet-photometry stage only when its preserved log shows
  a transient JPL Horizons transport failure. Each failed attempt is retained,
  and successful products retain their requested output paths in provenance.

## Preserved limitations

- Metadata-derived airmass validates but does not replace the blind
  photometric-zenith fit.
- Planet epoch evidence remains secondary and may be ambiguous.
- The existing Monster2 distributor is pinned to v11 and is not a v21 runner.
- New hardware calibration is outside scope because there is no camera access.
