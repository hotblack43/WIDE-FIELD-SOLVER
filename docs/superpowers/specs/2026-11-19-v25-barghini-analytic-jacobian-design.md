# V25 Barghini Analytic Jacobian Design

## Intent

Reduce v25 single-image solver time further by eliminating repeated numerical
differentiation of the Barghini camera and integrated-refraction residuals.
Preserve the exact residual definition, robust radial soft-L1 objective,
parameter bounds, blindness boundary, association sequence, scientific
products, and SciPy trust-region optimizer.

## Profile evidence

The final representative MMTO profile executed 67,063,709 Python-visible calls
in 72.237 profiler-seconds. `fit_camera()` accounted for 14.319 seconds.
SciPy numerical differentiation accounted for 13.220 seconds. The ordinary
eight-parameter residual ran 3,535 times, while the joint camera/refraction
residual ran 31,033 times and consumed 11.952 seconds. The joint residual is
therefore the primary target; compiling only the ordinary residual cannot make
an appreciable end-to-end difference.

## Selected approach

Add a narrow vectorized analytic-Jacobian module for the existing residuals.
It will propagate derivatives from the eight normalized Barghini parameters
through detector-to-camera rays, and from azimuth, inclination, A, and B through
the integrated-refraction model. It will then propagate both ray Jacobians
through the existing two-axis tangent-plane residual and radial soft-L1
transformation. Monotonicity and horizon-penalty rows retain their current
piecewise definitions and receive matching derivatives.

`fit_camera()` will continue to call `scipy.optimize.least_squares` with the
same bounds and tolerances, but will supply the analytic Jacobian. A small
last-input cache will prevent SciPy's separate residual and Jacobian callbacks
from calculating the same state twice. Fits with a fixed, already nonzero
refraction state may retain the current numerical derivative until their
inverse-refraction derivative is implemented and independently validated.

## Alternatives considered

1. **Vectorized analytic NumPy Jacobian — selected.** NumPy executes the array
   kernels in compiled code, while explicit derivatives remove the eight or
   twelve repeated residual evaluations. This adds no runtime dependency and
   keeps every equation inspectable.
2. **JAX automatic differentiation and JIT.** This avoids hand derivatives but
   adds a large dependency, requires a parallel implementation of the model,
   and would compile repeatedly for the solver's changing association counts.
   It is a useful independent derivative oracle, not the first production path.
3. **Rust/PyO3 extension.** This offers strong low-level control but still needs
   the same derivative mathematics and Python packaging. It is justified only
   if profiling after the analytic Jacobian shows the remaining vectorized
   kernel itself is a material bottleneck.

## Numerical validation

- Compare every analytic Jacobian column against central finite differences at
  multiple interior camera/refraction states, including mirrored parity.
- Exercise zero residuals, ordinary residuals, active robust downweighting,
  active monotonicity penalties, and active horizon penalties.
- Compare analytic and existing numerical fits from identical seeds for cost,
  parameters, predicted coordinates, association identities, and convergence.
- Preserve numerical differentiation as an explicit test/control mode until
  representative MMTO equivalence and runtime improvement are demonstrated.
- Reject the production switch if candidate membership changes or if fitted
  model predictions differ beyond established floating optimizer noise.

## Performance acceptance

Benchmark the same native MMTO image and one-process command used for the
digest/image and planet-state optimization. Report ordinary and joint residual
call counts, stellar-stage time, total wall time, and peak RSS. The change is
accepted only if the complete representative solve is measurably faster; a
microbenchmark-only improvement is insufficient.

## Non-goals

- No change to the Barghini equations, robust loss, fitting thresholds, source
  membership, refraction selection, epoch search, or output products.
- No new outer or inner parallelism.
- No Rust, JAX, Numba, GPU, or assembler dependency in this first production
  implementation.
- No modification of frozen v24 or earlier runtimes.

## Failure handling

Non-finite derivative states fail explicitly rather than silently falling back
during a scientific fit. The numerical control path remains callable for tests
and diagnosis. Production uses the analytic path only after focused derivative,
fit-equivalence, full-suite, demo, and representative MMTO checks pass.
