# V23 MMTO Weather Gate Design

## Intent

Keep the unattended MMTO backlog focused on images likely to support useful
photometry without requiring Peter to inspect a review queue. Weather is an
acquisition filter only; it must never enter or seed the blind astrometric fit.

## Decision

For each candidate exposure, query the public MMTO summit-weather history and
match the nearest outside-relative-humidity sample in UTC.

- A fresh humidity sample below 80% allows the candidate to proceed.
- A fresh humidity sample at or above 80% rejects the candidate automatically.
- Missing, malformed, failed, or stale weather telemetry is `unknown` and lets
  the candidate proceed exactly as it does today.
- A weather rejection does not consume the per-invocation image cap; the
  planner continues backward until it fills the requested cap or exhausts the
  date range.
- No manual-review state is created. Decisions are recorded only for audit.

Fresh means the nearest sample is no more than 120 seconds from the candidate's
UTC observation time. Equality at both boundaries is deliberate: 80.0% is
rejected and a sample exactly 120 seconds away remains usable.

## Source and timing

Use the unauthenticated historical endpoint
`https://api.mmto.arizona.edu/APIv1/history`, table `measurements`, and the
outside sensors `vaisala2_relative_humidity` and
`vaisala4_relative_humidity`. When both sensors have fresh samples, use the
larger humidity value. Candidate timestamps and weather samples are compared
as timezone-aware UTC values. For downloaded FITS validation, `DATE-BEG` is the
UTC exposure time; `DATE-OBS` is local observatory time and must not be treated
as UTC.

The NOAA/Synoptic Hopkins station and precipitation data are useful future
corroboration, but they require credentials and are at a lower elevation. They
are not part of this first gate. Their absence must not block image analysis.

## Interfaces and audit

Add a focused weather module rather than placing HTTP and matching logic inside
the acquisition planner. It returns one of `accept`, `skip`, or `unknown` for a
candidate, including the selected humidity, sample timestamp, age, sensor, and
reason. The pipeline summary reports aggregate counts, and the run directory
contains a JSON-lines audit of every weather decision considered.

Expose `--max-humidity-percent` with default `80.0` and
`--weather-max-age-seconds` with default `120`. A non-positive age or humidity
outside 0–100 is rejected as invalid configuration. Network/API/JSON failures
are logged and treated as unknown, never as fatal pipeline errors.

## Non-goals

- No manual inspection queue.
- No use of FITS humidity as a substitute for missing external telemetry.
- No interpolation or carrying the last sample across an outage.
- No weather input to source detection, association, fitting, or saved
  astrometry.
- No modification of frozen v22 or earlier runtimes.

## Approaches considered

1. **Only process RH below 80% (chosen).** Maximizes purity and is fully
   unattended, at the cost of completeness when real humidity is high.
2. **Use an 80–90% caution band.** Preserves more images but creates no useful
   action unless another automated image-quality classifier is designed.
3. **Reject only at the MMTO 90% closure threshold.** Has an official physical
   basis but is less conservative than desired for photometric sample quality.
