# Consolidated preserved and current solver paths

- `go.sh` runs the root Tycho-2/Hipparcos standalone-report workflow.
- `go4.sh` and `go_v0.4.3.sh` run the committed Gaia v0.4.3 package in `v4/`.
- `go5.sh` and `go_v0.5.0.sh` run the frozen Gaia v0.5.0 package in `v5/`;
  `docs/v5-runtime.json` records every preserved runtime hash.
- `go6.sh` and `go_v0.6.0.sh` run the frozen Gaia v0.6.0 package in `v6/`;
  `docs/v6-runtime.json` records every preserved runtime hash.
- `go7.sh` and `go_v0.7.0.sh` run the frozen Gaia v0.7.0 package in `v7/`;
  `docs/v7-runtime.json` records every preserved runtime hash.
- `go8.sh` and `go_v0.8.0.sh` run the frozen Gaia v0.8.0 package in `v8/`;
  `docs/v8-runtime.json` records every preserved runtime hash.
- `go8a.sh` runs the frozen independent v8a work snapshot in `v8a/`;
  `docs/v8a-runtime.json` records every preserved runtime hash.
- `go9.sh` and `go_v0.9.0.sh` run the current Gaia v0.9.0 package in `v9/`.
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

The six primary launchers work directly from this checkout and never require a
named worktree. Versioned v0.4.3, v0.5.0, v0.6.0 and v0.7.0 launchers select
their local packages explicitly.

The legacy science report retains its historical behaviour, including metadata-
assisted downstream diagnostics. It does not gain v4's blind epoch/planet model.
No v4 fixes are silently backported to the frozen Tycho runtime.

## Future work

Change and test the current runtime in `v9/`; update its source manifest
deliberately. Keep root legacy, v4, v5, v6, v7, v8 and v8a hashes fixed. Repointing a preserved
launcher requires an explicit decision, not merging a development branch over
its runtime. CI and release verification cover all preserved suites and demos.

## Validation of the consolidation

The root suite passes 42 tests and v4 passes 118. A clean export of the exact
staged files, with no `.worktrees`, passed launcher routing/preservation checks
and both historical demos: 3,653 associations, 0.397892-pixel RMS, 40 labels.
The root legacy runtime hashes still match `c023f1c`. Both lockfiles and every
required v4 catalogue, Python module, shell entrypoint and example are included.

Planet markers in v4 are hollow magenta stars so that the measured source
remains visible at their centres. The legend uses the same symbol. This display
change does not alter coordinates or fitted results.
