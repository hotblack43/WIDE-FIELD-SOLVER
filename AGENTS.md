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

`go.sh` is the preserved root Tycho-2/Hipparcos workflow. Its runtime is
recorded in `docs/legacy-runtime.json`. `go4.sh`, `go_v0.4.3.sh`, and the complete
`v4/` package are frozen at the public `v0.4.3` checkpoint; their hashes are in
`docs/v4-runtime.json`. `go5.sh`, `go_v0.5.0.sh`, and the complete `v5/` package
are also frozen; their hashes are in `docs/v5-runtime.json`. Never replace a
preserved version during an upgrade.

Develop upgrades in `v6/`, launched by `go6.sh` or `go_v0.6.0.sh`, with its own
catalogue, lockfile, ephemeris data and source manifest. All versions must work
without `.worktrees`. Update the v6 manifest deliberately and test all four
versions before publishing. Never merge a development worktree over a preserved
runtime.

## Local patch-helper fallback

In this repository, the `apply_patch` helper is known to fail during sandbox
setup with `bwrap: loopback: Failed RTM_NEWADDR`. Once that exact failure has
occurred in a session, do not retry the helper for every edit. Use a narrow
`git apply` patch directly instead, then inspect the resulting diff. Keep this
as a fallback only for the known helper failure; it does not relax the
requirements to preserve unrelated working-tree changes or to avoid destructive
commands.
