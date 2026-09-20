# Wide-field solver v0.11.0 release design

**Date:** 2026-09-20

**Status:** Approved conversational design; implementation awaits written-spec review

**Release:** `v0.11.0`

## Purpose

Publish a compact, self-contained GitHub release of the v11 wide-field solver.
The release must be useful to someone who downloads only a release asset: it
must contain the required runtime, a real colour-FITS example that works
offline, a clear README, licensing and provenance notices, and integrity
checksums. It must not expose the repository's old versions, local observing
archive, databases, generated results, caches, or development material.

The release preserves the scientific contract in `GOAL.md`. In particular,
the example must be solved blindly: observing time and site metadata may be
used only for separately labelled validation after fitted results are fixed.

## Rights and attribution

Project-authored software is copyright © 2026 Peter Andreas Thejll and Chris
Flynn and remains under the repository's existing BSD 3-Clause License. This
permits use, modification, and redistribution while requiring preservation of
the copyright and licence notices. It also prevents downstream distributors
from using the authors' names to imply endorsement.

The bundled example will be an MMTO all-sky-camera exposure, used with Tim
Pickering's permission. Its credit will read:

> MMTO all-sky-camera image courtesy of MMT Observatory, provided with
> permission from Tim Pickering.

The fitted solution and project-authored annotations will be credited to Peter
Andreas Thejll and Chris Flynn. The software licence will not be presented as a
licence for the MMTO observation. `NOTICE.md` will distinguish software,
observational data, catalogues, ephemerides, dependencies, and their respective
terms.

Fred Espenak's photographs will not be distributed in the release assets.
Where the README discusses the separate Espenak analysis, it may link to the
publisher's page and credit Fred Espenak, without copying the photograph or
claiming rights in it. The historical `examples/milky_way/` evidence remains
unchanged in the repository but its unidentified input photograph is excluded
from the downloadable release.

## Release contents

The public release will contain three uploaded assets:

- `wide-field-solver-v0.11.0.tar.gz`
- `wide-field-solver-v0.11.0.zip`
- `SHA256SUMS`

Each archive will have one top-level `wide-field-solver-v0.11.0/` directory.
Its curated contents will be:

- a standalone `README.md`, `LICENSE`, and `NOTICE.md`;
- `go11.sh` and `go_v0.11.0.sh` launchers;
- the v11 runtime Python modules, shell entry points, `pyproject.toml`,
  `.python-version`, and committed `uv.lock`;
- only the catalogue, display-name, and planet/minor-planet reference data
  required by the runtime;
- the demo runner and baseline checker;
- one compressed native-colour MMTO FITS input and a compact numerical
  baseline for validating its solution.

The package will not contain tests, prior solver versions, developer plans,
historical reports, databases, run directories, generated plots, Python
caches, virtual environments, the bulk MMTO archive, or the historical
unidentified Milky Way photograph.

## Built-in MMTO example

The selected example is
`2026_09_19__02_20_01.fits.bz2`, SHA-256
`d7278337c18a87e19b4254dbd053769cc10233732f1ce686a44b235a567fa960`.
It is approximately 6.1 MB compressed and contains native R, G, and B FITS
planes with a recorded 20-second integration. An existing v11 run converged
blindly on this exposure, making it a suitable real-data acceptance case.

The repository will gain a dedicated v11 MMTO example directory rather than
repurposing or deleting the historical Milky Way example. The packaged
`demo.sh` will solve the MMTO input offline into a user-selected output
directory, then compare stable scientific quantities with the committed
baseline. The acceptance check will use scientifically meaningful tolerances
and will not be weakened merely to make release validation pass.

The baseline will check convergence, source identity, channel preservation,
the minimum association quality established by the reference run, fitted
camera quantities that are stable enough for regression testing, and relevant
blindness/provenance fields. It will not treat FITS site/time metadata as a
blind fitted result.

## Documentation

The release README will be written for a new user and will cover:

1. what v0.11.0 does and what it does not infer;
2. Unix-shell, Python, and `uv` requirements;
3. unpacking and running the built-in MMTO demo;
4. solving a user-supplied JPEG, PNG, TIFF, raw-camera file, compressed FITS,
   or FITS image;
5. the principal output products and where to find them;
6. the distinction between blind stellar fitting and metadata-conditioned
   validation;
7. catalogue, MMT Observatory, Tim Pickering, Peter Thejll, Chris Flynn, and
   Fred Espenak credits where applicable;
8. BSD 3-Clause reuse terms, third-party-material boundaries, citation, and
   warranty disclaimer;
9. the release's known scientific and operational limitations.

Commands in the README must be executable from a clean extracted archive and
must name v11 rather than inherited v10 commands.

## Release construction

A tracked release builder will use an explicit allowlist rather than copying
the repository and deleting unwanted paths afterward. It will stage files in a
single system temporary directory, normalize archive metadata where practical,
create the tar and ZIP assets, emit `SHA256SUMS`, and verify the asset inventory.
The temporary staging directory will be removed automatically after upload or
after a failure. Release archives will not remain as untracked repository
clutter.

The builder must fail closed when:

- an allowlisted source is missing;
- a staged file falls outside the expected inventory;
- a forbidden suffix or directory is present;
- an archive does not contain exactly one correctly named top-level directory;
- generated checksums do not verify.

The repository will record the exact released v11 runtime hashes in
`docs/v11-runtime.json`. `v11/SOURCE_MANIFEST.json` will identify v0.11.0 as a
release rather than development, describe the MMTO release example, and contain
hashes consistent with the released runtime. Root documentation will identify
v0.11.0 as the latest packaged release without altering any preserved older
runtime.

## Verification

Before the release commit or tag, run all mandated and release-specific checks:

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/check-unique-name
cd v11 && uv run --frozen python -m unittest discover -v
```

Then build both assets. Extract each into separate fresh temporary directories,
verify `SHA256SUMS`, and from each extracted archive run:

```sh
./demo.sh --output results/release-demo
./go11.sh --version
./go_v0.11.0.sh --version
```

The release checks must also prove that prohibited files are absent and that
the demo uses the bundled MMTO input without network access. A failure at any
stage stops publication.

## Publication flow

After verification:

1. commit and push the release preparation on `main`;
2. create annotated tag `v0.11.0` at the verified release commit and push it;
3. create the GitHub release named **Wide-field solver v0.11.0** as a draft;
4. upload the tar archive, ZIP archive, and `SHA256SUMS`;
5. independently download or inspect the published assets, confirm filenames,
   sizes, checksums, and release notes;
6. publish the draft and confirm the public release URL;
7. remove local temporary staging and downloaded verification files.

The release notes will lead users to the curated assets rather than GitHub's
automatic full-repository source archives. They will summarize v11's joint
stellar/planetary epoch work, centre-zenith convention, lossless database
deduplication, supported inputs, example provenance, licence, and limitations
without overstating blind epoch or zenith inference.

## Acceptance criteria

The work is complete only when:

- `v0.11.0` is a public Git tag and GitHub release;
- all three curated assets are publicly downloadable and checksum-valid;
- both clean archive formats run the MMTO demo offline and pass its baseline;
- Peter Andreas Thejll and Chris Flynn are clearly identified as the software
  authors and copyright holders;
- MMT Observatory and Tim Pickering receive the agreed example credit;
- no third-party photograph with uncertain or restricted redistribution rights
  is present;
- no old solver, local archive, database, result, cache, or development-only
  material appears in the release package;
- preserved historical runtimes and evidence remain unchanged in the
  repository; and
- the repository working tree is clean after publication.
