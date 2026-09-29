# v0.6.0 blind planet-search performance

Version 0.6.0 accelerates the blind planetary epoch stage without using the
image date, site, filename, fitted stellar epoch or saved planetary solutions.
The daily proposal table spans Julian years 1850--2036 TDB. The causal run-time
ceiling still excludes future dates; 2036 is deliberate headroom beyond the
2026 release, not a prediction that future images are available.

## What changed

- A validated 12 MB daily reference table is shipped with v6, so ordinary runs
  do not build a 300-year ephemeris cache.
- Normalized Catmull--Rom interpolation supplies optimized proposal dates;
  one-sided cubic stencils cover the two reference-table edge segments.
- Independent visit brackets for one planet are refined in vector batches.
- Up to four planet groups run in deterministic worker processes. Set
  `WFS_PLANET_WORKERS=1` for the serial reference path.
- `planet_search_performance.json` records cache source, stage timings, worker
  count, exact/interpolated call counts and candidate counts. The identical
  object is embedded in `planet_epoch.json`.

Exact Astropy builtin directions remain authoritative. The interpolated date is
accepted as an option only after an exact evaluation confirms the five-arcsecond
interpolation guard. Every original visit bracket is still minimized in full on
the exact path, and every final detector gate, altitude, saved predicted
position and residual is exact. Tests deliberately put interpolated and exact
positions on opposite sides of a gate.

## Controlled Espenak benchmark

Measured 16 September 2026 on Linux 7.0.0-31, x86-64, 16 logical CPUs, using
`FishEye18-1021w_Espenak.jpg`. Each repetition copied the same completed
astrometric analysis, then reran only the planetary stage. Both versions used a
warm validated cache; v6 used four workers. Raw evidence is in
[`PLANET_SEARCH_BENCHMARK.json`](PLANET_SEARCH_BENCHMARK.json).

| Runtime | Repetitions (s) | Median (s) |
|---|---:|---:|
| v5 warm cache | 66.40, 66.87, 67.95 | 66.87 |
| v6 bundled table, 4 workers | 29.07, 30.19, 33.25 | 30.19 |

The median isolated-stage speedup is **2.21×**. The evidence records the v5
writable cache as present before every timed run and the v6 bundled-table digest
for every run.

One complete launcher run per version on the same image took 211.39 seconds for
`go5.sh` and 172.94 seconds for `go6.sh`: **1.22× end-to-end**, or 38.45 seconds
saved. The shared blind-bootstrap stage is both dominant and variable, so the
three-repetition isolated comparison is the appropriate measure of the planet
search itself. The complete v6 run reported 32.24 seconds inside the planetary
stage.

Both versions found 843 positional visits, ran 138 joint trials, retained the
same 138 candidate identities and reported `planet_epoch_not_identifiable`.
The largest candidate-epoch difference was 0.149 seconds and the largest RMS
difference was `3.28e-11` pixel. These are bounded exact-minimizer termination
differences, not changes to the camera, detections, gates or scientific status.
Every repetition also compared predicted coordinates, individual residuals and
altitudes, visibility decisions, source candidates, negative evidence, and the
planet CSV/JSON products. Both v5 and v6 reproduced their own full outputs on
all repeated runs.

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
