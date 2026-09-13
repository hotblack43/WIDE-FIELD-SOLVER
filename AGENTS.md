# Preserve the working wide-field solver

This is an independent point-star project. Keep runtime code and data local to
this repository; never import from the trail-processing project.

The `v0.1.0` tag preserves the first working release. The example input and
`examples/milky_way/reference/` are historical evidence. Preserve them when
developing new features. Do not relax regression thresholds to hide failures.

All detected sources are available for association and fitting. Do not introduce
withheld stars by default. Keep large/saturated source detection. Names are
display-only; cached identifiers or saved solutions must never seed the demo.

Astrometric corrections must be made in the Barghini model and propagated to
the saved coordinates. Plot measured centroids and model predictions faithfully:
never apply cosmetic radial shifts or move symbols to improve their agreement.
Any magnification of residual vectors must be explicitly labelled and must not
alter the actual-position overlay or numerical residuals.

Before committing changes, run both:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Keep `uv.lock` committed. Document numerical changes and their reasons. Leave
the historical comparison with solve-field factual and bounded by its tests.
