# Wide-Field Solver v0.25.1

Wide-Field Solver v0.25.1 is the current stable release of the v25 runtime by
Peter Thejll and Chris Flynn. It supersedes v0.25.0 and is available from the
[GitHub release page](https://github.com/hotblack43/WIDE-FIELD-SOLVER/releases/tag/v0.25.1).

## Hotfix

The v23, v24, and v25 planet-photometry commands now accept the combined
`RGB` channel requested by their production launchers. The earlier parser
accepted only the three individual channels, so the routine derived-product
stage stopped before creating its RGB products. The astrometric and
photometric numerical methods are unchanged.

Successful masked v0.25.0 MMTO receipts remain recognised as completed work.
New runs and derived-product provenance report v0.25.1.

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

## Verification

The release boundary passes the full Python regression suite, including a
regression test that invokes the v23-v25 planet-photometry CLIs with `RGB`.
The required bundled demonstration still produces 3,653 associations,
0.397892-pixel RMS, and 40 labels. The exact release commit is also exercised
by clean-clone Ubuntu 24.04 and Ubuntu 26.04 CI jobs.

The release includes curated `.tar.gz` and `.zip` packages, an interactive
code floorplan, and `SHA256SUMS`. Verify the downloaded files with:

```sh
sha256sum -c SHA256SUMS
```
