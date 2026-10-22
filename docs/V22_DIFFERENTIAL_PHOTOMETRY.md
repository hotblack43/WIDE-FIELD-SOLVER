# V22 differential photometry

V22 tests four corrections on held-out nights and stars:

1. local comparison-star ensemble;
2. random forest;
3. gradient boosting;
4. small neural network.

The simplest method that improves both held-out scatter and haze/airmass trend
is selected. It then gets one final pseudo-planet test. If either gate fails,
V22 keeps the raw and v21 values but publishes no corrected planet magnitude.

The benchmark is local and read-only. It does not query JPL and does not change
`stars.sqlite` or the MMTO manifest.

Run it directly with:

```sh
./run_v22_photometry_benchmark.sh \
  --database results/stars.sqlite \
  --manifest raw_allsky_samples/manifest.sqlite \
  --v21-control results/photometry-runs/RUN/nightly-extinction \
  --output results/photometry-runs/v22-benchmark
```

The routine v22 pipeline freezes a completed v21 control directory before any
v22 work, runs the benchmark last, and records operational and scientific gates.

## Current MMTO result

The corrected 2026-10-22 benchmark used 590 runs, 1,449,615 stellar channel
measurements, and 36,993 planet channel measurements. Its 50,803 validation rows
were jointly held out by night and star identity. Injected signals were measured
as preserved, but every method still failed either R/B improvement or residual
brightness, radius, or PSF-width tests. No v22 planet correction was published.
