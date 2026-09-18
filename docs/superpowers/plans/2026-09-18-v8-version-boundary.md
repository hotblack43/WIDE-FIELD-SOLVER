# V8 preservation and scientific-upgrade implementation plan

**Goal:** Freeze v7 and deliver v0.8.0 with offline Ceres/Vesta searches,
exposure-normalized count rates for identified sources, and separately audited
saturated-wing photometry.

**Constraints:** Detached HEAD only; no branches. Never modify preserved v7
bytes. Keep raw measurements and model estimates distinct. Preserve blind-fit
and metadata-validation boundaries.

## Tasks

- [x] Add preservation tests, track the four unchanged historical v7 images,
  and generate `docs/v7-runtime.json`.
- [x] Clone the staged v7 package into self-contained v8 and add v0.8.0
  launchers, identity, lockfile and launcher tests.
- [x] Add exposure provenance for FITS `EXPTIME`/`EXPOSURE` and EXIF
  `ExposureTime`, retaining missing/conflicting status.
- [x] Add per-channel aperture ADU and ADU/s for every detection; retain
  stellar, planet-candidate and combined identified-source views.
- [x] Add robust masked Moffat-wing models for saturated channels with separate
  total, count rate, centroid, fit RMS and quality status; keep them out of the
  extinction/zenith regression.
- [x] Generate and validate the committed 1850--2036 Ceres/Vesta JPL Horizons
  position and apparent-magnitude reference; extend search and negative evidence.
- [x] Pass the complete 300-test v8 suite (one optional DS9 skip) and run the
  real MMTO three-plane FITS through `go8.sh`.
- [x] Regenerate `v8/SOURCE_MANIFEST.json`, finish root/v8 documentation, run
  all preservation/root/demo checks, inspect the final diff, and commit on
  detached HEAD.
