# Wide-Field Solver v0.25.0

Wide-Field Solver v0.25.0 is the stable public release of the active v25
runtime by Peter Thejll and Chris Flynn. It was published on 20 November 2026
from commit `ccd0b52ff6c364554413a5fa6fc002730267acc7` and is available from the
[GitHub release page](https://github.com/hotblack43/WIDE-FIELD-SOLVER/releases/tag/v0.25.0).

## First run

Ubuntu 24.04 and Ubuntu 26.04 LTS on x86-64 are certified. A new machine needs
Bash, Git, HTTPS certificates, `tar`, `sha256sum`, and either `curl` or `wget`:

```sh
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
./quickstart.sh
```

The bootstrap installs checksum-verified `uv` and managed Python 3.12 inside
the clone, synchronises the frozen v25 environment, and runs the bundled MMTO
verification. A passing run creates `results/quickstart-v25/report.pdf`.

Solve another image with:

```sh
./go25.sh /full/path/to/image.fits
```

## Curated downloads

Use one of the named solver archives from the release page rather than
GitHub's automatic source-code archives. The TAR and ZIP packages contain the
same 510 paths and include the v25 runtime, locked environment, catalogue and
ephemerides, approved MMTO installation mask, demonstration image, launchers,
tests, documentation, and rights information.

The release also provides `SHA256SUMS` and a self-contained interactive
`wide-field-solver-v0.25.0-floorplan.html` map of the active v25 code. Its
published checksums are:

```text
3c2bd6996332fd44e29dc914c62832a2f761a2e38f157aebac702f09c4f62f73  wide-field-solver-v0.25.0-floorplan.html
0ff9794890a845c041da384b3de1adb3840644d22cc2f372f8c6bd9969a27fbd  wide-field-solver-v0.25.0.tar.gz
01e36beb10f51235f40ba466e91aa19168f011ecef94ceaa3a0b24f94917aeca  wide-field-solver-v0.25.0.zip
```

For example, verify and unpack the TAR package with:

```sh
grep 'wide-field-solver-v0.25.0.tar.gz$' SHA256SUMS | sha256sum -c -
tar -xzf wide-field-solver-v0.25.0.tar.gz
cd wide-field-solver-v0.25.0
./quickstart.sh
```

## Verified release boundary

The exact release commit passed clean-clone bootstrap and demonstration runs
on Ubuntu 24.04 and Ubuntu 26.04. The v25 operator, calibration, frozen-v24
boundary, and bundled numerical demonstration checks also passed in the
[release workflow](https://github.com/hotblack43/WIDE-FIELD-SOLVER/actions/runs/44731587389).

Before publication, the four uploaded assets were downloaded from the draft
release. Their bytes matched the local release set, all three published
checksums passed, both archive formats passed integrity checks, and the tag
resolved to the release commit.

The masked MMTO demonstration retains 1,280 stellar associations at
0.326263-pixel RMS (2.522 arcmin). These are fitted residuals, not an
independent withheld-star validation.

## Scope

V25 retains the accepted v24 installation-mask workflow and adds the
clean-machine bootstrap plus the configuration-driven
`go_visible_sky_v25.sh` operator. Automatic mask construction inside the
routine `go_mmto_photometry_v25.sh` pipeline is deferred beyond v0.25.0. MMTO
is the only physical camera installation with complete cold-start validation
evidence in this release.

Earlier launchers and runtime directories remain available for reproducible
comparison and are protected by their recorded manifests.

## Rights and credit

Project-authored software is Copyright (c) 2026 Peter Thejll and Chris Flynn
and is available under the BSD 3-Clause licence. Third-party catalogues,
models, dependencies, and observations retain their own terms; see
`NOTICE.md`.

Required example credit: **MMTO all-sky-camera image courtesy of MMT
Observatory, provided with permission from Tim Pickering.**
