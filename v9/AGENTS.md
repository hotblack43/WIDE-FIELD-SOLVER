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
present. Blind stellar solving remains the primary contract: site/time metadata
may be revealed only after the astrometric, refraction and photometric-zenith
results are fixed. The default v8 planet stage may then use an EXIF, FITS,
filename or explicit observation time to bound a metadata-conditioned local
fit; it must record that provenance and must not describe the result as blind
epoch inference. `--blind-planets` preserves the full blind planetary search,
which is also the automatic fallback when no usable time exists. Do not replace
the photometric-zenith constraint with metadata-derived airmass.
Preserve implemented capabilities and add regression evidence for new ones.

## Version boundary

This directory is the active v0.9.0 runtime. Keep root legacy, `v4/`, `v5/`,
`v6/`, `v7/`, `v8/`, and the independent `v8a/` work snapshot unchanged;
`../docs/v8-runtime.json` and `../docs/v8a-runtime.json` record the exact parent
snapshots. Develop v9 changes only here and through `go9.sh` or
`go_v0.9.0.sh`. Keep this package self-contained and runnable without
`.worktrees`.

## Language
- No LaTeX file destined for, copied from, mirrored with, or synchronized to Overleaf may contain the word `contract`; treat it as an AI mannerism. Before any Overleaf upload, push, or synchronization, search the entire project case-insensitively and remove every occurrence from the material being synchronized. For audit-only requests, report occurrences without editing the `.tex` files unless the user explicitly asks for changes.
