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

## Read the scientific goal first

Read [GOAL.md](GOAL.md) before changes and check `docs/FEATURE_STATUS.md` when
present. Blind solving is the primary contract: site/time metadata may be
revealed only after the fitted results are fixed, for separate validation.
Do not replace the photometric-zenith constraint with metadata-derived airmass
or describe a metadata-centred planet lookup as blind epoch inference.
Preserve implemented capabilities and add regression evidence for new ones.

## Consolidated version boundary

`go.sh` is the preserved root Tycho-2/Hipparcos workflow. Never point it at Gaia
or replace its dependencies as part of a v4 update. `docs/legacy-runtime.json`
records the unchanged pre-Gaia runtime. `go4.sh` and `go_v0.4.3.sh` use the tracked
`v4/` package, including its own catalogue and `uv.lock`; they must work without
`.worktrees`. Make upgrade changes in `v4/` and deliberately update its source
manifest. Test both versions before publishing. Never merge a development
worktree wholesale over the root legacy implementation.
