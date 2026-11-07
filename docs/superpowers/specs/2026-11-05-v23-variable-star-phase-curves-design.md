# V23 Variable-Star Phase Curves Design

## Intent

Replace v23's chronological variable-star PDF with a phase-folded PDF so the
same nightly extinction-corrected measurements are inspected against stellar
phase rather than UTC.

## Goals

- Stop producing `variable_star_time_series.pdf` in new v23 runs.
- Produce `variable_star_phase_curves.pdf` with one panel per selected VSX
  object and phase on the horizontal axis.
- Define phase zero independently for each star as its earliest plotted UTC and
  calculate `phase = ((UTC - reference UTC) / VSX period) mod 1`.
- Preserve the measured magnitudes, R/G/B separation, inverted magnitude axis,
  fixed-period sine fits, fitted brightest-phase labels, selection rules, CSV
  audits, and immutable-output behavior.
- Update v23 documentation and regression tests to describe and verify the new
  product name and phase convention.

## Non-goals and anti-goals

- Do not change source selection, nightly flux averaging, extinction
  correction, VSX periods, or fit weighting.
- Do not infer or invent a catalogue epoch that is absent from the frozen VSX
  cross-match.
- Do not align each channel independently at maximum light, because that would
  hide possible R/G/B phase offsets.
- Do not modify frozen earlier versions.

## Constraints

- Changes are limited to active v23 code, its launcher-facing reporting,
  tests, and v23/current-status documentation.
- Existing user data and historical run directories remain untouched.
- Numerical magnitude and sine-fit CSV values must remain unchanged.

## Approaches

1. **Earliest-observation reference (selected):** fold every channel for a star
   with the star's earliest plotted UTC as phase zero. This is deterministic,
   auditable from existing inputs, and retains inter-channel phase offsets.
2. **Per-channel fitted maximum:** put each fitted channel maximum at phase
   zero. Rejected because it removes the fitted R/G/B phase differences and is
   undefined for sparse or rank-deficient channels.
3. **Catalogue epoch:** use a published epoch of maximum or minimum. Rejected
   for this change because the frozen v23 cross-match contains periods but no
   such epoch; adding one would require a new catalogued-data acquisition and
   provenance change.

## Implementation boundary

The plotting helper will calculate folded phases from the same per-star
reference UTC already used by the sine fitting. Scatter points and fitted
curves will use phase coordinates in `[0, 1)`. Product metadata and terminal
output will identify phase folding and the reference convention. Regression
tests will prove the phase transform, axis labeling, renamed PDF, absence of
the old PDF, and preservation of multipage/empty-selection behavior.
