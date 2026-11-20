# V25 clean-clone bootstrap design

**Date:** 2026-11-20

**Status:** Approved in conversation

## Intent

Make the v25 GitHub release usable by a new user on a clean Ubuntu 24.04 or
Ubuntu 26.04 LTS x86-64 machine. Ubuntu 24.04 is the minimum certified
baseline; Ubuntu 26.04 is tested as the newer LTS. After cloning the repository,
the user should run one command and obtain a verified solver report without
first diagnosing Python versions, virtual environments, missing packages,
catalogues, masks, or demonstration inputs.

The primary interface is:

```sh
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
./quickstart.sh
```

The bootstrap may require internet access. It must not require root access,
modify the user's global Python installation, or silently install system
packages.

## Goals

- Certify Ubuntu 24.04 and Ubuntu 26.04 LTS on x86-64, with Ubuntu 24.04 as the
  minimum supported baseline.
- Bootstrap a pinned `uv` executable inside the repository, then use the
  committed v25 lockfile to obtain the required Python 3.12 runtime and Python
  dependencies.
- Run the existing bundled v25 MMTO demonstration as the first successful
  analysis, using only release-controlled scientific data and configuration.
- Print the final report path and a short next command for analysing a user's
  own image.
- Detect unsupported systems and missing bootstrap utilities before starting a
  long dependency installation.
- Report one concrete remedy for each missing operating-system prerequisite.
- Test the documented clone-to-report path independently in clean Ubuntu 24.04
  and Ubuntu 26.04 environments before publication.
- Make repeated invocations safe and substantially faster by reusing the exact
  pinned local tools and environment.

## Non-goals

- Native Windows, macOS, ARM, and other Linux distributions are not certified
  by this release. They may work, but the documentation must label them as
  unverified.
- The bootstrap does not provide an offline first installation. The bundled
  demonstration itself remains offline after dependencies have been obtained.
- Docker is not the primary user interface.
- The script does not use `sudo`, modify shell startup files, create cron jobs,
  or install operating-system packages automatically.
- The quick start does not run the MMTO archive pipeline, which has separate
  acquisition and operational requirements.
- This design does not itself freeze or publish v25, nor does it build the
  optional Floorplan release asset.

## Anti-goals

The bootstrap is a failure if it passes only because the development machine or
CI runner already supplied `uv`, Python packages, catalogue data, calibration
files, or cached results. It is also a failure if it executes an unpinned remote
installer, falls back to unpinned dependency versions, changes global user
state, conceals a failed demonstration, or leaves the user with a traceback and
no actionable explanation.

## Approaches considered

### Selected: repository-local bootstrap

`quickstart.sh` downloads one pinned Linux x86-64 `uv` release archive, verifies
its recorded SHA-256 checksum, and installs the executable under an ignored
repository-local tools directory. It invokes that exact executable for every
subsequent step, even when another `uv` is present on `PATH`. It then performs a
frozen v25 environment sync and runs the existing v25 demonstration.

This approach directly exercises the interface a new user sees while retaining
the committed lockfile and current launcher structure.

### Rejected: require the user to install `uv`

Keeping `uv` as a documented prerequisite requires a separate installation
step and preserves the current early failure mode. It does not meet the
clone-and-run requirement.

### Rejected as the primary path: Docker image

A container could encapsulate the runtime, but Docker is a larger prerequisite
than the solver's current requirements and adds image, volume, permission, and
output-location concepts to the first run. A container may be added later as a
supplementary distribution.

## Bootstrap behaviour

The script resolves the repository from its own location and runs correctly
from any current working directory. Before downloading anything, it checks:

1. the operating system identifies as Ubuntu 24.04 or Ubuntu 26.04;
2. the machine architecture is x86-64;
3. Bash, Git, CA certificates, `sha256sum`, and either `curl` or `wget` are
   available;
4. the committed v25 project, lockfile, demonstration, catalogue, mask, and
   demonstration input exist.

An absent fetch utility or CA certificate support produces one exact Ubuntu
package-installation command and exits without changing the machine. An
unsupported platform reports both certified targets and exits unless a later
explicit developer-only override is introduced.

The script downloads the selected `uv` archive to a temporary file, verifies
its hard-coded checksum before extraction, and atomically places the executable
under a versioned local path such as `.tools/uv/<version>/uv`. A partial or
checksum-invalid download is never executed. The exact `uv` version and archive
checksum are reviewed release inputs.

The script prepends the local tool directory to `PATH`, clears inherited Python
virtual-environment variables that could redirect installation, and runs the
equivalent of:

```sh
uv sync --project v25 --frozen --python 3.12
./v25/demo.sh --output results/quickstart-v25
```

The actual implementation passes the repository-local `uv` through to nested
launchers so the demonstration cannot accidentally use a global executable.
The demonstration must retain its existing scientific baseline checks. A zero
exit status means the environment was created and the demonstration passed.

On success, the final console block names the generated PDF report and gives
one example using `./go25.sh` with a user-supplied image. On failure, the script
names the failed stage, preserves the useful command output, and exits nonzero.
It never describes a dependency installation as a successful solver run.

## Clean-machine verification

Add a dedicated two-version release-gate matrix using the explicit Ubuntu 24.04
and Ubuntu 26.04 x86-64 images, not the moving `ubuntu-latest` label. Each job
must start without a repository virtual environment or dependency cache and
invoke the public sequence:

```sh
git clone <candidate repository>
cd WIDE-FIELD-SOLVER
./quickstart.sh
```

Where the CI service itself performs checkout, each matrix entry must otherwise
isolate the working copy in a minimal container of the matching Ubuntu version
and install only the declared baseline utilities needed to perform a Git clone
and HTTPS download. The jobs must not use `setup-uv`, `setup-python`, or a
dependency cache.

The job verifies the demonstration exit status, expected report, numerical
baseline receipt, and console-reported output path. A second invocation verifies
idempotent reuse of the local tool and environment. Separate tests cover
unsupported architecture, missing fetch utility, checksum mismatch, interrupted
download, dependency failure, and demonstration failure.

## Documentation and release boundary

The root README begins with the three-command clone-and-run sequence. The v25
README explains the two certified Ubuntu versions, Ubuntu 24.04 as the minimum
baseline, the internet requirement, local tool and environment locations,
expected download size where known, generated report, and removal procedure.
`docs/QUICKSTART.md` must be updated from its older v15 instructions to the v25
interface.

Generated tools, environments, and quick-start results remain ignored and are
excluded from Git and release archives. The v25 source manifest records the new
tracked launcher, tests, and documentation. The curated v25 release assets must
contain every catalogue, calibration artifact, demonstration input, baseline,
and script required by `quickstart.sh`.

V25 is not ready to publish until both this clean-machine gate and the separate
normal-pipeline visible-sky integration gate pass. The optional Floorplan HTML
may then be generated from the exact frozen release tree, checksummed, and
uploaded as a separate documentation asset.

## Acceptance criteria

The design is implemented when all of the following hold:

- clean Ubuntu 24.04 and Ubuntu 26.04 LTS x86-64 machines with Git, Bash, HTTPS
  certificates, and one supported fetch utility each reach a passing v25
  demonstration through `./quickstart.sh`;
- the bootstrap uses a checksum-verified repository-local `uv` and the frozen
  v25 lockfile without relying on global Python or `uv` state;
- the first run prints the actual investigator-facing PDF path;
- missing prerequisites and unsupported platforms fail before dependency setup
  with a single actionable remedy;
- clean-machine CI runs the same public command on both certified Ubuntu
  versions without preinstalled Python or `uv`, then verifies an idempotent
  second run on each;
- the documented commands agree across the root README, v25 README, and quick
  start guide;
- existing preserved runtimes and launchers remain unchanged; and
- publication remains blocked while either the clean-clone gate or the v25
  visible-sky pipeline-integration gate is failing.
