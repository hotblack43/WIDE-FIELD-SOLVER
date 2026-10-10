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

## State action honestly and react immediately

Use language that distinguishes these states exactly:

- Before beginning work, say `I will ... now` or `I am starting ... now`, then
  perform that action in the same turn.
- Say `I am continuing` only when work actually continues in that same turn,
  with a tool call, wait, or concrete progress update following it. Never use
  present-progress language merely to acknowledge a command.
- If an external process is independently running, identify it as such; do not
  imply that Codex is actively monitoring or working after yielding the turn.
- If waiting for Peter's instruction or approval, say so explicitly. Never make
  Peter type `go` or `yes` merely to trigger an already clear, safe next action.
- After Peter says `go` or `yes`, state exactly what will start and start it in
  that same turn. A status-only reply is not sufficient.

When ongoing work requires more time, keep the turn active and provide concise,
evidence-backed progress updates. If yielding instead, say what has actually
stopped, what external process remains active, and what future action still
requires another turn.

## Read the scientific goal first

Read [GOAL.md](GOAL.md) before changes and check `docs/FEATURE_STATUS.md` when
present. Blind stellar solving remains the primary contract: site/time metadata
may be revealed only after the astrometric, refraction and photometric-zenith
results are fixed. V11 searches the full supported causal planet interval,
regardless of metadata. Metadata is separate post-selection validation;
it cannot bound the epoch or fix identities. `--blind-planets` also skips
metadata reading in the planetary stage. Do not replace
the photometric-zenith constraint with metadata-derived airmass.
Preserve implemented capabilities and add regression evidence for new ones.

## Version boundary

This directory is the active experimental v0.16.0 runtime. Keep root legacy,
`v4/`, `v5/`, `v6/`, `v7/`, `v8/`, the independent `v8a/` work snapshot,
`v9/`, `v10/`, `v11/`, and `v12/` unchanged; `../docs/v12-runtime.json` freezes
the experimental v12 snapshot, v13, and v14 unchanged; `../docs/v14-runtime.json`
freezes the lunar-corroboration v14 checkpoint; `../docs/v15-runtime.json`
freezes v15. Develop v16 changes only here and through `go16.sh` or
`go_v0.16.0.sh`. Keep this package self-contained and runnable without
`.worktrees`.

## Language
- No LaTeX file destined for, copied from, mirrored with, or synchronized to Overleaf may contain the word `contract`; treat it as an AI mannerism. Before any Overleaf upload, push, or synchronization, search the entire project case-insensitively and remove every occurrence from the material being synchronized. For audit-only requests, report occurrences without editing the `.tex` files unless the user explicitly asks for changes.
