# Find Planet v1 design

## Intent

Build an independent orbit-determination experiment around the dated MMTO
point-source measurements.  The experiment first asks whether the existing
44-day, arcminute-precision track contains enough information to recover a
Mars-like heliocentric orbit when its identity is hidden.  It then attempts the
harder experiment: form moving-object tracks from unidentified detections
without consulting any planet ephemeris, fit their orbits, freeze the results,
and only afterward compare them with known Solar-System bodies.

This is a new launcher family, not v24 of the wide-field plate solver.  The
root launchers are:

- `go_find_planet_controlled_v1.sh`: create and fit the explicitly
  answer-key-selected anonymous `Object A` observations.
- `go_find_planet_blind_v1.sh`: form anonymous tracks and fit viable orbits
  without known-planet identities or ephemerides.
- `go_find_planet_compare_v1.sh`: reveal the answer only after a fit is sealed,
  then compare fitted elements and predictions with authoritative ephemerides.
- `go_find_planet_all_v1.sh`: run the three stages in order, stopping rather
  than comparing when a preceding stage has not produced a sealed result.

`X` in Peter's requested `go_find_planet_X_v1.sh` convention is therefore the
stage name.  Future materially different experiments get `v2`, not changes to
the meaning of a v1 launcher.

## Goals

1. Recover a six-component heliocentric state and osculating elements from
   dated, topocentric lines of sight, with uncertainties and correlations.
2. Demonstrate the method first on the 189 presently available Mars-associated
   measurements from 34 nights, while labelling their selection as non-blind.
3. Keep the strict-blind track search independent of the controlled result and
   of all planet names, planet reference tables, Horizons calls, saved planet
   predictions, and cached planet identities.
4. Test predictions on withheld nights and support later precovery searches in
   older MMTO frames using uncertainty regions rather than exact answer-key
   positions.
5. Produce inspectable figures, tables, provenance, sealed stage manifests and
   explicit unresolved/degenerate outcomes.

## Non-goals

- Do not alter the Barghini plate fit, source centroids, stored coordinates,
  MMTO acquisition, photometry, or any frozen solver runtime.
- Do not claim discovery merely because an answer-key-selected track fits.
- Do not require the fitted orbit to be Mars, force Mars-like element bounds,
  or tune thresholds after the comparison stage reveals the answer.
- Do not promise that the current 44-day arc uniquely determines all six
  elements.  A family of admissible orbits is an acceptable scientific result.
- Do not search external historical plate archives in v1.  V1 predicts dated
  uncertainty regions and tests them on locally held-out MMTO images.
- Do not use photometry as an astrometric measurement.  Brightness and colour
  may rank otherwise equivalent blind tracks, but may not move centroids.

## Scientific conventions

- Observation epochs come from verified FITS exposure midpoints and are
  converted from UTC to TDB.  The MMTO geodetic position is a permitted input
  for this dated-photo orbit experiment and is recorded explicitly.
- Measurements are topocentric inertial unit vectors recovered by applying the
  saved authoritative Barghini camera model to the measured centroids.  No
  predicted planet position enters this transformation.
- The observer state is MMTO's topocentric state plus Earth's heliocentric
  state at each epoch.  V1 obtains the Earth-only heliocentric position and
  velocity from ERFA `epv00` through the pinned runtime and obtains MMTO's
  geocentric position from its fixed geodetic coordinates and Earth rotation.
  The blind environment contains no general Solar-System kernel or
  known-planet position table.  Comparison data are kept outside the fitting
  process.
- The fitted parameter is a heliocentric Cartesian state at a recorded TDB
  reference epoch.  Report osculating `a`, `e`, `i`, longitude of ascending
  node, argument of perihelion and mean anomaly at that epoch, with the frame
  and equinox in every table and plot.
- Predictions include iterative one-way light time.  Topocentric parallax is
  not approximated as geocentric.  Atmospheric refraction is not applied a
  second time when the saved authoritative astrometry already embodies the
  accepted Barghini/refraction solution.
- V1 begins with Sun-only two-body propagation because the observational noise
  is at the arcminute scale and the arc is 44 days.  The limitation is stated;
  a later version may add repository-local N-body perturbations without
  changing v1 results.
- Angular residuals are two-dimensional tangent-plane residuals, never raw RA
  differences.  Per-exposure uncertainty starts from the saved stellar fit
  scale and is bounded away from zero.  Robust fitting may limit outliers, but
  every input row and its final weight/exclusion reason remains exported.

## Runtime and repository boundary

Create `find_planet_v1/` with its own `pyproject.toml`, committed `uv.lock`,
source manifest, package code, tests and any ephemeris data used at runtime.
The four root launchers execute only that environment.  They may read the
canonical `results/stars.sqlite`, `raw_allsky_samples/manifest.sqlite`, native
MMTO files and explicitly supplied sidecar CSVs.  They do not import Python
modules from `v23/` or another frozen directory.

Outputs go under a fresh
`results/find-planet-v1/<UTC-run-id>/` directory.  Existing products are never
overwritten.  Every stage writes a status JSON even when the scientific result
is unresolved, plus SHA-256 provenance for all inputs and code/data manifests.

## Stage 1: controlled anonymous fit

The controlled launcher takes an explicit metadata-association audit CSV and
the canonical run database.  The v1 reference input is
`results/photometry-runs/v23-20261027T050447Z/planet-empirical-extinction/B/`
`planet_only_airmass_correction_audit.csv`, SHA-256
`e0f445e044382369aa4a468a53900b1192cd7859389b9c388dd00c8633be6924`.
An override is allowed but is a different recorded experiment.  The extractor
selects the rows labelled Mars only in a clearly named `answer_key_selection`
step and uses the exact `run_id` recorded by each row; it never chooses a
different receipt merely because it is newer.  It verifies one astrometric
observation per source image and writes a sealed anonymous observation table
containing `object_id=Object A`, epoch, measured direction, uncertainty and
source/run identifiers.  It excludes predicted coordinates, predicted
distances, planet names, known elements and Horizons quantities from the
fitter's input.

The sealed observation table is split by whole observing night into fit and
withheld sets using a deterministic recorded rule.  The default is every fifth
chronological usable night withheld; the observation extractor records the
rule and both lists before fitting.

The default directional covariance is isotropic in the local tangent plane
with `sigma=max(1 arcmin, saved stellar-only fit RMS)`.  This deliberately uses
the plate solution's empirical scale rather than treating the centroid as
exact.  The report includes fits at half and twice that sigma as sensitivity
checks; these do not replace the declared primary weighting.

Initial orbit determination uses systematic ranging rather than relying on a
single three-observation Gauss solution.  A deterministic grid of admissible
topocentric range and range-rate values at the central epoch supplies multiple
initial heliocentric states.  Reject solar collision, Earth collision and
unbound solutions unless a separately labelled hyperbolic search is requested
in a future version.  Refine surviving states with bounded robust nonlinear
least squares against all fit-night directions.  Retain distinct local minima
when the data do not select one orbit.

Uncertainty is assessed from the local Jacobian and a deterministic night-level
bootstrap.  When the geometry is too weak for covariance or bootstrap
intervals, report the affected elements as unresolved instead of emitting
misleading precision.

The controlled result must beat two declared held-out baselines before it is
called predictive: a fixed sky direction and a constant-angular-velocity
tangent-plane track.  Completion of the optimizer alone is not success.
Both baselines are fitted only on fit nights.  The fixed baseline is the
weighted mean unit direction.  The moving baseline is a weighted linear fit to
two tangent-plane coordinates about the median fit epoch.  All three models
use the same withheld nights, uncertainties, angular residual definition and
report median, RMS, 90th-percentile and weighted chi-square scores.

## Stage 2: strict-blind track formation and orbit fitting

The blind launcher reads measured detections and saved camera solutions, not
planet candidate products.  At launch it snapshots every successful MMTO
receipt with solver version 0.21.0 or 0.23.0 that has a verified FITS midpoint
in `raw_allsky_samples/manifest.sqlite`; where both versions solved the same
source SHA-256, v23 is authoritative, otherwise v21 is used.  The snapshot
records the exact run IDs, database schema/version, query and manifest rows.
For the initial repository state this universe contains at most 583 successful
v21 and 201 successful v23 receipts before duplicate-source preference is
applied.  New database rows never enter an already started run.

The blind search retains catalogue-associated, unmatched, compact, broad and
saturated detections with their flags.  It does not remove a detection merely
because the plate solver associated it with a catalogue star: a planet may be
blended with or mistaken for a star.  Stationary multi-night tracks are instead
identified and rejected by recorded identity-free motion tests.  Every
retained centroid is converted to an inertial direction and every row remains
in the audit.

Before track formation, every fifth chronological usable night is assigned to
the blind held-out set by the same deterministic rule as the controlled stage.
Held-out detections cannot participate in linking, orbit fitting, candidate
selection or threshold setting.  Only after candidate states and ranks are
sealed are their predicted uncertainty regions searched against held-out
detections for evaluation.

Track formation proceeds without using the controlled Object A state:

1. Group detections into observing-night tracklets and collapse duplicate
   exposures only through recorded positional/time consistency rules.
2. Form cross-night pairs under broad, declared angular-speed bounds.
3. Extend pairs into three-night candidates under broad angular-acceleration
   bounds.
4. Apply the same identity-free systematic-ranging orbit fit and retain every
   dynamically admissible solution passing predeclared residual and coverage
   gates.
5. Score candidates using held-out angular prediction, night count, time span,
   residuals and ambiguity.  Brightness may break a numerical tie but never
   supplies a planet identity.

Combinatorial controls are operational limits, not scientific exclusions:
their counts and rejected-candidate reasons are exported.  A configurable
resource cap stops with `search_incomplete` and a resumable manifest rather than
silently declaring no object.

The v1 admissible region is preregistered as bound heliocentric orbits with
perihelion at least 0.05 au and aphelion at most 50 au.  Systematic ranging uses
topocentric distances from 0.02 to 100 au on a logarithmic grid; range rates
are retained only when the resulting state lies in that admissible region.
Pair formation permits angular speeds through 5 degrees/day and the
three-night extension permits angular acceleration through 0.5
degrees/day-squared.  A candidate needs at least six distinct fit nights over
at least 20 days.  These intentionally broad production bounds, all grid sizes
and the resource cap are written before the first real blind detection is read.

Scientific acceptance thresholds are frozen by the synthetic injection suite,
not adjusted from real Mars results.  At minimum, an accepted candidate must
complete the declared search, improve held-out weighted chi-square over the
constant-angular-velocity baseline, have held-out median residual no worse than
the synthetic suite's preregistered 95th-percentile recovery limit, and retain
no statistically indistinguishable orbit family with a materially different
state.  The generated `preregistered_gates.json` is hashed into the blind-stage
seal.  Failure to establish useful gates from synthetic injections blocks a
real blind discovery claim.

Before any comparison, the blind stage writes a sealed result manifest holding
the observation hashes, candidate states, elements, uncertainties, fit code
manifest, thresholds and completion status.  The controlled output directory,
answer-key audit fields and known-planet reference material are unavailable to
the blind-stage process by construction and verified by tests.

## Stage 3: reveal and comparison

The comparison launcher requires a sealed controlled or blind result.  It is
the only stage allowed to read known-planet reference data or query an
authoritative service.  It never edits the sealed directory; it writes a
separate comparison subdirectory keyed by the seal hash.

The v1 known-object comparison population is Mercury through Neptune plus
Ceres and Vesta, matching the project's current bright-planet/minor-planet
reference population.  For the fit's exact reference epoch and frame it
compares:

- the fitted state and osculating elements with the major planets;
- element differences with fitted covariance and bootstrap intervals;
- predicted topocentric directions on withheld nights;
- the identity and rank of the nearest known orbit; and
- alternative known objects that remain compatible within uncertainty.

The report may say “consistent with Mars” only when the comparison is supported
by declared element/state and withheld-prediction criteria.  The controlled
report says “controlled rediscovery”; only a completed strict-blind search may
use “blind rediscovery,” and neither is a claim of priority discovery.
Compatibility is computed in six-dimensional Cartesian state space at the
common epoch using the fitted covariance where it is full rank and the
night-bootstrap state cloud otherwise.  A known body is compatible when its
state lies within the preregistered 99% region and its withheld directions pass
the same predictive gate as the anonymous fit.  It is uniquely identified only
when it is the sole compatible reference object and the next-best reference has
at least 25 worse chi-square units on the same angular observations.  Otherwise
the report lists all compatible bodies and retains an ambiguous identity.

## Outputs

Each fit stage produces:

- `orbit_sky_track.png`: measured fit/withheld directions, predictions and
  uncertainty regions versus time;
- `orbit_residuals.png`: tangent-plane residual components and angular norm,
  with actual residuals unshifted and any magnification explicitly labelled;
- `heliocentric_orbit.png`: the fitted orbit family, Sun and Earth's orbit in a
  declared reference plane;
- `observations.csv`, `observation_audit.csv`, `candidate_orbits.csv`,
  `orbital_elements.csv`, `covariance.csv`, `bootstrap_elements.csv` and
  `fit_summary.json`;
- a sealed manifest for completed fit stages.

The comparison stage additionally produces `element_comparison.png`,
`withheld_prediction_comparison.png`, `known_object_comparison.csv` and
`comparison_summary.json`.  Plots show uncertainty and distinguish direct
measurements, fitted values and post-fit answer-key/reference values.

## Testing and acceptance

- Unit tests cover coordinate/time conversions, Barghini centroid inversion,
  light-time iteration, two-body propagation, state-to-elements conversion,
  tangent-plane residuals, systematic-ranging determinism and seal checking.
- Synthetic end-to-end tests generate topocentric observations from known
  bound orbits at the real MMTO cadence, add declared noise/outliers, and check
  state recovery and honest degeneracy reporting.
- A leakage test makes known-planet data and controlled-stage outputs fail if
  accessed by the blind process.  It also verifies that the blind runtime uses
  ERFA's Earth-only `epv00` path and contains no general planet kernel/reference
  table.
- A controlled real-data run is accepted operationally when it preserves all
  input/audit rows and produces a sealed, reproducible outcome.  It is accepted
  scientifically only if it improves held-out angular predictions over both
  baselines and its uncertainty statement is numerically supported.
- A blind run is scientifically successful only under predeclared completeness,
  residual, coverage and held-out-prediction gates.  “No unique orbit” and
  `search_incomplete` are valid outcomes, not failures to be hidden by changed
  thresholds.
- Before any commit, run the new family's complete tests plus the repository's
  required `uv run --frozen python -m unittest discover -v` and
  `./demo.sh --output results/check-unique-name`.  Frozen runtime manifests
  must remain unchanged.

## Approaches considered

1. **Controlled fit only.**  Fastest and useful for establishing information
   content, but it cannot answer whether Mars can be found without knowing which
   detections are Mars.
2. **Strict blind search immediately.**  Scientifically strongest, but it mixes
   failures of orbit fitting with failures of combinatorial source linking and
   makes diagnosis unnecessarily difficult.
3. **Staged controlled then strict blind, with independent comparison.**
   Selected.  It validates the orbit machinery on real measurements first while
   preserving a separately executable, leakage-tested blind experiment.

## Builder decisions left open

The builder may choose internal module names, plotting colours, chunk sizes,
SQLite query structure, numeric integrator tolerances justified below the
measurement-error scale, and the exact deterministic sampling implementation.
The builder may reduce a default search grid for tests, but production limits,
completion status and all search bounds must remain recorded and must not be
tuned after comparison reveals the answer.
