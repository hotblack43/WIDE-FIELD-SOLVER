# Preserve Tycho and publish Gaia v4

**Goal:** Restore local `go.sh` to the preserved Tycho PDF workflow and publish a self-contained Gaia `go4.sh`, without replacing the stable GitHub branch.

**Architecture:** Keep the root Tycho runtime unchanged from pre-Gaia commit `c023f1c`. Copy the tested v0.4.3 runtime, data, lockfile, tests and evidence into `v4/`. Root launchers explicitly select one implementation. A fresh checkout must work without development worktrees.

**Authorization:** User requested the local correction and a safe GitHub push. Publish a new branch and PR against `main`; do not force-push or merge main. Leave development worktrees and the historical release intact.

## Tasks

- [x] Add launcher integration tests using a fake `uv` executable that captures the selected project, entrypoint and catalogue; exercise paths containing spaces. Verify the tests expose the current Gaia routing of `go.sh` and absent packaged v4.
- [x] Change `go.sh` to delegate to the original `go_solve_wide.sh` Tycho PDF workflow. Keep the root runtime, root lockfile, catalogue, example and historical reference bytes unchanged. Record these hashes in `docs/legacy-runtime.json` and verify them in tests.
- [x] Package v4 from `feature/visibility-v0.4.3` plus its tested uncommitted bootstrap/report fixes. Copy runtime Python, analysis/demo/solve scripts, data, lockfile, tests, scientific documentation and historical example. Exclude virtual environments, generated results, git metadata and the unrelated Overleaf submodule. Record source hashes.
- [x] Route root `go4.sh` and `go_v0.4.3.sh` into the packaged runtime. Keep other version-specific launchers unchanged. Test the Gaia catalogue and blind epoch flags through the actual shell route.
- [x] Update README and CI to document and test both variants. Run root and v4 complete unittest suites and historical demos. Verify packaging from a clean exported checkout with no `.worktrees` or local environments.
- [x] Review the staged file list and preservation hashes, commit, push only `release/preserve-tycho-publish-gaia-v4`, and open a PR against main. Verify remote main and `v0.1.0` did not move.
