# Current development feature status

The published checkpoint remains v0.11.0. Historical runtime boundaries through
v23 are frozen by their manifests. V24 is the active camera-installation
visible-sky-mask line.

## V24 in development

- V24 now contains generic calibration machinery for any supported fixed
  all-sky camera: sealed review proposals, immutable revision and approval,
  layered append-only registries, explicit activation, checksum-keyed source
  assignments, opt-in downloader integration, and automatic launcher
  resolution. The existing unmasked numerical path remains available and is
  recorded as `not_configured`.
- A sealed MMTO cold-start replay freshly verified 3,194 native FITS originals
  across 116 dates, reserved every fifth sorted date (669 frames on 24 dates),
  and generated the proposal from 92 phase-cycled calibration dates before the
  approved mask was revealed. The sealed result has 98.418% exact pixel
  agreement, mask IoU 0.9751, mean boundary separation 5.50 pixels, and p95
  separation 13.93 pixels from the approved MMTO reference. Production
  point-source detection was also run on all 669 held-out frames: 380,048
  unmasked detections were audited, with 10,539 supports intersecting the
  proposed boundary and 3,410 wholly inside the excluded region. This is MMTO
  evidence only: the generic workflow is not yet validated on a real non-MMTO camera.
- A same-model FITS header that omits the known camera serial is compatible;
  a different explicit serial remains fatal. A camera move, rotation, crop, or
  replacement requires a new installation ID and approved artifact.
- The packaged v24 MMTO demo uses the approved mask rather than the legacy
  unconfigured path. Its versioned baseline records the expected numerical
  change from 1,526/1,409 unmasked detections/associations to 1,362/1,280 masked
  detections/associations and requires the exact approved mask checksum.

- The concurrent MMTO batch retains each solver's complete command, diagnostics,
  and traceback in its private `run.log`, while the terminal prints only one
  `SOLVER EXIT` line with that evidence path. A failed blind bootstrap remains a
  recorded per-image solver failure and does not resemble a pipeline crash on
  the routine terminal display.
- Receipt validation starts only after every concurrent solver has finished its
  atomic SQLite append. This removes the rollback-journal reader/writer race on
  the large shared results database without changing solver concurrency,
  receipts, or scientific results.
- The v24 pipeline carries its own launchers and implementations for grey
  extinction, same-sidereal transmission, known-site/time validation, and the
  differential-photometry benchmark; each configured derived stage is checked
  by starting its exact command with `--help`.
- Differential-photometry control replay combines the versioned v21, v23, and
  v24 FITS-header observation sidecars read-only. This preserves exact replay
  of the cumulative nightly-extinction population when it contains frozen v23
  receipts, while only v24 receipts count as completed masked solver work.
- A v24 MMTO run cannot report `complete` unless all 33 fixed figure paths from
  the latest complete v23 output contract exist and are non-empty. This
  explicitly includes the R, G, and B planet plots against UTC time and hours
  past local noon. Same-sidereal map counts remain data-dependent.

## Independent OpenOrb planet experiment

- `go_find_planet_openorb_v1.sh` is a new, independent native OpenOrb 1.3.0
  workflow; it does not change or import any frozen solver runtime.
- A controlled answer-key stage exports anonymous dated MMTO directions, then
  withholds every fifth observing night before OpenOrb sees the fit input.
- Two date-only statistical-ranging seeds each request 5,000 accepted samples;
  OpenOrb LSL supplies the nominal elements and covariance, and OpenOrb itself
  predicts the withheld epochs.
- The first real end-to-end run is predictive relative to fixed-direction and
  angular-velocity baselines but remains `multimodal`. The known-planet
  comparison occurs only after the anonymous evidence is sealed and does not
  establish a Mars identification.

## V23 frozen implementation

- The MMTO v23 pipeline runs four independent, single-threaded image solvers
  concurrently by default; `--solver-workers N` changes the bound. Each solve
  still receives its own run directory and appends one atomic SQLite receipt.
  The batch path invokes the pinned v23 interpreter directly and forces
  display-name resolution offline, avoiding repeated shell/uv startup and
  failed SIMBAD waits without changing astrometry, photometry, or epoch fits.
- The variable-star product is now
  `variable-stars/variable_star_phase_curves.pdf`; v23 no longer emits the
  inherited chronological `variable_star_time_series.pdf`. Each star is folded
  into `[0,1)` with its frozen VSX period and earliest plotted UTC as phase zero.
  Magnitudes, nightly flux averaging, selection, and fixed-period sine-fit
  values are unchanged.
- MMTO v23 now writes `acquisition_timeline.pdf` and its per-image CSV after
  acquisition and solver processing, before derived photometry. The report
  separates newly downloaded from reused images by observing night and shows
  solver successes and failures, plus the current night and durable backward
  cursor. Its path is repeated in the terminal if a later stage fails. This
  changes reporting only; selection, receipts, fits, and numerical results are
  unchanged.
- Preserves v22 and tests aperture and local-sky radii read-only on native FITS.
- Uses held-out nights and requires one radius rule to improve R, G and B.
- The 71-image, 36-night test retained the v22 production rule. A 4-sigma
  aperture reduced scatter, but introduced held-out magnitude/PSF trends.
- Annuli scaled to detected blob width did not improve all three channels;
  the existing aperture+3 to aperture+7 pixel annulus remains the control.
- The differential-photometry figure set now consumes the fresh cumulative
  nightly-extinction population built by the same v23 invocation. It no longer
  replays the fixed v21 run list, and plot legends/metric fields call this the
  current nightly control. Versioned v21 and v23 FITS-header observation tables
  are combined read-only so newly accumulated v23 images enter the figures.
- Post-fit known-site validation transforms all stellar coordinates from one
  exposure as a vector, rather than repeating the same Astropy frame setup for
  every star. A 1,200-coordinate regression case fell from about 5.1 seconds to
  about 1.6 seconds on the development machine, with unchanged altitude,
  airmass and refraction-direction values.
- Fitted stellar Julian years are interpreted as TDB during the separate
  header-time comparison. This avoids extrapolating UTC leap seconds for old
  blind epoch estimates; only the post-fit absolute time difference changes,
  by the applicable TDB-minus-UTC offset (32.2 seconds for the observed
  1937--1958 estimates). The fitted epoch and astrometry are unchanged.
- Same-sidereal transmission keeps every map path in its saved manifest but
  prints only the map count and directory in routine stage output and the
  final terminal/pipeline-log figure listing; individual map paths are not
  enumerated there.
- MMTO acquisition checks the current and intervening remote nights, then the
  durable older-night cursor, before spending any remaining image allowance on
  cached local backlog. Within a listed night, previously unseen remote images
  take priority over already downloaded files, while the per-invocation image
  cap and one-night-at-a-time archive access remain unchanged.
- MMTO v23 acquisition independently checks the public summit weather-history
  API for both outside Vaisala relative-humidity sensors. For each candidate it
  uses the larger fresh reading nearest the candidate UTC time: humidity below
  80% is accepted and humidity at or above 80% is skipped. A reading is fresh
  through an absolute age of 120 seconds. Missing, stale, malformed, or failed
  telemetry fails open, so the image proceeds without manual intervention.
  Weather decisions are made before the image cap is spent and are recorded in
  each run's `weather-decisions.jsonl`; weather never enters the blind fit.
- The extinction-plus-distance planet plot keeps the accepted nightly
  extinction thresholds unchanged. Recent planet measurements that lack an
  accepted nightly extinction fit are now shown separately as open,
  unconnected distance-only points, with aperture-only uncertainty, and are
  exported to `planet_distance_only_uncalibrated_measurements.csv`; filled
  points remain the fully extinction- and distance-corrected population.
- The v23 planet-photometry stage now handles R, G, and B in one process.
  Each source FITS is checksum-verified and decoded once for all three
  uncertainty calculations, and the shared distance ephemeris is built once;
  the existing per-channel CSV and PDF products remain unchanged.

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
- Real non-MMTO calibration evidence is not yet available because no second
  fixed camera installation has been supplied for validation.
