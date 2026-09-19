# V11 Joint Stellar and Planetary Epoch Design

**Date:** 2026-09-19

**Status:** Implementation authorized; see execution ledger for conservative deviations

## Purpose

Create a new, self-contained v0.11.0 runtime that preserves the successful v10
wide-field solution while restoring planets to the scientific epoch inference.
V11 must determine whether two or more measured moving bodies, together with
the stellar proper-motion field, support a common observation epoch. A planet
overlay at a supplied timestamp is validation evidence, not an epoch solution.

The investigator's intended analogy is explicit: catalogue stars and Solar
System bodies both have time-dependent predicted celestial coordinates. Stars
usually provide many weak proper-motion constraints; planets can provide a few
much faster constraints. They must be evaluated against the same measured
centroids, epoch, Barghini camera, and saved coordinates. Planet identities are
discrete hypotheses rather than trusted labels.

V11 succeeds scientifically only when a bounded, unique joint solution is
supported by at least two distinct planets assigned to two distinct measured
sources. Zero or one plausible planet may be reported as evidence but cannot
produce a claimed joint epoch.

## Version Boundary

V11 does not modify v10. The investigator authorized proceeding without further
permission gates. The exact current v10 working snapshot is recorded without
committing another window's changes. Root `go10.sh`, `go_v0.10.0.sh`, and the
complete `v10/` package retain their existing bytes and v0.10.0 behavior.
`docs/v10-runtime.json` retains this working snapshot under
`working_tree_parent_snapshot`; its top-level hashes freeze the committed v10
runtime so a clean checkout does not depend on another window's uncommitted edits.

V11 starts from that recorded v10 runtime, excluding generated environments,
caches, reports, and run products. It owns:

- `v11/`, including code, catalogues, ephemeris data, documentation, tests,
  source manifest, dependency declaration, and lockfile;
- root launchers `go11.sh` and `go_v0.11.0.sh`; and
- root preservation tests and documentation for the new boundary.

V11 must run from a clean clone without `.worktrees` and without importing any
runtime code or data from another project. V10 and every earlier preserved
runtime remain byte-for-byte governed by their recorded manifests.

## Chosen Architecture

V11 uses a two-level inference instead of either a metadata-centred overlay or
an impractically expensive camera refit on every ephemeris day.

### 1. Initial stellar solution

The existing v10 blind detection, catalogue association, stellar epoch profile,
Barghini fit, refraction diagnostics, photometry, and physical-zenith work run
first. This supplies an initial camera, fixed measured centroids, catalogue
associations, and a stellar epoch profile. No timestamp, site, filename date,
saved planet identity, or previous solution enters these stages.

### 2. Global planet-hypothesis discovery

The existing accelerated 1850-to-causal-ceiling trajectory search remains the
global authority for possible dates and identities. It considers all detected
sources, including sources already associated with stars, subject to the
existing star-versus-planet competition rules. Large and saturated detections
remain eligible.

When usable observation-time metadata exists, v11 may first evaluate exact
planet positions and apparent brightnesses at that time to propose likely
source/body pairs. This is an acceleration and discovery step only:

- the metadata time does not bound the subsequent epoch search;
- the proposed identities are not locked;
- alternative planet identities and dates remain eligible; and
- failure to find two plausible metadata-time planets falls back to the full
  global candidate search rather than terminating the planetary analysis.

When metadata is absent or unusable, v11 begins directly with the full global
search. Both paths record whether metadata proposed any hypotheses and exactly
which later candidates, if any, descended from those proposals.

The global stage holds the initial stellar camera fixed only to find discrete
candidate constellations and broad date intervals cheaply. It does not publish
that fixed-camera result as the final epoch.

### 3. Qualification for joint refinement

A candidate can enter joint refinement only when it contains at least two
distinct Solar System bodies assigned one-to-one to at least two distinct
measured sources. Two labels on one source, duplicate detections of one body,
or a single body at multiple alias dates do not qualify.

Every qualifying candidate retains:

- its body/source assignments and alternatives;
- its global positional interval and competing dates;
- star-association conflicts and residual improvements;
- visibility and solar-consistency evidence;
- measured photometry, saturation state, and predicted brightness evidence;
  and
- whether metadata helped propose it.

Zero- and one-planet cases retain their evidence and candidate dates but return
`joint_epoch_not_attempted_insufficient_planets`. They do not alter the initial
stellar camera, adopted epoch, or saved coordinates.

### 4. Joint local epoch profile

For every qualifying global candidate, v11 constructs a local epoch profile
over the candidate's complete positional interval, enlarged enough to measure
both sides of the minimum. At each trial epoch it:

1. propagates every fixed stellar association from its catalogue reference
   epoch using the existing proper-motion implementation;
2. calculates exact ephemeris directions for the candidate planets;
3. refits one Barghini camera against the stellar and planetary angular
   residuals together;
4. preserves the one-to-one body/source assignments for that particular
   profile while separately profiling every viable alternative assignment;
5. records stellar-only, planet-only, and combined contributions to the
   objective; and
6. calculates numerical residuals and saved sky coordinates directly from
   that trial camera, without moving measured centroids or plot symbols.

The camera remains strongly anchored by the many stellar associations, while
the rapid planet motion supplies epoch curvature. Stellar and planetary
angular residuals use documented uncertainty scales and robust losses rather
than arbitrary replication or hand weights. The v11 implementation must expose
those scales in the saved result and test that changing the number of stars
does not silently erase or exaggerate a planet constraint.

After each candidate minimum, stellar associations are reassessed through the
existing bounded reassociation loop. Planet/source assignments are then
rechecked against competing star explanations and alternative planet
identities. A changed membership requires another joint profile; the saved
camera and coordinates must always correspond to the final recorded membership.

## Brightness Evidence

V11 promotes ephemeris brightness from absence-only screening to soft identity
evidence. Position remains the astrometric observable; brightness must never
shift a centroid, camera projection, or residual.

For each proposed planet/source association, v11 saves:

- predicted apparent V magnitude and its model provenance;
- measured native-channel aperture counts and exposure-normalized count rates;
- saturation flags and any valid one-sided lower bound;
- provisional airmass and extinction context when an image-derived zenith is
  available; and
- a brightness-consistency contribution with its uncertainty and reason.

The comparison profiles a nuisance photometric zero point. It uses differential
planet brightness, locally measured stellar depth, the existing extinction
estimate when available, and a conservative scatter floor covering V-versus-
camera passband mismatch, colour, clouds, vignetting, and model limitations.
Saturated measurements contribute only valid one-sided information. Missing,
unavailable, or scientifically inconclusive photometry is neutral.

Brightness can rank otherwise plausible identity assignments and can retain
the existing conservative missing-bright-planet penalty. It cannot create a
positional match, rescue a geometrically invalid candidate, or by itself turn
an ambiguous solution into an established epoch. The result records positional
and brightness rankings separately as well as their declared combined ranking.

## Selection and Status Rules

All global candidates remain auditable. V11 selects an established joint epoch
only when all of the following hold:

- at least two distinct planets and detections support the same candidate;
- the joint minimum is interior to the causal search range and its profiled
  confidence interval is bounded on both sides;
- no statistically competitive date/identity solution remains;
- measured and predicted planet positions satisfy physical visibility and
  valid-detector projection checks;
- solar evidence does not contradict the accepted nighttime field; and
- the final camera, memberships, and objective are mutually consistent.

The principal statuses are:

- `joint_epoch_fitted`: the requirements above are met; the joint epoch and
  camera become the saved scientific solution;
- `joint_epoch_ambiguous`: at least two planets support one or more candidates,
  but aliases, boundary behavior, visibility, or fit degeneracy prevent a
  unique result;
- `joint_epoch_not_attempted_insufficient_planets`: zero or one plausible
  planet; the stellar solution remains authoritative;
- `joint_epoch_inconsistent`: all multi-planet candidates are contradicted by
  geometry, solar evidence, or supported missing-bright-planet evidence; and
- `joint_epoch_failed`: a numerical or data-integrity failure prevented the
  required profiles; partial evidence remains saved and the stellar solution
  is retained.

An ambiguous, inconsistent, insufficient, or failed joint analysis never
silently replaces the initial stellar camera or coordinates.

## Saved Solution and Propagation

For `joint_epoch_fitted`, the final `result.json`, `solution.fits`, annotated
FITS, WCS approximation, star-coordinate table, and report use the jointly
fitted Barghini camera and epoch. Stellar catalogue coordinates are propagated
to that epoch. Planet rows retain measured centroids, exact predicted sky and
detector coordinates, angular residuals, brightness evidence, and identity
alternatives.

The initial stellar-only solution and profile remain separately inspectable so
the investigator can see what the planets changed. The result records camera-
parameter changes, stellar residual changes, planet residuals, and epoch shifts;
it never overwrites that audit with only the final values.

If no established joint solution exists, all standard saved coordinates and
WCS products continue to use the stellar-only camera. Candidate planet tables
remain diagnostics and are not encoded as confirmed identities.

## Metadata Boundary

Observation-time metadata is permitted to propose planet/source hypotheses in
the explicitly named `metadata_assisted_global` mode. It is not a prior or
bound on the global epoch and cannot enter stellar astrometry, physical-zenith
estimation, or refraction fitting.

After the joint result is fixed, v11 performs a separate metadata validation:

- joint fitted time minus metadata time;
- planet residuals at the fitted time versus at the metadata time; and
- agreement or disagreement among all available metadata timestamps.

The report must never label a metadata-time association as an epoch-fit planet.
It must state `metadata-assisted` when metadata proposed hypotheses and `blind`
when none was used. A deliberately incorrect timestamp must not constrain the
accepted epoch; it may at most change proposal order before the global fallback
and alternative search restore completeness.

## Reports and Plots

The primary sky overlay marks measured centroids associated by the final joint
fit and separately shows their predicted positions. It never moves a symbol to
improve agreement. Any residual-vector magnification is numerical, explicitly
labelled, and confined to a residual diagnostic.

Metadata-time associations, when requested for validation, use a distinct
marker and legend and never replace the fitted associations on the primary
overlay. The first report page states:

- stellar-only epoch status;
- joint epoch status and uncertainty;
- planet count, identities, and positional residuals;
- whether metadata assisted hypothesis discovery;
- brightness consistency and missing-planet evidence; and
- the separately revealed metadata-time difference.

The report must make zero/one-planet insufficiency, aliases, boundary-limited
fits, and unchanged stellar-only fallbacks unmistakable.

## Error Handling and Auditability

Every stage writes enough information to resume diagnosis without rerunning the
whole solve. Numerical failure of one assignment does not delete other global
candidates. Invalid ephemeris values, unsupported brightness formula domains,
unknown saturation, missing exposure, and unavailable physical zenith produce
explicit neutral or unresolved evidence rather than fabricated penalties.

The global proposal table, every refined identity assignment, joint profile,
objective decomposition, reassociation iteration, selection reason, and
metadata comparison remain machine-readable. Cached identifiers, previous run
products, display names, or saved solutions never seed a v11 run.

## Verification

Development is test-driven in v11. Required synthetic and regression evidence
includes:

- two moving planets plus stars recover a known epoch and save the joint camera;
- the same case without metadata recovers the same solution within numerical
  tolerance;
- correct metadata accelerates proposal discovery but does not change the
  fitted answer;
- deliberately wrong metadata does not bound, select, or bias the recovered
  epoch;
- zero and one planet never publish a joint epoch or alter stellar coordinates;
- two labels cannot reuse one detection and one planet cannot count twice;
- competing two-planet dates remain ambiguous;
- alternative planet identities are retained and the correct coherent
  constellation can defeat an initial metadata suggestion;
- predicted relative brightness downranks a photometrically implausible
  identity without changing astrometric residuals;
- missing or saturated planet photometry is neutral or one-sided as specified;
- missing-bright-planet evidence can contradict a candidate only with the
  established local-depth witnesses;
- joint reassociation saves the exact camera and memberships that were fitted;
- failed or ambiguous joint fits preserve the stellar-only solution;
- overlays use measured centroids and distinguish fitted from metadata-time
  predictions; and
- v10 launchers, package hashes, results, and reports remain unchanged.

An end-to-end v11 acceptance run uses the motivating MMTO FITS image
`2026_09_19__05_00_17.fits.bz2`. Its known timestamp is hidden from the final
global selection and revealed only for the saved comparison. Acceptance does
not require that this particular image yield an established epoch: it requires
honest status, complete candidate evidence, no metadata-bounded minimum, and no
metadata-time marker presented as a fitted planet. Any claimed epoch must pass
the two-planet, uniqueness, bounded-interval, visibility, and consistency rules.

Before every commit, run:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Before publishing v11, also run the complete v11 suite and demo, launcher and
manifest checks, the end-to-end MMTO acceptance case, and all preserved-version
checks required by the repository boundary. Numerical changes must be explained;
thresholds must not be relaxed to hide failures.

## Non-Goals

- V11 does not claim a joint epoch from a single planet.
- V11 does not use metadata as an epoch prior, search bound, or final identity
  authority.
- V11 does not calibrate camera photometry to a standard Johnson V system.
- V11 does not let brightness move centroids or replace positional evidence.
- V11 does not require a planet detection when the image depth, obstruction,
  saturation, or passband makes detectability unresolved.
- V11 does not extend the bundled ephemerides beyond their validated bodies or
  date range without separate provenance and tests.
- V11 does not modify v10 or any earlier preserved runtime.
