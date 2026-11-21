# V26 Observation-Sidecar Discovery Design

## Intent

The cumulative v26 differential-photometry replay must consume every compatible
MMTO FITS-header observation sidecar through v26 without requiring a handwritten
table list. Versioned write tables remain separate so each frozen runtime keeps
its provenance.

## Approaches

- Adding only `mmto_v25_observations` would repair today's failure but preserve
  the manual maintenance trap. Rejected.
- A single replacement observation table would simplify new writes but would
  rewrite the established append-only storage boundary and frozen history.
  Rejected.
- Discover tables named `mmto_v<integer>_observations`, accept only versions no
  newer than v26, validate the required replay columns, sort by numeric version,
  and retain the existing cross-table conflict check. Selected.

## Requirements

- Include compatible observation tables through v26, including v25.
- Ignore future-version tables so frozen v26 behavior cannot change when a newer
  runtime appends its own sidecar.
- Fail explicitly when a discovered in-range table lacks a required replay
  column.
- Preserve the existing error on conflicting midpoint or exposure metadata.
- Do not change measurements, selected run IDs, blind fitting, or any frozen
  runtime.
