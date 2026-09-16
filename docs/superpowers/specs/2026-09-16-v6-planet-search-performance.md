# v6 planetary-search performance design

Date: 2026-09-16

## Purpose

Create an independent `v6/` runtime, version 0.6.0, that preserves the latest
`origin/main` v5 scientific behaviour while making the blind planetary epoch
stage substantially faster. The v5 package and `go5.sh` remain frozen and usable.
The new implementation must retain the full blind interval, causal upper date
bound, image-derived horizon checks, competing dates and identities, and exact
Astropy builtin ephemerides as the authority for saved candidates.

The performance acceptance target is at least a twofold reduction in the median
warm-cache planetary-stage wall time relative to v5 on the same machine and
image. The complete v5 and v6 launchers will also be timed on the Espenak image.
Scientific status and candidate identities must agree; any numerical differences
in exact candidate epochs or residuals must be tightly bounded, explained, and
recorded rather than hidden by relaxed regression thresholds.

## Version boundary

Version 6 starts from commit `1e22756`, the latest `origin/main` at design time.
It therefore includes the post-v0.5.0 sky-footprint, single-planet-alias and FITS
fixes. Copy that complete v5 package into `v6/`, then make v6-only changes.

Add `go6.sh` as the moving v6 launcher and `go_v0.6.0.sh` as the pinned launcher.
Both launch only `v6/run.sh`. Do not edit `go5.sh`, `go_v0.5.0.sh`, or any file
under `v5/`. Record a hash manifest for the frozen v5 boundary before v6 source
changes, and extend the root preservation instructions and guide to cover all
four included runtimes: legacy, v4, v5 and v6. The resulting checkout must work
without a `.worktrees` directory.

The v6 package owns its catalogue, example evidence, lockfile, ephemeris data,
source manifest and tests. Its reported version is `0.6.0` and run folders use
the v0.6.0 name. Historical reference inputs and products remain unchanged.

## Reference ephemeris artifact

Commit one exact float64 daily reference table for Mercury through Neptune over
Julian years 1850--2036 TDB under `v6/data/`. Generate it with the v6 locked
Astropy builtin ephemeris, never with site, image or observation-time metadata.
The table contains the complete Julian-date vector, normalized GCRS direction
vectors, schema number, Astropy and ERFA versions, model/frame/time conventions,
interval and step, and a SHA-256 digest over every numerical array.

The v6 loader validates all provenance, dates, shapes, finite values, norms and
the content digest before use. A valid bundled table is the first choice and
must not be copied or regenerated per analysis. If it is absent or incompatible,
v6 may rebuild the same reference-only data into its ignored writable cache, but
must print and record that expensive fallback explicitly. A corrupt bundled
artifact is an error rather than a silently trusted seed. The existing cache
builder becomes an explicit reproducible build/verify command.

The approximately 12 MB stored NPZ is acceptable. The binary artifact and its
generator are included deliberately in `v6/SOURCE_MANIFEST.json`.

## Ephemeris provider and interpolation

Introduce a focused ephemeris provider that exposes two visibly different paths:

- `interpolated(name, jd_tdb)` evaluates normalized cubic interpolation from the
  validated daily table and records call/date counters.
- `exact(name, jd_tdb)` evaluates the existing Astropy `get_body` builtin model
  and records call/date counters.

Interpolation is only a proposal and acceleration mechanism. It must never be
described as the fitted ephemeris and must not supply final saved positions,
altitudes, gate decisions, residuals or epochs. The implementation uses four
adjacent daily direction samples with normalized Catmull--Rom interpolation and
handles reference-table boundaries explicitly.

A deterministic validation test samples the entire 1850--2036 interval for all
seven planets and compares interpolated directions with exact Astropy directions.
The design probe used 4,000 dates per planet and found a worst sampled angular
error of 2.83 arcseconds. V6 adopts a documented conservative proposal guard
above the verified maximum. Interpolated gate or horizon proposals are widened
by that bound; exact evaluation decides whether each proposal survives. Tests
cover fast Mercury motion, retrograde folds, reference endpoints, rise/set
crossings and candidates close to the detector gate.

## Search and exact refinement

Keep the exact daily trajectory grid and existing spherical KD-tree segment scan.
It remains exhaustive over the blind interval but is not a naive product of all
dates and detections. The causal run-time ceiling still clips the actual search,
and neither stellar epoch nor image/site metadata may narrow or seed it.

Group coarse visit windows by planet. Within each group, interpolation cheaply
locates local minima, gate intervals and visibility crossings. Exact correction
then operates in batches by planet. A vectorized bounded minimizer evaluates all
active windows for one planet at each iteration through a single exact Astropy
call, rather than invoking `get_body` separately for every scalar optimizer step.
It retains the existing date tolerance and searches the full original local
bracket, so interpolation cannot move the exact solution outside consideration.
Exact batched bisection or exact final checks resolve gate and horizon boundaries.

Joint multi-planet assignments retain the existing Hungarian assignment logic,
cardinality-first ranking and reassociation limit. Interpolation may propose the
joint date, but exact positions for every participating planet determine the
returned date, membership, visibility, residuals and uncertainty. All final
non-detection evidence and same-epoch display projections also use exact vectors.

V5 and v6 comparison tests require the same retained planet/source identities,
candidate classification and ambiguity status. Candidate dates must agree within
the existing optimizer tolerance where the objectives are isolated and stable;
detector residual differences receive an explicit small bound derived from exact
evaluations. Boundary and degenerate cases compare semantic outcomes rather than
inventing precision.

## Parallel execution and determinism

Refine independent planet groups in a process pool with at most four workers by
default. Use no more workers than there are nonempty planet groups. The environment
variable `WFS_PLANET_WORKERS` accepts a positive integer; `1` selects the serial
reference path used for reproducibility and debugging. Invalid values fail with
a concise error before search work begins.

Workers receive only reference tracks and the fixed measured/model inputs needed
for their planet. They do not read metadata, mutate output files, select a global
winner, or write logs. The parent process merges returned passages, counters and
timings in canonical planet/date/source order before joint assignment. Serial and
parallel runs must produce identical JSON/CSV candidate content apart from their
explicit performance fields. Worker completion order must not affect candidates,
ranking, printed output or plots.

## Performance telemetry

Record a versioned `planet_search_performance` object in `planet_epoch.json` and
write the same object to `planet_search_performance.json`. It contains at least:

- cache source, cache digest, cache bytes, load time and any build time;
- requested and used worker counts;
- coarse segment-scan, interpolated refinement, exact refinement, joint
  assignment, negative-evidence and total planetary-stage wall times;
- interpolated and exact provider call counts and evaluated-date counts;
- refined visit, source-candidate and joint-trial counts.

Use `time.perf_counter()` around named stages. Timings and execution counters are
diagnostic only: they cannot affect candidate selection or scientific status.
Print one compact end-of-stage summary so a user can distinguish cache loading,
coarse scanning and refinement without reading JSON. Tests assert schema and
counter consistency, not wall-clock thresholds.

## Verification and benchmarks

Develop production behaviour test-first. Unit and integration evidence includes:

1. bundled-cache validation, reuse, corruption, incompatibility and fallback;
2. interpolation accuracy and conservative proposal containment;
3. batched exact minimization versus the v5 scalar exact reference;
4. exact authority over final gates, horizon checks, dates and residuals;
5. identical serial and four-worker candidate products;
6. existing blindness, causal-ceiling, visibility, association competition,
   ambiguity and negative-evidence regressions;
7. performance telemetry and a material reduction in exact call count;
8. launcher/version isolation and v5 hash-manifest preservation.

Wall-time assertions do not belong in unit tests. A benchmark command runs the
v5 and v6 planetary stages against equivalent solved inputs, performs at least
three warm repetitions, and reports individual values, medians and speed ratio.
It also compares the scientific JSON/CSV products while excluding documented
performance fields. Run one complete `go5.sh` and one complete `go6.sh` analysis
of `/home/pth/Skrivebord/StarTrails/FishEye18-1021w_Espenak.jpg` and record the
machine, worker count, cache state, stage times, total times and numerical
comparison in the v6 performance documentation.

Before publication, run unit discovery and the preserved demo separately in the
legacy root, `v4/`, `v5/` and `v6/`, using unique output directories. Run the v5
runtime-manifest verification and regenerate/verify the v6 source manifest.
Failures must be fixed; thresholds or historical products must not be weakened.

## Documentation and limitations

Update the root guide, consolidated preservation instructions, v6 README, v6
feature status and v6 performance document. State that the search is still a
full-interval blind trajectory search, that interpolation only accelerates
candidate proposals, and that every reported candidate uses exact Astropy builtin
ephemerides. Retain the established limitations: geocentric rather than
topocentric positions, approximate builtin ephemerides, frame/aberration and
refraction differences, conditional local timing uncertainty, and uncalibrated
false-alarm probability.

Do not narrow the date range around metadata or the stellar epoch, increase the
daily step without a new completeness proof, omit alternative dates, move plotted
measurements, change the fitted camera, or turn performance counters into fitting
inputs.
