# V23 Recent Planet Visibility Design

## Intent

Each v23 invocation must discover and process unseen MMTO images before using
its capacity on already-downloaded leftovers. Its main planet time plot must
also show that recent planet measurements exist when the preserved nightly
extinction fit is unavailable.

## Goals and constraints

- Keep the one-night-at-a-time remote request rule and the requested image cap.
- Scan the current night, missed recent nights, and the persistent remote cursor
  before filling remaining capacity from the local unfinished backlog.
- Within a listed night, select unseen remote files before verified local files.
- Change v23 only; do not alter frozen v21 acquisition behavior.
- Preserve the 30-reference-star and 10-image extinction gates.
- Keep filled, connected points as extinction- and distance-corrected data.
- Plot usable measurements lacking an accepted nightly extinction fit as open,
  unconnected symbols at their distance-corrected but unextinguished magnitude.
- Label the open symbols explicitly and export them to a separate CSV so they
  cannot be mistaken for extinction-corrected measurements.
- Keep blind fitting separate from metadata-conditioned downstream association.

## Approaches considered

1. Wait until every recent night passes the extinction gate. This preserves the
   existing plot but can hide successfully processed images indefinitely when
   their stellar fields are unsuitable for the nightly fit.
2. Lower the extinction thresholds. This was rejected because it would weaken a
   scientific regression gate merely to fill the plot.
3. Preserve the thresholds and add explicitly uncorrected open symbols. This is
   the selected approach because it exposes the acquired measurements without
   representing them as calibrated.

For acquisition, a reserved remote quota was considered, but remote-first
selection is simpler and directly matches the requested newest-data behavior.

## Outputs

The existing `planet_extinction_corrected_distance_magnitude_vs_time.pdf` keeps
its stable path. A new `planet_distance_only_uncalibrated_measurements.csv`
records every open point and its missing-calibration status. The run summary
separately reports corrected and uncorrected plotted counts.

