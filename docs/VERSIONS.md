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
| `go21.sh` | Frozen | v0.21.0 FITS-header-timed MMTO reprocessing and post-fit validation |
| `go22.sh` | Frozen experiment | v0.22.0 differential-photometry model benchmark |
| `go23.sh` | Frozen | v0.23.0 aperture and sky-annulus validation |
| `go24.sh` | Frozen | v0.24.0 accepted generic camera-installation calibration checkpoint |
| `go25.sh` | Active development | v0.25.0 configuration-driven visible-sky operator and masked MMTO processing |

For current installation-masked MMTO development from a repository checkout,
use `go_mmto_photometry_v25.sh`. Configure a new installation through
`go_visible_sky_v25.sh`. Use `go17.sh` only for its independent
KNALDGAS line, and use earlier launchers when reproducing older results.

## Releases versus the development line

The **Latest packaged release** is v0.11.0. Download the named `.tar.gz` or
`.zip` asset and `SHA256SUMS` from that release; GitHub's automatic source-code
archives are not the curated runnable package. The active v0.25.0 development
runtime is used from a repository checkout. It preserves v24's approved
installation mask, generic calibration registry, immutable checksum assignments,
and cold-start MMTO evidence while adding the public configuration-driven
operator command. Every earlier launcher remains separate; v25 is not
represented as a published release.

The complete launcher syntax and output-directory behaviour remain in the
repository's `REFERENCE.md`.
