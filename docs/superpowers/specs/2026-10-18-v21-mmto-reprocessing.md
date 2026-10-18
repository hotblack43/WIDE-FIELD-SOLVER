# V21 MMTO Header-Time Reprocessing Design

## Purpose

V21 reprocesses the existing MMTO FITS archive with authoritative exposure
times from the FITS headers and known MMTO site coordinates.  It continues the
bounded backward acquisition when required images are absent, without changing
the blind stellar, astrometric-refraction, photometric-zenith, or planetary
fits.

MMTO site metadata are latitude `+31.6866666667` degrees, longitude
`-110.8841666667` degrees east-positive, and elevation `2616` metres.

## Version and evidence boundary

- Freeze the committed v20 runtime before creating v21.  Temporary uncommitted
  timing experiments do not become part of v20.
- V21 has its own package, launchers, catalogue, ephemeris data, lockfile,
  source manifest, tests, receipts, output directories, and backfill state.
- Continue using the append-only `results/stars.sqlite`.  V16--v20 rows remain
  unchanged; v21 appends runs labelled `0.21.0`.
- Continue using `raw_allsky_samples/manifest.sqlite`.  Preserve the existing
  archive-listing timestamps and add a separate v21 table containing
  authoritative header start, exposure, midpoint, schema, and provenance.
- An existing receipt counts as completed v21 work only when its solver version
  or embedded source-manifest version is `0.21.0`.  Older receipts avoid no
  download because the archive file already exists, but do not suppress v21
  analysis.  A v21 receipt counts regardless of exit status, retaining the v20
  rule that a repeatedly failing file does not block the backward walk.

## Acquisition and processing

Each invocation retains the v20 configurable image cap and one-MMTO-night-at-a-
time remote listing rule.

1. Select verified, already-downloaded files without a v21 receipt first,
   newest first and with the established cadence de-duplication.
2. If capacity remains, continue the durable look-back cursor one night at a
   time.
3. Reuse and checksum-validate local files.  Download only selected files that
   are absent or fail validation.
4. Parse and validate the FITS header before invoking the solver.  Scientific
   observation time is never taken from the filename, URL, directory name, or
   archive listing.
5. Run the v21 solver blindly with the planet metadata path forced blind.
6. Only after the solver receipt exists, generate separate known-site/time
   validation products.
7. Regenerate aggregate photometric, planetary, transparency, and
   same-sidereal-time products from successful v21 runs.

The full downloaded backlog may require many invocations.  The cap bounds each
invocation; it does not redefine the desired v21 coverage.

## Authoritative MMTO header time

The parser recognises the MMTO ZWO ASI294MC Pro camera and supports both known
header generations:

- Older files: naive `DATE-OBS` and `UT` are Arizona local exposure start.
  Convert with `America/Phoenix` (UTC-7), cross-check the two start fields and
  the UTC `DATE` creation field, and calculate midpoint as start plus half the
  header exposure duration.
- Newer files: `DATE-BEG` is UTC exposure start and `DATE-END` is UTC exposure
  end.  Cross-check their duration, the local `DATE-OBS` value, and the header
  exposure duration.  Calculate midpoint from start plus half the header
  exposure duration.

Conflicting or incomplete MMTO time fields are an explicit operational failure.
There is no filename fallback for a recognised MMTO FITS file.

## Blindness and planet result

No timestamp, longitude, latitude, elevation, metadata-derived airmass, saved
identity, or earlier receipt may seed, constrain, rank, or tune the blind fit.
The primary result remains the stellar Barghini solution and its coupled
refraction/photometric-zenith evidence.

Retain the global blind planet epoch search because it can sharply constrain an
epoch.  Present it as a secondary result with its candidates, ambiguity,
visibility evidence, and limitations independently inspectable.  Compare its
fixed result with the header epoch only in the post-fit validation product;
agreement must not feed back into the stellar or planetary fit.

## Post-blind known-site/time validation

For each completed v21 run, write a separate validation record that includes:

- authoritative header start, exposure, and midpoint with parser provenance;
- known MMTO coordinates and elevation;
- stellar-epoch minus header-epoch difference;
- blind photometric-zenith versus metadata-predicted zenith separation;
- blind derived latitude versus known MMTO latitude;
- saved blind airmass versus metadata-derived airmass for fitted stars;
- integrated-refraction direction versus metadata-predicted zenith when the
  fitted product supports that comparison; and
- blind planet epoch/candidate comparison with the header epoch, explicitly
  labelled secondary and post-fit.

The validator reads completed products and never rewrites fitted coordinates,
memberships, parameters, residuals, or planet candidates.

## Per-exposure grey transparency

For each night and channel, fit the robust model

`m_machine(s,i) = a_s + k_night X(s,i) + Z_i`

on the fixed eligible sample.  Here `a_s` is one stellar intercept,
`k_night` is the common extinction coefficient, and `Z_i` is one grey
transparency offset per image.  Constrain the mean accepted-image `Z_i` to zero
to remove the additive degeneracy.  Use soft-L1 loss and report rank/leverage,
uncertainties, sample membership, residuals, and failures rather than silently
falling back.  The absolute photometric zero point is the representative
catalogue-referenced stellar offset plus the relative `Z_i`.

Write per-image transparency tables and time-series figures.  V21 corrected
photometry subtracts both `k_night X` and the fitted per-image grey term.

## Same-sidereal-time transmission maps

Use only successful v21 runs with authoritative header midpoints.  Compute
local apparent sidereal time from the midpoint and known longitude after all
blind products are fixed.  Pair exposures from different observing nights
within a documented sidereal-time tolerance.  Match the same catalogue stars,
form channel-wise magnitude differences, retain the pair-wide grey difference,
and map the median-centred residuals at faithfully measured pixel positions.

Export pair selection/audit tables, per-star differential transmission rows,
and labelled maps.  Do not move measured positions or infer a physical cloud
height.  If coverage is insufficient, write an explicit insufficient-data
status rather than a decorative interpolation.

## No hardware-dependent work

V21 makes no recommendation or requirement for new MMTO hardware, calibration
flats, darks, laboratory linearity measurements, or changes at the observatory.
Those are outside the available access and this implementation scope.
