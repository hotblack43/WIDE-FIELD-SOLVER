# Suppress same-sidereal map paths from v23 terminal output

## Intent

Prevent the large `same-sidereal-transmission` map set from pushing useful
terminal output out of view at the end of `go_mmto_photometry_v23.sh` runs.

## Design

- Keep generating and saving every same-sidereal transmission map.
- Keep every map path in the stage's saved manifest.
- In v23 only, omit individual files below `same-sidereal-transmission/` from
  the final `FIGURES` path listing.
- Print one summary line with the omitted map count and directory instead.
- Continue listing all other PDF and PNG products individually.

## Alternatives considered

- Delete the maps: rejected because the scientific diagnostics would be lost.
- Suppress every figure path: rejected because the other final products remain
  useful inspection targets.
- Suppress only the same-sidereal maps: selected because it removes the large,
  repetitive output while preserving both the diagnostics and useful paths.

## Verification

Add a v23 regression test proving same-sidereal map paths are absent from
terminal and log output, their count is summarized once, and other figures are
still listed.
