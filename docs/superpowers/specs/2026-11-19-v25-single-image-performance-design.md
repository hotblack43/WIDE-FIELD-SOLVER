# V25 Single-Image Performance Design

## Intent

Make `go_mmto_photometry_v25.sh` appreciably faster through faster single-image
code, independently of its existing outer solver concurrency. Preserve the v25
scientific results, blindness boundary, receipts, and output products.

## Profile evidence

A representative successful native MMTO solve spent about 13 profiler-seconds
decoding the same bzip2 FITS source 13 times and about 21.5 profiler-seconds in
4,315 scalar Astropy body evaluations. The numerical kernels are already in
compiled NumPy/SciPy/ERFA code; repeated library calls, not Python arithmetic,
are the first-order avoidable costs.

## Approaches

1. **Reuse verified decode and scalar ephemeris states (selected).** Cache the
   scientific image by source digest and load policy inside one solver process,
   and cache exact scalar planet ray/projection states inside one blind search.
   This removes duplicate compiled-library work without changing algorithms.
2. Add Numba around Python loops. Rejected for the first pass because the hot
   work is bzip2, Astropy/ERFA, SciPy, and rendering calls that Numba cannot
   compile through.
3. Rewrite the solver in Rust/C++. Rejected for the first pass because the hot
   kernels are already native; a rewrite would mainly duplicate mature FITS,
   optimization, ephemeris, and plotting libraries while increasing scientific
   validation risk.

## Constraints

- Change only the active v25 runtime and its v25 pipeline documentation/tests.
- Preserve exact input-byte verification and invalidate cached image data when
  the digest or load policy differs.
- Do not change fit thresholds, candidate membership, scientific outputs, or
  the existing solver-worker behavior.
- Require numerical equivalence on a representative successful MMTO image and
  a measured warm-filesystem wall-time improvement at `--solver-workers 1`.
