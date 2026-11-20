# V25 Clean-Clone Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one `./quickstart.sh` command bootstrap and verify v25 from a clean Ubuntu 24.04 or 26.04 LTS x86-64 clone.

**Architecture:** A thin root launcher calls a sourceable v25 shell library. The library pins and verifies a repository-local `uv`, isolates its Python and cache state under `.tools`, performs a frozen v25 sync, runs the existing MMTO demonstration, and prints the verified report path. Unit tests replace sourceable shell functions; a two-version Docker CI matrix tests the real network and dependency path.

**Tech Stack:** Bash, uv 0.9.30, Python 3.12, `unittest`, GitHub Actions, Ubuntu Docker images

**Spec:** `docs/superpowers/specs/2026-11-20-v25-clean-clone-bootstrap-design.md`

## Global Constraints

- Certify Ubuntu 24.04 and Ubuntu 26.04 LTS on x86-64; Ubuntu 24.04 is the minimum baseline.
- Require only Bash, Git, CA certificates, `sha256sum`, `tar`, and either `curl` or `wget` before bootstrap.
- Do not use `sudo`, modify global Python state, modify shell startup files, or silently install operating-system packages.
- Pin `uv` to 0.9.30 and `uv-x86_64-unknown-linux-gnu.tar.gz` SHA-256 `8b3762374972daa7a74bbc6896cc73229ca69a07403dd9f9ea3805a51ffd7582`.
- Use `v25/uv.lock` with `--frozen`; do not add dependency fallbacks.
- Keep generated tools, Python, caches, environments, and results outside Git and release inventories.
- Preserve all frozen solver runtimes and existing launchers.
- Do not commit unless the user explicitly requests it.

## Review Focus

- A truncated or altered uv archive must fail checksum verification and never execute; Task 1 tests this.
- An inherited `VIRTUAL_ENV`, global uv, or global Python must not redirect bootstrap state; Task 1 tests exact local paths and environment variables.
- Missing `curl`/`wget`, CA support, `tar`, or `sha256sum` must produce one actionable Ubuntu package command before download; Task 1 tests each class.
- Ubuntu 24.04 and 26.04 must both resolve every pinned wheel and run the numerical demonstration from empty local state; Task 2 tests both real containers.
- A dependency or demonstration failure must propagate nonzero and must not print the success block; Task 1 tests both failures.

---

### Task 1: Repository-local bootstrap

**Files:**
- Create: `quickstart.sh`
- Create: `v25/scripts/quickstart.sh`
- Create: `v25/test_quickstart.py`
- Modify: `.gitignore`
- Modify: `test_v25_runtime_boundary.py`

**Interfaces:**
- Consumes: `v25/pyproject.toml`, `v25/uv.lock`, `v25/demo.sh`, and the bundled MMTO example.
- Produces: `quickstart_main REPOSITORY_ROOT [arguments...]`, plus sourceable shell functions `quickstart_platform`, `quickstart_requirements`, `quickstart_install_uv`, `quickstart_sync`, and `quickstart_demo` for isolated tests.
- Produces local state at `.tools/uv/0.9.30/uv`, `.tools/cache`, `.tools/python`, `v25/.venv`, and `results/quickstart-v25`.

- [ ] **Step 1: Write failing shell-boundary tests**

Add `QuickstartTests` in `v25/test_quickstart.py`. Run Bash subprocesses that source `v25/scripts/quickstart.sh`, override one named function at a time, and assert:

- Ubuntu `24.04` and `26.04` with `x86_64` are accepted;
- Ubuntu `22.04`, a non-Ubuntu ID, and `aarch64` are rejected before `quickstart_install_uv`;
- each missing prerequisite exits nonzero and names one `sudo apt-get install` remedy;
- the pinned archive constants equal the values in Global Constraints;
- checksum mismatch leaves no executable at the final path;
- `VIRTUAL_ENV` is cleared and `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, and `UV_PROJECT_ENVIRONMENT` resolve below the repository;
- sync or demo failure propagates nonzero without `Quick start complete`;
- success requires `results/quickstart-v25/report.pdf` and prints that path plus `./go25.sh /full/path/to/image.fits`;
- a second invocation reuses the existing verified uv executable without downloading again.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `cd v25 && uv run --frozen python -m unittest -v test_quickstart`

Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Implement the sourceable v25 bootstrap library**

In `v25/scripts/quickstart.sh`, define the interfaces above and call no main function while sourced. When executed through the root wrapper:

- read `/etc/os-release` and `uname -m`;
- accept only Ubuntu 24.04/26.04 and x86-64;
- validate prerequisites and required v25 assets before network access;
- download the pinned uv archive with `curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error` or the wget HTTPS equivalent;
- verify the hard-coded SHA-256 before extracting to a temporary directory;
- atomically install `uv` under `.tools/uv/0.9.30/uv` and verify `uv --version` on reuse;
- set the three local uv paths from Step 1 and unset `VIRTUAL_ENV`;
- run `uv sync --project v25 --frozen --python 3.12`;
- prepend the local uv directory to `PATH`, run `./v25/demo.sh --output results/quickstart-v25`, and require `report.pdf`;
- print the compact success block only after every step passes.

The root `quickstart.sh` resolves its own directory, sources the v25 library, and calls `quickstart_main` with that directory. Add `/.tools/` to `.gitignore` and `quickstart.sh` to `V25_ROOT_FILES` in `test_v25_runtime_boundary.py`.

- [ ] **Step 4: Run focused tests and boundary checks**

Run: `cd v25 && uv run --frozen python -m unittest -v test_quickstart`

Run: `uv run --frozen python -m unittest -v test_v25_runtime_boundary`

Expected: PASS.

- [ ] **Step 5: Inspect the task diff**

Run: `git diff --check && git diff -- quickstart.sh v25/scripts/quickstart.sh v25/test_quickstart.py .gitignore test_v25_runtime_boundary.py`

Expected: no whitespace errors; only Task 1 files changed.

### Task 2: Real Ubuntu 24.04 and 26.04 release gate

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `test_v25_documentation.py`

**Interfaces:**
- Consumes: `./quickstart.sh` from Task 1.
- Produces: GitHub Actions job `v25-clean-clone` with matrix key `image: ["ubuntu:24.04", "ubuntu:26.04"]`.

- [ ] **Step 1: Add failing workflow assertions**

Extend `test_ci_runs_v25_operator_and_boundary_checks` or add `test_ci_certifies_clean_clone_on_both_ubuntu_lts_versions`. Assert the workflow contains `v25-clean-clone`, `ubuntu:24.04`, `ubuntu:26.04`, `./quickstart.sh`, a second `./quickstart.sh`, and no `setup-uv` or `setup-python` inside that job block.

- [ ] **Step 2: Run the documentation test and confirm failure**

Run: `uv run --frozen python -m unittest -v test_v25_documentation`

Expected: FAIL because the clean-clone job is absent.

- [ ] **Step 3: Add the two-container clean-clone job**

Add `v25-clean-clone` to `.github/workflows/tests.yml`. Use an explicit matrix of `ubuntu:24.04` and `ubuntu:26.04`, run on a pinned Ubuntu host runner, and execute each matching container with the checked-out repository mounted writable. Inside each fresh container, install only Bash, Git, CA certificates, curl, coreutils, and tar; then run `./quickstart.sh` twice and require `results/quickstart-v25/report.pdf` after each run. Do not use Actions dependency caching, `setup-uv`, or `setup-python` in this job.

- [ ] **Step 4: Run workflow assertions**

Run: `uv run --frozen python -m unittest -v test_v25_documentation`

Expected: PASS.

- [ ] **Step 5: Exercise both containers locally when Docker is available**

Run the same Docker command recorded in the workflow once for `ubuntu:24.04` and once for `ubuntu:26.04` from separate clean temporary working copies.

Expected: both invocations reach `Quick start complete`, produce `report.pdf`, and pass a second invocation. If Docker is unavailable locally, record that GitHub CI remains the required external verification and do not claim the matrix passed.

### Task 3: New-user documentation and v25 provenance

**Files:**
- Modify: `test_v25_documentation.py`
- Modify: `README.md`
- Modify: `v25/README.md`
- Modify: `docs/QUICKSTART.md`
- Modify: `v25/HANDOFF.md`
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `v25/scripts/update_v25_manifest.py`
- Regenerate: `v25/SOURCE_MANIFEST.json`

**Interfaces:**
- Consumes: command, paths, supported systems, and failure behaviour from Tasks 1-2.
- Produces: one consistent public three-command quick start and a manifest hash for every changed v25 file.

- [ ] **Step 1: Write failing documentation assertions**

In `test_v25_documentation.py`, assert that the root README, v25 README, and `docs/QUICKSTART.md` all include `./quickstart.sh`, Ubuntu 24.04, Ubuntu 26.04, `results/quickstart-v25/report.pdf`, and the user-image command. Assert `./quickstart.sh` appears before manual `uv sync` and before advanced operator commands. Assert the handoff and feature-status records name the clean-clone gate as required before v25 publication.

- [ ] **Step 2: Run the documentation test and confirm failure**

Run: `uv run --frozen python -m unittest -v test_v25_documentation`

Expected: FAIL on the missing quick-start wording.

- [ ] **Step 3: Rewrite the public quick start and status wording**

Make the root README lead with clone, `cd`, and `./quickstart.sh`. In the v25 README and `docs/QUICKSTART.md`, state the two certified Ubuntu versions, internet and baseline utility requirements, repository-local generated paths, expected report, removal command, unsupported-platform scope, and one `go25.sh` example. Keep operator and scientific documentation intact after the concise first-run section. Add the clean-clone release gate to the handoff and feature-status records.

- [ ] **Step 4: Update v25 manifest provenance**

Add a concise clean-clone bootstrap entry to `CHANGES` in `v25/scripts/update_v25_manifest.py`, then run:

`uv run --project v25 --frozen python v25/scripts/update_v25_manifest.py`

Expected: `v25/SOURCE_MANIFEST.json` records updated hashes for the v25 README, handoff, bootstrap library, and its tests.

- [ ] **Step 5: Run documentation and manifest tests**

Run: `uv run --frozen python -m unittest -v test_v25_documentation test_v25_runtime_boundary`

Expected: PASS.

### Task 4: End-to-end verification

**Files:**
- Verify only; fix failures in their owning task files.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: evidence that the local runtime, preserved versions, numerical demo, and clean-clone path remain valid.

- [ ] **Step 1: Run focused v25 bootstrap and documentation tests**

Run: `cd v25 && uv run --frozen python -m unittest -v test_quickstart`

Run: `uv run --frozen python -m unittest -v test_v25_documentation test_v25_runtime_boundary`

Expected: PASS.

- [ ] **Step 2: Run the actual bootstrap from empty local state**

Move any task-created `.tools`, `v25/.venv`, and `results/quickstart-v25` aside into one temporary directory rather than deleting them. Run `./quickstart.sh`, verify `results/quickstart-v25/report.pdf`, then run `./quickstart.sh` again. Restore only pre-existing user state afterward.

Expected: both runs pass; the second reuses uv and the environment.

- [ ] **Step 3: Run both clean Ubuntu containers**

Run the Task 2 Docker matrix commands for Ubuntu 24.04 and 26.04.

Expected: both clean environments pass twice. If external network or Docker availability prevents this, report the exact blocker and leave publication blocked.

- [ ] **Step 4: Run required repository regressions**

Run: `uv run --frozen python -m unittest discover -v`

Run: `./demo.sh --output results/check-unique-name`

Run: `cd v25 && uv run --frozen python -m unittest discover -v`

Run: `./v25/demo.sh --output v25/results/check-clean-clone`

Expected: all commands PASS without relaxing numerical thresholds.

- [ ] **Step 5: Inspect final state**

Run: `git diff --check && git status --short && git diff --stat`

Expected: no generated tools, environments, caches, or results are tracked; only approved source, tests, CI, documentation, spec, and plan changes remain.
