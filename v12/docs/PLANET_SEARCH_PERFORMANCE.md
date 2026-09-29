# v0.6.0 blind planet-search performance

Version 0.6.0 accelerates the blind planetary epoch stage without using the
image date, site, filename, fitted stellar epoch or saved planetary solutions.
The daily proposal table spans Julian years 1850--2036 TDB. The causal run-time
ceiling still excludes future dates; 2036 is deliberate headroom beyond the
2026 release, not a prediction that future images are available.

## What changed

- A validated 12 MB daily reference table is shipped with v6, so ordinary runs
  do not build a 300-year ephemeris cache.
- Normalized cubic interpolation supplies cheap proposal checks only.
- Independent visit brackets for one planet are refined in vector batches.
- Up to four planet groups run in deterministic worker processes. Set
  `WFS_PLANET_WORKERS=1` for the serial reference path.
- `planet_search_performance.json` records cache source, stage timings, worker
  count, exact/interpolated call counts and candidate counts. The identical
  object is embedded in `planet_epoch.json`.

Exact Astropy builtin directions remain authoritative. Every final date,
detector gate, altitude, saved predicted position and residual is evaluated on
the exact path. Interpolation cannot accept a candidate, and tests deliberately
put interpolated and exact positions on opposite sides of a gate.

## Controlled Espenak benchmark

Measured 16 September 2026 on Linux 7.0.0-31, x86-64, 16 logical CPUs, using
`FishEye18-1021w_Espenak.jpg`. Each repetition copied the same completed
astrometric analysis, then reran only the planetary stage. Both versions used a
warm validated cache; v6 used four workers. Raw evidence is in
[`PLANET_SEARCH_BENCHMARK.json`](PLANET_SEARCH_BENCHMARK.json).

| Runtime | Repetitions (s) | Median (s) |
|---|---:|---:|
| v5 warm cache | 68.60, 76.77, 76.80 | 76.77 |
| v6 bundled table, 4 workers | 24.84, 25.53, 24.16 | 24.84 |

The median speedup is **3.09×**. A separate v6 one-worker run took 32.42 s wall
(30.34 s measured inside the stage), showing that batching supplies most of the
gain and process parallelism supplies a further improvement.

Both versions found 843 positional visits, ran 138 joint trials, retained the
same 138 candidate identities and reported `planet_epoch_not_identifiable`.
The largest candidate-epoch difference was 0.139 seconds and the largest RMS
difference was `2.56e-11` pixel. These are bounded exact-minimizer termination
differences, not changes to the camera, detections, gates or scientific status.

Reproduce the comparison from the repository root after syncing both locked
environments and making the v5 warm cache available:

```sh
v6/.venv/bin/python v6/scripts/benchmark_planet_search.py \
  --v5-analysis /path/to/fitted-analysis \
  --v6-analysis /path/to/fitted-analysis \
  --image /path/to/image.jpg --repetitions 3 --workers 4 \
  --json v6/docs/PLANET_SEARCH_BENCHMARK.json
```

Timings are machine- and field-dependent. Fields with few planet/source visits
will gain less, while the exact scientific limitations of the builtin
geocentric ephemeris, image-derived zenith and uncalibrated positional ranking
remain unchanged.
