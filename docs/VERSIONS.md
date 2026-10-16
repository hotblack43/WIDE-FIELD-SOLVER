# Version guide

The repository intentionally preserves earlier working solvers. Existing
launchers and version directories are protected by manifests and regression
tests; they are not aliases for the newest code.

| Launcher | Status | Distinguishing behaviour |
|---|---|---|
| `go.sh` | Preserved legacy | Tycho-2/Hipparcos historical workflow |
| `go4.sh` | Frozen | Gaia v0.4.3 checkpoint |
| `go5.sh` | Frozen | v0.5.0 planet non-detection evidence |
| `go6.sh` | Frozen | v0.6.0 faster planetary search |
| `go7.sh` | Frozen | v0.7.0 detector-parity selection |
| `go8.sh` | Frozen | v0.8.0 compressed FITS, count rates and saturated wings |
| `go8a.sh` | Frozen work snapshot | Portable result storage plus v8 capabilities |
| `go9.sh` | Frozen | v0.9.0 consolidated runtime and reports |
| `go10.sh` | Frozen | v0.10.0 native colour inputs and metadata-conditioned planet validation |
| `go11.sh` | Latest packaged release; frozen | v0.11.0 joint stellar/planetary epoch profile and permitted MMTO demo |
| `go12.sh` | Frozen experiment | v0.12.0 radial-model study |
| `go13.sh` | Frozen | v0.13.0 integrated-refraction runtime |
| `go14.sh` | Frozen | v0.14.0 lunar corroboration runtime |
| `go15.sh` | Frozen | v0.15.0 early combined Sun/Moon gating |
| `go16.sh` | Frozen | v0.16.0 planet-only empirical extinction in the MMTO workflow |
| `go17.sh` | Independent development line | v0.17.0 KNALDGAS linear-RGB work |
| `go18.sh` | Frozen experiment | v0.18.0 two-night-at-a-time full-range backlog inventory |
| `go19.sh` | Frozen | v0.19.0 variable-star time series on the v16 scientific model |
| `go20.sh` | **Recommended MMTO runtime** | v0.20.0 bounded 40-image acquisition with one-night requests and a durable backward cursor |

For bounded MMTO archive work from a repository checkout, use
`go_mmto_photometry_v20.sh`. Use `go17.sh` only for its independent KNALDGAS
line, and use earlier launchers when reproducing older results.

## Releases versus the development line

The latest packaged GitHub release is v0.11.0. Download the named `.tar.gz` or
`.zip` asset and `SHA256SUMS` from that release; GitHub's automatic source-code
archives are not the curated runnable package. The recommended MMTO v0.20.0
runtime is currently used from a repository checkout. It retains v19's
variable-star and inherited v16 products while replacing v18's complete-range
inventory with one-night requests. Each invocation selects at most 40 images
by default, skips any image with an existing solver receipt, and advances a
durable cursor only after the selected batch has receipts. Every earlier
launcher remains separate.

The complete launcher syntax and output-directory behaviour remain in the
repository's `REFERENCE.md`.
