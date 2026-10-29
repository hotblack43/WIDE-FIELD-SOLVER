# Find Planet OpenOrb v1 Design

## Intent

Replace the stopped generic SciPy orbit-fitting experiment with a new,
independent launcher family whose orbit inversion is performed by OpenOrb
1.3.0.  The experiment remains controlled: a pinned answer key selects the
MMTO detections, but the orbit engine receives only an anonymous designation,
dated measured directions, declared uncertainties, and observatory code.  The
result must be sealed before any comparison with known planetary orbits.

This is the professional-software route selected after the first prototype's
brute-force bootstrap was stopped.  The stopped branch, its commits, and its
three run directories remain evidence; they are not repointed as OpenOrb
results and are not deleted.

Implementation starts from the intact main branch in a new worktree.  The
stopped `find-planet-controlled-v1` branch remains unmerged.  Only the
controlled extraction and saved-camera behavior independently reimplemented
and retested in the OpenOrb runtime may cross that boundary; the generic
fitter, bootstrap, reports, and incomplete documentation do not enter the
delivered main line.

## Goals

- Build a new `go_find_planet_openorb_v1.sh` family without changing any
  existing solver launcher, frozen version, database, raw image, historical
  reference product, or the stopped `find_planet_v1` prototype.
- Convert the exact pinned controlled MMTO centroids into anonymous OpenOrb
  observations with per-observation astrometric uncertainty.
- Use OpenOrb statistical ranging for initial orbit probability sampling and
  OpenOrb least-squares/differential correction for the nominal solution and
  covariance.
- Withhold every fifth chronological observing night before any orbit fit and
  assess OpenOrb ephemerides on those untouched nights.
- Preserve OpenOrb's raw inputs, configuration, stdout/stderr, sampled orbits,
  nominal orbit, residuals, covariance, ephemerides, build receipt, data
  receipt, and exact executable hash in a sealed evidence directory.
- Keep known-object identification as a later, separate reveal step.

## Non-goals

- Do not retain the generic SciPy optimizer as a fallback behind the OpenOrb
  launcher.
- Do not create a strict blind source-linking search in this version.
- Do not claim Object A is Mars, or tune OpenOrb settings after comparing with
  Mars.
- Do not submit observations to the Minor Planet Center or publish externally.
- Do not implement OrbFit integration in this version.  Preserve a clean
  adapter boundary so OrbFit can later provide independent validation.

## Anti-goals

- No hidden use of a known Mars position, distance, elements, Horizons row, or
  DE441 Mars state during anonymous inversion.
- No invocation-specific downloading of changing ephemeris or observatory
  files.
- No unpinned system-wide OpenOrb installation and no silent fallback to a
  different executable or data directory.
- No conversion of optimizer completion into a scientific-success claim.
- No deletion or rewriting of the stopped prototype or failed/interrupted run
  evidence.

## Approaches considered

### OpenOrb primary, OrbFit adapter later — selected

OpenOrb's statistical ranging is explicitly designed for scarce or short-arc
astrometry and maps a non-Gaussian orbital probability distribution.  It can
then seed its least-squares solution and produce topocentric ephemerides.  Its
native executable gives a clean process boundary from Python and avoids the
known fragility of the `pyoorb`/f2py wrapper.  OrbFit remains a future
independent validator, not a second engine mixed into the first result.

### OrbFit `fitobs` primary

OrbFit provides mature propagation, orbit determination, astrometric error
models, covariance, and close-approach machinery.  Its configuration and
initial-orbit workflow are more involved for this anonymous short-arc first
experiment, and it would add more integration uncertainty before the basic
observation export is independently validated.

### Dual OpenOrb and OrbFit in one first release

Independent agreement would be scientifically attractive, but two native
Fortran builds, two data models, and two configuration surfaces would make it
harder to distinguish an astrometry/export error from an engine-integration
error.  The design therefore establishes a stable observation and seal format
with OpenOrb first, then makes the same sealed observations consumable by an
OrbFit validator.

## Version and native-build boundary

The runtime is `find_planet_openorb_v1/`, with its own Python project,
lockfile, source manifest, tests, configuration template, and documentation.
It never imports the stopped `find_planet_v1` package or any trail-processing
project.  Required controlled-extraction and Barghini-inversion code is copied
into the new runtime, reviewed locally, and covered by its own tests.

OpenOrb is pinned to release `v1.3.0`, commit
`945178476f016dae8f3981b54a937f61de81360f`.  A setup command downloads the
official source archive, verifies a recorded archive SHA-256, builds the native
`oorb` executable with the available GNU Fortran toolchain, runs the relevant
upstream tests, and installs only into a repository-local ignored vendor
directory.  The wrapper never searches `$PATH` for another `oorb`.

The GPL OpenOrb source/binary remains a clearly separated third-party
component.  Project-authored wrapper code retains the repository's BSD terms;
the build receipt records OpenOrb's GPL-3.0 license, official source URL,
release, commit, compiler, flags, upstream test result, and installed binary
hash.  No OpenOrb source is copied into an existing solver version.

## Pinned OpenOrb data

Setup also creates a repository-local data snapshot and receipt containing:

- OpenOrb `OBSCODE.dat` with observatory `696`, Whipple Observatory, Mt.
  Hopkins;
- `TAI-UTC.dat` and `ET-UT.dat`;
- a locally built DE441 OpenOrb ephemeris file supported by v1.3.0; and
- SHA-256, source URL, acquisition time, and format/version for each item.

The MMTO coordinates in the project are compared numerically with code 696's
longitude and parallax constants before use.  A difference large enough to
matter at the declared angular uncertainty stops the run; the wrapper does not
silently substitute the geocentre or a nearby observatory.  Normal execution
is offline and refuses missing or changed data.

The terrestrial positions derived from the two site definitions must differ
by less than one kilometre, and the resulting parallax difference must remain
below 0.1 arcsec even at the declared minimum trial range of 0.02 au.  Failure
requires a new pinned custom observatory entry and a revised design; it cannot
be waived at runtime.

## Controlled extraction and anonymous boundary

The controlled selector retains the pinned audit hash
`e0f445e044382369aa4a468a53900b1192cd7859389b9c388dd00c8633be6924`.
It selects Mars-labelled B-channel rows only in an explicitly named answer-key
stage, requires the exact recorded solver `run_id`, verifies the matching
source SHA and successful saved camera receipt, and preserves every accepted or
rejected audit row with a reason.

The authoritative saved Barghini model converts the unchanged measured pixel
centroid to a vacuum ICRS unit direction.  It reproduces saved detector parity,
radial mapping, and integrated derefraction exactly once.  The anonymous table
contains only a neutral technical designation mapped to `Object A`, UTC
exposure midpoint, ICRS RA/Dec, isotropic uncertainty, source/run hashes, and
partition.  It contains no planet name, predicted coordinate, known range,
known elements, or Horizons quantity.

## OpenOrb observation format

The adapter writes OpenOrb's 132-column `.mpc3` format because that parser
supports individual RA/Dec standard deviations.  The primary uncertainty is
`max(60 arcsec, saved stellar-only RMS)` for both tangent coordinates.  The
writer uses UTC, observatory code `696`, and sufficient RA/Dec precision to
remain far below the measurement uncertainty.

Every generated record is parsed back through the pinned OpenOrb executable
before fitting.  The round-trip audit must recover epoch, observatory code,
direction, designation, and both uncertainties within declared tolerances.
Raw `.mpc3`, an easier-to-inspect CSV, and a field-by-field format audit are all
sealed.  Half- and double-uncertainty sensitivity files are secondary products
and cannot replace the primary observations.

## Fit/withheld split

Every fifth chronological usable observing night is withheld as a whole before
OpenOrb is invoked.  The fit `.mpc3` file contains no withheld record.  A
separate withheld file is used only for ephemeris scoring after the anonymous
fit is fixed.  The exact night lists and deterministic rule are written before
fitting and hashed into the final seal.

## Professional orbit pipeline

1. Run OpenOrb statistical ranging on fit nights with an explicit, versioned
   configuration and a preregistered sample/trial budget.  The primary run uses
   automatic ranging (`sor.type=2`), 5,000 accepted sample orbits,
   `sor.ntrial=5,000,000`, `sor.niter=3`, and a 60-minute wall-time limit.
   Each half/double uncertainty sensitivity uses 2,000 accepted samples,
   2,000,000 trials, three iterations, and a 30-minute wall-time limit.
   Reaching a trial or time limit before the requested accepted sample count is
   `search_incomplete`, not a smaller successful search.  Preserve the full
   sampled-orbit PDF and completion diagnostics.
2. Use the ranging output to initialize OpenOrb `lsl`, producing the nominal
   orbit, covariance/hyperellipsoid, residuals, selected/outlier observations,
   and stop reason.  No custom SciPy fitting is permitted.
3. Generate topocentric OpenOrb ephemerides for the exact withheld epochs and
   observatory 696.  Score measured-minus-predicted tangent residuals with the
   declared uncertainties.
4. Fit the fixed-direction and constant-angular-velocity baselines only on the
   same fit nights, and score them on exactly the same withheld rows.  These
   simple baselines remain project-authored validation, not orbit fitting.
5. Run half- and double-uncertainty OpenOrb sensitivity jobs under separate
   recorded configurations.  They do not replace the primary result.

OpenOrb's raw outputs remain authoritative.  Python parses them into tables and
figures but never edits or cosmetically improves residuals.

Every OpenOrb call uses `--fixran` and a controlled working directory.  The
parsed sample arrays, nominal orbit, covariance, residuals, and ephemerides
must be byte-identical for identical inputs, executable, data, and
configuration.  Raw logs may contain elapsed-time text; those differences are
retained and sealed but excluded from the scientific reproducibility hash.

## Identity-neutral dynamics

The anonymous process does not know or assume what Object A is.  It does not
select a force model, prior, range, seed, family, or acceptance threshold from
the possibility that the measurements belong to any particular known body.
The primary ranging and LSL configurations use the same OpenOrb `2-body`
target dynamics for every unidentified Solar-System track at this declared
measurement scale.  All planetary perturbers are disabled uniformly; no one
planet is singled out for inclusion or exclusion.

DE441 is used only for the Sun/Earth observer geometry and time transformations
needed to interpret topocentric astrometry.  The unmodified OpenOrb executable
may contain other planetary states in that data file, but the audited two-body
target-dynamics path does not consult them when propagating Object A.  Tests
inspect the exact configuration, invocation, relevant upstream code path, and
logs and fail if any planetary perturber is enabled.

A later post-seal comparison may deliberately reveal and use known planetary
states, but it writes a separate directory keyed by the anonymous seal and can
never alter that seal.  The anonymous report does not rank candidate families
by similarity to a known object.

## Completion and scientific status

Operational success requires verified inputs, a completed declared ranging
budget, a completed LSL result or explicit OpenOrb non-convergence result,
complete raw logs, all tables/figures, and a valid seal.  SIGINT or another
interruption writes an interruption receipt and never a success seal.

Scientific status is:

- `predictive`: OpenOrb supplies a supported orbit/uncertainty result and its
  held-out weighted score improves over both baselines;
- `not_predictive`: a supported OpenOrb result exists but fails the matched
  held-out gate;
- `multimodal`: ranging retains materially distinct supported families whose
  held-out predictions are not distinguishable;
- `unresolved`: OpenOrb cannot establish a supported orbit or uncertainty;
- `search_incomplete`: the preregistered ranging/trial budget did not finish.

Only `predictive` is positive evidence that the anonymous track supports an
orbit.  None of these statuses identifies Mars.

A covariance is supported only when OpenOrb reports successful LSL
convergence, the full six-parameter covariance is present and finite, all
eigenvalues are positive, its spectral condition number is at most `1e12`, and
the propagated withheld uncertainty ellipses are finite.  Otherwise covariance
is explicitly unresolved.

Ranging samples are clustered at a common epoch.  A secondary family is
material only when it carries at least five percent of accepted samples, its
99-percent state region does not overlap the primary family's 99-percent state
region, and its held-out weighted chi-square is within 25 of the primary.  Such
a result is `multimodal` rather than choosing the family most similar to a
known planet.

The decisive predictive gate is held-out weighted chi-square.  The orbit must
beat each baseline by at least 25 chi-square units, and its held-out median
angular residual must not exceed the preregistered 95th-percentile recovery
limit derived from synthetic injections.  That synthetic limit is generated
and sealed before the real audit/database paths are made available to the
production runner.

## Outputs

Each successful operational run creates a fresh
`results/find-planet-openorb-v1/<UTC-run-id>/` directory containing at least:

- `answer_key_selection.csv` and its input/hash audit;
- `object_a_all.csv`, `object_a_fit.mpc3`, `object_a_withheld.mpc3`, and
  `mpc3_roundtrip_audit.csv`;
- exact OpenOrb configurations and command transcripts;
- raw ranging, LSL, residual, covariance, and ephemeris files;
- parsed `candidate_orbits.csv`, `orbital_elements.csv`,
  `withheld_predictions.csv`, `baseline_scores.csv`, and `fit_summary.json`;
- `orbit_sky_track.png`, `orbit_residuals.png`,
  `heliocentric_orbit.png`, and exact backing CSVs;
- `openorb-build-receipt.json`, `openorb-data-receipt.json`, source manifest,
  dependency lock hash, executable hash, and `seal.json`.

Measured points are never shifted.  Residual magnification is absent or
explicitly labelled and never changes the numerical residuals.

## Testing and acceptance

- Unit tests cover audit selection, exact receipt loading, real saved-camera
  inversion, UTC/RA/Dec formatting, `.mpc3` column layout, uncertainty units,
  whole-night splitting, output parsing, scoring, and sealing.
- Integration tests run the pinned native OpenOrb executable on upstream sample
  data and on synthetic topocentric arcs generated without known-object input.
- A leakage test rejects planet names/known states in the anonymous input,
  rejects enabled perturbers, and makes comparison resources inaccessible to
  the fit process.
- A holdout test proves no withheld record enters ranging or LSL and all models
  score identical withheld identifiers and weights.
- A preservation audit hashes every protected launcher, frozen runtime
  manifest, database, pinned audit, and raw manifest before and after the first
  real run.
- Required repository regressions remain
  `uv run --frozen python -m unittest discover -v` and
  `./demo.sh --output results/check-unique-name` from the intact main checkout.
- All generated runs use fresh directories and never overwrite the stopped
  prototype's evidence or any historical product.

## Future OrbFit validation boundary

The sealed anonymous CSV is the engine-neutral evidence format.  A future
`go_find_planet_orbfit_v1.sh` may translate that same sealed table into OrbFit
input, run `fitobs`, and write a separate result keyed by the observation seal.
It may compare OpenOrb and OrbFit states, covariances, residuals, and withheld
predictions, but it cannot silently substitute one engine's answer for the
other or alter either sealed directory.
