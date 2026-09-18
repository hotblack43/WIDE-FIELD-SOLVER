# Raw All-Sky Acquisition Design

**Date:** 2026-09-18

**Status:** Approved in chat on 2026-09-18

## Purpose

Build a small, reproducible dataset of genuine high-dynamic-range colour
all-sky observations. The work must find public original files, download only a
controlled time sample, inspect the stored numerical data, and retain enough
provenance to repeat or automate the acquisition later.

This is an independent data-acquisition subsystem. It must not import runtime
code or data from another project, and it must not modify or replace any
preserved solver launcher or version. The existing specialised MMTO downloader
under `scripts/mmt_archive/` remains intact. Its verified archive-timing lessons
may inform the new MMTO adapter, but the new interface has a different,
multi-source purpose.

## Scope

Investigate these source families:

1. MMTO all-sky camera.
2. University of Calgary TREx-RGB, specifically `TREX_RGB_RAW_NOMINAL`.
3. PRESENTE / GOA-SCAN.
4. Rubin Observatory / LSST all-sky camera.
5. OASI all-sky camera.
6. Public installations of INDI-AllSky.

For an initial run, download only a few representative nighttime observations:
normally one to three files per source, while seeking two independent cameras
for TREx-RGB and PRESENTE and three independent cameras for INDI-AllSky when
public raw access permits. Empty source directories are retained for sources
that prove restricted, unsuitable, unresolved, or processed-only.

Bulk mirroring, authentication bypasses, guessed private endpoints, cron
installation, Moon filtering, and solar-altitude filtering are outside this
initial implementation. The architecture preserves site coordinates and UTC
timestamps so `--moon-down` and `--sun-below` can be added without replacing the
selection model.

## Evidence and Classification

A source receives exactly one public status:

- **SUCCESS:** An original file was downloaded, decoded, numerically inspected,
  shown to contain genuine colour or Bayer measurements above ordinary 8-bit
  rendered information, and found to contain or credibly show usable point-like
  stars.
- **ACCESS RESTRICTED:** Authoritative evidence establishes that suitable raw
  files exist, but access needs credentials, an application, or direct contact.
- **RAW NOT FOUND:** The colour camera or archive is public, but diligent search
  located only rendered or otherwise processed products.
- **UNSUITABLE:** Public originals were inspected and failed the colour,
  dynamic-range, coverage, or point-star requirement.
- **UNKNOWN:** Available evidence does not decide the question. The unresolved
  fact and attempted routes are recorded.

Documentation alone can support an access or existence claim, but never
`SUCCESS`. Search snippets are leads, not evidence. Every successful source row
links the exact original URL and records the local relative path and SHA-256.
Licensing or reuse terms are recorded when an authoritative statement exists;
silence is reported as unknown rather than interpreted as permission.

## Repository Layout

The implementation adds these focused units:

```text
download_samples.py                 command-line entry point
inspect_allsky_samples.py           reproducible numerical inspection entry point
allsky_download/
  __init__.py
  model.py                          candidate, site, and result records
  cadence.py                        deterministic time-slot selection
  http.py                           bounded listing and transfer client
  manifest.py                       transactional download/inspection ledger
  registry.py                       adapter lookup and source capability reporting
  sources/
    mmto.py
    trex_rgb.py
    presente.py
    rubin.py
    oasi.py
    indi_allsky.py
  inspect.py                        FITS, HDF5, and camera-RAW inspectors
tests/
  test_allsky_cadence.py
  test_allsky_cli.py
  test_allsky_http.py
  test_allsky_manifest.py
  test_allsky_sources.py
  test_allsky_inspect.py
raw_allsky_samples/
  mmto/
  trex_rgb/
  presente/
  rubin/
  oasi/
  indi_allsky/
  manifest.sqlite
  inspection.json
SOURCES.md
sources.json
```

Only adapters with a verified legitimate public listing route expose downloads.
An investigated but inaccessible source still has a registry entry and
documented status; it does not get invented URL patterns or a nonfunctional
adapter implementation.

Original files live beneath `raw_allsky_samples/<source>/<camera>/` and retain
their remote basename whenever this is safe and unambiguous. Derived previews,
if needed to evaluate stars, live in a separate `derived/` subtree and are
clearly labelled. Inspectors open originals read-only and never rewrite them.

## Archive Adapter Contract

Every operational source adapter provides:

1. Stable source and camera identifiers.
2. Site name, latitude, longitude, elevation when known, and IANA timezone.
3. A `list_candidates` operation that contacts only listings, metadata APIs, or
   comparably lightweight archive objects.
4. Observation timestamps parsed from authoritative listing/API metadata or
   filenames whose convention has been verified against file metadata.
5. Original URLs, filenames, and advertised sizes when available.
6. A transfer operation delegated to the common HTTP layer.

Candidate listing must finish before selection and raw transfer. If observation
times cannot be learned without downloading large originals, that source must
fail closed for ranged cadence downloads or use a documented small metadata
sidecar/header-range mechanism. It must never download every raw file merely to
discover which ones satisfy cadence.

Adapters normalize observation times to timezone-aware UTC while retaining the
source timestamp and its interpretation. Archive bucket dates are not assumed
to equal observation dates. In particular, MMTO's verified noon-to-noon bucket
and local-clock FITS convention are handled explicitly.

## Date and Cadence Semantics

`--date YYYY-MM-DD` denotes one civil day, from local midnight inclusive to the
next local midnight exclusive, in the selected camera's registered IANA
timezone. `--start YYYY-MM-DD --end YYYY-MM-DD` denotes a half-open range of
local civil dates: start is included and end is excluded. A multi-camera source
applies these boundaries separately using each selected camera's timezone.

The default cadence is `10m`. Accepted duration units initially include seconds
(`s`), minutes (`m`), and hours (`h`), with a strictly positive integer or
decimal magnitude. Omitting cadence never means all files. An explicit future
bulk mode would require a separately named opt-in and is not part of this work.

For each camera independently:

1. Convert the requested local range start to UTC; this is cadence boundary 0.
2. Form half-open slots `[start + k*cadence, start + (k+1)*cadence)`.
3. In each nonempty slot select the earliest candidate at or after the slot's
   lower boundary. Break identical-timestamp ties by normalized URL.
4. Leave an empty slot empty; do not borrow an observation from a later slot.
5. Apply `--max-files` to the combined deterministically ordered selection
   before any raw transfer.

This produces no more than one file per cadence interval, uses actual
observation time, and returns the same selection for an unchanged listing.
Output ordering is observation UTC, source identifier, camera identifier, then
URL.

When supplied, `--max-files N` must be a positive integer and is an absolute cap
for the whole invocation. The CLI default is 20 files as an additional guard. A
request whose deterministic selection exceeds the cap is
truncated predictably and reported as such; it never silently transfers more.

## Dry Run and Transfer Safety

`--dry-run` may retrieve archive pages, indices, metadata records, and advertised
object sizes. It must not request a raw object's body. It prints:

- normalized observation timestamp;
- source and camera;
- remote filename and URL;
- advertised size or `unknown`;
- selected count, cap/truncation state, and known total volume;
- a warning that unknown sizes are excluded from the volume estimate.

The common client uses explicit connect/read timeouts, a descriptive user agent,
bounded exponential retry with jitter-free deterministic delays, and no
interactive prompts. It retries transient network/server failures but not
permanent authentication or not-found responses. Downloads go to a same-folder
temporary file, are flushed, hashed, validated for size when known, and
atomically renamed. Interrupted temporary files are not treated as originals.

The downloader exits 0 only when all selected files are already verified or
have been downloaded and verified. Invalid arguments use the normal CLI error
exit. Listing/transfer/validation failures produce a nonzero operational exit
while retaining per-file failure records and continuing with independent files
where safe.

## Duplicate Avoidance and Manifest

`raw_allsky_samples/manifest.sqlite` is the transactional ledger. It records:

- source and camera identifier;
- normalized observation UTC and raw timestamp;
- remote URL and filename;
- local relative path;
- advertised and observed byte size;
- SHA-256;
- download and validation status;
- attempt time and diagnostic error;
- inspector kind and inspection-record identifier.

The remote URL is unique. Before transfer, a successful existing row is accepted
only when its local file exists and its size and SHA-256 still match. Otherwise
the discrepancy is recorded and the file is reacquired through the temporary
path. SQLite transactions make repeat and cron executions durable. A process
holds a repository-output lock during manifest mutation and transfer planning so
two cron invocations cannot race into duplicate downloads.

## Scientific Inspection

Inspection results are written reproducibly to
`raw_allsky_samples/inspection.json` and summarized in `SOURCES.md`.

For FITS, inspect every HDU and record header-derived dimensions, `BITPIX`,
stored/scaled dtype, channel axes, Bayer-related keywords, exposure, observation
time, and camera/site identifiers. For every numerical image array record the
finite count, minimum, maximum, median, selected percentiles, and fraction at
the declared or observed saturation level. Count distinct values exactly when
an integer array's value span is at most 1,000,000; otherwise report the distinct
count from a deterministic regularly spaced sample of at most 1,000,000 pixels
and label it as sampled.

For HDF5, recursively record every group and dataset path, shape, dtype,
attributes relevant to Bayer layout, exposure, timestamp, site, camera, gain,
black level, white level, and calibration. Numerical image datasets receive the
same range and percentile statistics.

For camera RAW, inspect the genuine sensor array rather than the embedded
preview. Record visible/raw dimensions, raw dtype, Bayer pattern or colour
descriptor, black and white levels, exposure, ISO, timestamp, numerical range,
percentiles, and saturation fraction. Preserve the original camera file.

Container width alone is not treated as effective dynamic range. Reports
separate documented ADC depth, stored dtype width, and observed occupied range.
Observed range includes at least `ceil(log2(max - min + 1))` where meaningful,
but is labelled as an empirical lower-bound-style diagnostic rather than a
camera specification. Values exceeding 255 are necessary but not sufficient;
documentation, raw layout, level population, scaling metadata, and processing
history are considered together.

Point-like stars are assessed from a losslessly decoded or explicitly labelled
display stretch. The evidence records whether ordinary stars are visually
present and approximately point-like; uncertainty is reported rather than
turning a daytime, cloudy, trailed, or ambiguous frame into a success.

## Source Research Method

Research begins from the supplied official pages and follows legitimate public
links, archive listings, APIs, code repositories, publications, and institutional
storage. Exact URLs and access dates are retained. For Rubin, the search extends
beyond SMTN-005 but accepts only unauthenticated public CR2 originals. For OASI
and INDI-AllSky, attractive web JPEGs do not count; server HTML and documented
public structures may be examined, but authentication boundaries and
non-indexed private paths are not probed.

For MMTO, inspect the archive root and nearby public paths to decide whether raw
archiving stopped around 2026-06-23, moved, or changed structure. For Calgary,
locate `TREX_RGB_RAW_NOMINAL` originals and official decoding guidance. For
PRESENTE, distinguish documented 14-bit HDF5 capture from publicly downloadable
HDF5 and record the appropriate institutional contact if access is restricted.

## Configuration and Documentation

`sources.json` is machine-readable public configuration and research status. It
contains no credentials. It records stable IDs, display names, public roots,
camera/site metadata, timezone and coordinates, adapter availability, archive
coverage when established, status, and authoritative documentation links.

`SOURCES.md` contains the requested results table, exact original URLs, decoded
properties, measured statistics, archive coverage, access result, licensing,
and bounded notes on unsuccessful routes. `README.md` gains concise examples for
dry-run, one date, a date range, cadence, maximum files, and camera selection,
plus cron-oriented exit/logging guidance. It states that Moon and Sun switches
remain future work until they are scientifically implemented.

## Testing and Verification

Development follows test-first cycles. Unit and local integration tests use a
local HTTP server and synthetic FITS/HDF5 fixtures; they do not depend on live
archives. Tests cover:

- duration parsing and rejection;
- local-date and DST-aware range conversion;
- deterministic slot selection, ties, gaps, multiple cameras, and cap ordering;
- dry-run making no raw-body request;
- size estimates with unknown sizes;
- retry/non-retry status handling and timeout paths;
- atomic transfer and corrupt/truncated transfer rejection;
- checksum-based duplicate reuse and changed-file reacquisition;
- manifest transactions and concurrent-run exclusion;
- source-specific listing/timestamp fixtures captured from public structures;
- all-HDU FITS, recursive HDF5, and genuine raw-array inspection interfaces;
- CLI exit codes and actionable logs.

Live smoke tests use only narrow date/camera queries and `--max-files` values.
Before any commit, run the repository-required commands:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Before declaring the acquisition work complete, also run the focused downloader
tests, representative dry runs, manifest/checksum verification, and inspection
regeneration from the preserved originals. No regression threshold is relaxed.

## Acceptance Criteria

The work is complete when:

1. All six requested source families have evidence-backed public statuses.
2. Every `SUCCESS` has an unchanged local original, SHA-256, exact URL, decoded
   numerical inspection, colour/Bayer evidence, dynamic-range evidence, and star
   assessment.
3. The downloader selects by observation time before raw transfer, defaults to
   ten minutes, obeys an absolute maximum, and has a body-free dry run.
4. A repeat invocation does not redownload a verified unchanged original.
5. The CLI handles a single date, half-open date ranges, source selection, and
   camera selection without interaction.
6. Documentation accurately distinguishes successful, restricted,
   processed-only, unsuitable, and unresolved sources.
7. Preserved solver versions, historical examples, and existing user changes
   remain untouched, and all required regressions pass.
