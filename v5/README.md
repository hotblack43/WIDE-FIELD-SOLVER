# Gaia v5 runtime

For installation, choosing a solver and running images, use the
[shared guide for go.sh, go4.sh and go5.sh](../README.md).

Run `./go5.sh /path/to/image.jpg` or `./go_v0.5.0.sh /path/to/image.jpg` from the
repository root. This directory contains v0.5.0 and its local Python modules,
Gaia catalogue, provenance, dependency lockfile, tests and scientific status.
No development worktree is required.

The root `go.sh` remains the preserved Tycho-2/Hipparcos workflow. `go4.sh` and
`go_v0.4.3.sh` keep the preserved Gaia v0.4.3 package under `v4/`. Each runtime
has separate modules and a lockfile. For the implemented science and remaining
limitations, read [GOAL.md](GOAL.md) and [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).

`SOURCE_MANIFEST.json` records this version's source inventory. The baseline is
v0.4.3 at commit `d8ca43891d9943e17c27ad56cdecb299df3cf1d5`; new v5 development
belongs here. The preserved v4 files and launchers are recorded in
[../docs/v4-runtime.json](../docs/v4-runtime.json).

Validation, from this directory:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
```

Bright-planet evidence, numerical rules and limitations: [docs/PLANET_NONDETECTIONS.md](docs/PLANET_NONDETECTIONS.md).
