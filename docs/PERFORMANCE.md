# Performance profile

The preserved Milky Way example was profiled on 14 September 2026 with the
frozen Python 3.12 environment. Timings are machine-specific, but they identify
where this workload spends time.

## Baseline

An end-to-end demo took 26.14 seconds wall time and peaked at 905,644 KiB RSS.
The detailed deterministic profile attributed the largest cumulative costs to:

| Work | Profiled time |
|---|---:|
| Blind tetra3 bootstrap | 8.87 s |
| PNG encoding | 5.97 s |
| Point-source detection | 2.26 s |
| All 23 nonlinear camera fits | 2.21 s |
| Catalogue association | 0.88 s |

Rendering and encoding diagnostic products therefore cost more than the
Barghini fit itself. Reordering blind-bootstrap attempts was deliberately not
used as an optimization because a demo-specific order could reduce robustness
on other fields.

## Lossless PNG optimization

Generated PNG figures use zlib compression level 1. A controlled re-encoding
of the six demo PNGs reduced encoding time from 5.73 to 1.43 seconds. The files
were 15.6% larger, but every decoded pixel was identical.

The complete post-change demo took 22.96 seconds, 3.18 seconds or 12.2% less
wall time than the baseline. It reproduced the numerical baseline exactly:
3,653 catalogue associations, 0.39789212181523126-pixel RMS, and 40 distributed
labels. Detection, associations, Barghini parameters, saved coordinates,
residuals, plot resolution, and plotted positions are unchanged. The historical
reference products were not modified.

## Verification

```sh
uv run --frozen python -m unittest discover -v
/usr/bin/time -v ./demo.sh --output results/check-unique-name
```

For function-level investigation, invoke `point_star_barghini.run` under
`cProfile`; profiling `scripts/run_demo.py` alone only measures time waiting for
its solver subprocess.
