# Two preserved solver paths

- `go.sh` runs the root Tycho-2/Hipparcos standalone-report workflow.
- `go4.sh` and `go_v0.4.3.sh` run the committed Gaia v0.4.3 package in `v4/`.
- Every root legacy Python module, script, dependency lockfile, catalogue and
  historical example in `legacy-runtime.json` matches pre-Gaia commit `c023f1c`.
- Gaia work is contained in `v4/`, including proper motions, blind stellar and
  planetary date searches, physical visibility checks, photometric zenith,
  report improvements and the tested bootstrap fallback. Scientific limitations
  remain recorded in `v4/docs/FEATURE_STATUS.md`.
- The original `v0.1.0` tag and all historical files remain intact. Both solver
  paths are available on `main` through consolidation PR #1. The checkpoint tag
  `pre-consolidation-2026-09-15` preserves the previous GitHub `main` at `392bedb`.
  Existing development branches and worktrees are retained.

The old root `go.sh` was a wrapper around `go_v0.4.0.sh`, which explicitly selected
Gaia. It has been corrected locally as well as in the published branch. Tests run
the shell launchers without `.worktrees` and check the selected project/catalogue;
a checksum test catches unintended changes to the preserved legacy runtime.

Earlier versioned launchers remain historical development entrypoints and can
still require their named worktree. Only `go.sh`, `go4.sh` and `go_v0.4.3.sh` are
supported from this consolidated checkout alone.

The legacy science report retains its historical behaviour, including metadata-
assisted downstream diagnostics. It does not gain v4's blind epoch/planet model.
No v4 fixes are silently backported to the frozen Tycho runtime.

## Future work

Change and test v4 in `v4/`; update its source manifest deliberately when its
files change. Keep root legacy hashes fixed. Repointing `go.sh` or changing its
legacy runtime requires an explicit decision, not merging a Gaia development
branch wholesale. CI runs both suites and both historical demos.

## Validation of the consolidation

The root suite passes 42 tests and v4 passes 118. A clean export of the exact
staged files, with no `.worktrees`, passed launcher routing/preservation checks
and both historical demos: 3,653 associations, 0.397892-pixel RMS, 40 labels.
The root legacy runtime hashes still match `c023f1c`. Both lockfiles and every
required v4 catalogue, Python module, shell entrypoint and example are included.

Planet markers in v4 are hollow magenta stars so that the measured source
remains visible at their centres. The legend uses the same symbol. This display
change does not alter coordinates or fitted results.
