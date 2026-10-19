# Current development feature status

The published checkpoint remains v0.11.0. Historical runtime boundaries through
v20 are frozen by their manifests. V21 is the active MMTO FITS-header-timed
development line.

## V21 implemented

- Reuses verified local MMTO downloads before fetching a selected missing file.
- Checks the current MMTO observing night before filling the invocation cap
  from older local backlog, then resumes the durable older-night cursor.
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

## Preserved limitations

- Metadata-derived airmass validates but does not replace the blind
  photometric-zenith fit.
- Planet epoch evidence remains secondary and may be ambiguous.
- The existing Monster2 distributor is pinned to v11 and is not a v21 runner.
- New hardware calibration is outside scope because there is no camera access.
