# Quick start

## Certified systems

The v25 clean-clone path is tested on Ubuntu 24.04 and Ubuntu 26.04 LTS on
x86-64. Ubuntu 24.04 is the minimum supported baseline. Native Windows, macOS,
ARM, and other Linux distributions are not certified by this release.

A new machine needs Bash, Git, HTTPS certificates, `tar`, `sha256sum`, and
either `curl` or `wget`. It does not need a preinstalled Python or `uv`.
Internet access is required for the first dependency installation.

## Clone and verify

```bash
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
./quickstart.sh
```

The command downloads the pinned Linux x86-64 `uv` archive, verifies its
recorded SHA-256 checksum, and installs it under `.tools/`. It then obtains
Python 3.12 and the exact packages in `v25/uv.lock` before running the bundled
MMTO demonstration. A successful run prints:

```text
results/quickstart-v25/report.pdf
```

Open that PDF to inspect the first verified solution. The demonstration uses
the bundled catalogue, installation mask, MMTO input, and numerical baseline;
it does not require a separate input image.

## Solve your image

```bash
./go25.sh /full/path/to/image.fits
```

Compressed FITS, common raster formats, and supported camera RAW inputs may be
passed directly. Quote paths containing spaces. Each image receives its own
analysis directory and the launcher prints the resulting report path.

```bash
./go25.sh /full/path/to/image.fits.bz2
./go25.sh /full/path/to/image.cr2
```

Use `./go25.sh --help` for FITS HDU, channel-order, saturation, output, and
visible-sky calibration options.

## Local generated files

The bootstrap keeps its state inside the clone:

- `.tools/uv/0.9.30/uv`: verified bootstrap executable;
- `.tools/python/`: managed Python runtime;
- `.tools/cache/`: dependency downloads;
- `v25/.venv/`: frozen v25 environment; and
- `results/quickstart-v25/`: verification result.

All five paths are ignored by Git. To start again, remove only `.tools/`,
`v25/.venv`, and `results/quickstart-v25`; the tracked solver, catalogue,
calibration, and example files remain untouched.

If a required Ubuntu utility is absent, `quickstart.sh` exits before downloading
anything and prints one `apt-get` command naming the missing package. A checksum,
dependency, or numerical demonstration failure exits nonzero and does not print
the success message.
