# Gaia v4 runtime

Run `./go4.sh /path/to/image.jpg` from the repository root. This directory contains
v0.4.3 and its local Python modules, Gaia catalogue, provenance, dependency lockfile,
tests and scientific status. No development worktree is required.

The root `go.sh` remains the preserved Tycho-2/Hipparcos workflow. Its modules and
lockfile are separate. For the exact implemented science and remaining limitations,
read [GOAL.md](GOAL.md) and [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).

`SOURCE_MANIFEST.json` records the copied source files, including the tested
bootstrap fallback and report-label fixes present at consolidation. New v4 changes
belong here; development-worktree changes do not automatically update this package.

Validation, from this directory:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```
