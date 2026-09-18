# V8 version boundary design

**Date:** 2026-09-18

**Status:** Approved in chat for specification. Implementation begins only
after review of this written design.

## Objective

Freeze the complete v7 runtime at its present `v0.7.0` state and establish an
independent `v8/` runtime at version `0.8.0`. The initial v8 runtime must be a
functional clone of v7: it may differ only where version ownership, launcher
routing, manifests, documentation, or tests must name v8. Count-rate
photometry, minor planets, and saturation-wing fitting belong to later v8 work
and must not enter this boundary change.

The root Tycho workflow and the preserved v4, v5, and v6 packages remain
unchanged. V7 must also remain byte-identical after its freeze manifest is
created.

## Preservation boundary

Create `docs/v7-runtime.json` with:

- the current source commit as the preserved commit;
- a statement that this is the exact v7 snapshot at the v8 boundary;
- SHA-256 hashes for `go7.sh`, `go_v0.7.0.sh`, and every tracked file under
  `v7/`.

Generated environments, caches, result directories, and other ignored or
untracked files are not runtime sources and must not enter the manifest. Four
historical assets are an explicit exception discovered during clean-worktree
verification: the v7 source manifest already records the example input,
identified-star image, and two diagnostic plots, but the repository-wide image
ignore rules left their bytes untracked. Their bytes must first be verified
against `v7/SOURCE_MANIFEST.json` and then committed as ordinary Git blobs so a
clean export actually contains the historical evidence. A preservation test
will recompute every recorded hash, reject missing or changed files, require
every source-manifest asset to be tracked, and ensure the freeze manifest covers
the complete tracked v7 runtime.

After this manifest is generated, the implementation must not edit either v7
launcher or any file under `v7/`.

## Independent v8 runtime

Copy the tracked v7 package into `v8/`; do not copy `v7/.venv`, writable
ephemeris caches, analysis results, or other generated state. V8 receives its
own copies of all runtime code and data, including:

- `uv.lock`, `pyproject.toml`, and `.python-version`;
- the Gaia catalogue and provenance files;
- the bundled planet ephemeris and its builder;
- source and example manifests;
- tests, documentation, demo assets, and launcher scripts.

The clone will then receive narrow identity updates:

- solver/package version `0.8.0`;
- internal runtime labels that identify the active package as v8;
- v8-local paths and documentation links;
- `v8/SOURCE_MANIFEST.json`, regenerated deliberately after the identity-only
  edits.

Scientific constants, algorithms, thresholds, catalogues, reference products,
and expected numerical results remain unchanged. The initial v8 test suite must
therefore reproduce v7 behavior except for explicit version/path assertions.

## Launchers and outputs

Add `go8.sh` and `go_v0.8.0.sh`. Both route only to `v8/run.sh`; neither may
source or import the v7 runtime. `go8.sh` is the current v8 launcher and
`go_v0.8.0.sh` is pinned to the initial v8 release identity.

V8 analysis directories use the existing collision-resistant convention with
`v0.8.0` in the run name. V8 resolves its catalogue, lockfile, ephemeris bundle,
Python modules, and scripts inside `v8/`. It may continue to append run evidence
to the repository-level results database because that database is an output,
never a solver input.

No existing launcher is repointed. In particular, `go7.sh` and
`go_v0.7.0.sh` continue to execute `v7/run.sh`.

## Repository documentation and policy

Update the root `AGENTS.md`, `README.md`, and `docs/CONSOLIDATION.md` so they
state that root, v4, v5, v6, and v7 are preserved and that new development
occurs only in v8. The copied `v8/AGENTS.md`, `v8/README.md`, and
`v8/docs/FEATURE_STATUS.md` will identify v8 as the active runtime and
`docs/v7-runtime.json` as its parent boundary.

Historical documents copied into v8 remain historical evidence. Identity
updates must not rewrite their scientific claims or make old v7 results appear
to be v8 results.

## Verification and failure handling

Add or extend repository tests to verify:

1. The v7 hash manifest is complete and exact.
2. Both v7 launchers still report and execute v0.7.0.
3. Both v8 launchers report and execute v0.8.0.
4. V8 imports runtime code only from `v8/` and works when no `.worktrees`
   directory exists.
5. The initial v8 suite reproduces the v7 numerical behavior.
6. Root, v4, v5, v6, v7, and v8 frozen dependency installations and unit suites
   pass.
7. The required root regression commands pass:
   `uv run --frozen python -m unittest discover -v` and
   `./demo.sh --output results/check-unique-name`.
8. V7 and v8 demo runs complete in distinct new output directories.

Manifest generation must fail rather than silently omit a tracked runtime file.
Launchers must fail clearly if their local package, catalogue, or reported
version is inconsistent. No regression threshold may be loosened to make the
clone pass.

## Development isolation and handoff

The work is performed in a detached isolated worktree as requested; no branch
is created. This is development isolation only. No runtime path may refer to
the worktree, and the final repository content must run from an ordinary clone
with no `.worktrees` directory. The preserved v7 tree is never replaced by or
merged over from another runtime.

## Deferred v8 work

After this clean boundary is verified, separate v8 designs and tests may add:

- exposure-provenanced per-channel count rates for identified stars and planet
  candidates;
- per-channel saturation handling and explicitly modelled wing estimates;
- local ephemerides and brightness models for Ceres and Vesta.

Those changes are deliberately excluded from the boundary so any later
scientific difference has a precise v7/v8 baseline.
