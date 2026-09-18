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
| `go9.sh` | **Current development** | v0.9.0 consolidated runtime and current reports |

For new work, use `go9.sh`. Use an earlier launcher only when reproducing an
older result or testing an explicitly version-dependent change.

## Releases versus the development line

The latest packaged GitHub release is v0.6.0. The repository's main branch has
subsequently retained v0.7.0, v0.8.0, v8a and v0.9.0 as separately preserved
runtimes. Calling v0.9.0 “current” therefore describes the development line; it
does not imply that a v0.9.0 release asset has been published.

The complete launcher syntax and output-directory behaviour remain in the
repository's `REFERENCE.md`.
