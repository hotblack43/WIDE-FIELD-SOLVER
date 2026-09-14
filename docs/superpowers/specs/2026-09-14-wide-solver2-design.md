# Wide-field Solver 2: Limiting-Magnitude Exploration

## Goal

Create an isolated version 2 of the point-star wide-field solver that compares
Tycho-2 catalogue limits of 7.5, 8.0, and 8.5 while retaining the existing
Hipparcos bright-star supplement at V <= 2.0.

## Preservation constraints

- Do not modify or replace any existing solver, catalogue builder, frozen
  catalogue, historical example, or regression threshold.
- Every new executable Python source and test file is labelled with a trailing
  `2` in its basename.
- Keep `data/stars_tycho2_mag75.csv` as the frozen v1 catalogue.
- Write the deeper candidate catalogue to
  `data/stars_tycho2_mag85_v2.csv`.
- Continue to make every detected source available for association and fitting;
  v2 does not introduce withheld stars.

## Architecture

`point_star_barghini2.py` is an isolated v2 solver derived from the working
v1 flow. It accepts an explicit limiting magnitude and filters the supplied
catalogue at every progressive and final association stage. Its progressive
schedule preserves the successful bright stages through magnitude 7.5 and adds
modest 8.0 and 8.5 stages only when requested.

`analyse_image2.py` is the v2 experiment driver. It runs three independent
candidate solves at 7.5, 8.0, and 8.5 into separate subdirectories and writes
`limiting_magnitude_comparison2.json`. It reports candidate metrics and
cross-limit association stability but deliberately does not select a winner.

`scripts/rebuild_catalogue2.py` builds the 8.5 Tycho-2 superset and adds the
same Hipparcos V <= 2.0 supplement and positional de-duplication used by v1.

## Comparison outputs

For every candidate, record convergence, association count, RMS, median and
90th-percentile residual, unmatched detections, catalogue rows available at
the limit, stage history, and camera parameters. Between adjacent limits,
record retained, gained, and lost catalogue identifiers and detector-to-star
pair stability. These are fitted residuals, not independent validation.

## Error handling

Reject limits outside the supported set, catalogues shallower than the requested
limit, duplicate/unsorted limits, missing required catalogue columns, and any
candidate solve that fails the existing convergence and monotonicity checks.
A failed candidate remains represented in the comparison instead of silently
becoming the selected solution.

## Verification

Tests cover the depth-dependent stage schedule, explicit final catalogue
filtering, candidate limit validation, and hand-checked association-stability
summaries. The complete v1 unit suite must remain green. A real v2 run on the
preserved Milky Way image produces separate 7.5/8.0/8.5 evidence without
changing the historical reference directory.
