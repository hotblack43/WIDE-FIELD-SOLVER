# Wide-Field Solver v0.11.0

This is the curated public v0.11.0 release of Wide-Field Solver by Peter Thejll
and Chris Flynn. It includes the required v11 solver code and data, pinned
dependency lockfile, launchers, rights documentation, and one built-in native
colour MMTO FITS example. It does not include result databases, caches, test
suites, historical solver versions, `goBIG`, or the historical Fred Espenak
photograph.

## Download and verify

Choose one archive—not GitHub's automatic “Source code” archives:

- `wide-field-solver-v0.11.0.tar.gz` for a tar archive; or
- `wide-field-solver-v0.11.0.zip` for a ZIP archive.

Do not download both. Verification is optional. To verify the archive you
chose, also download `SHA256SUMS` and run the matching command below.

For the tar archive:

```sh
grep 'wide-field-solver-v0.11.0.tar.gz$' SHA256SUMS | sha256sum -c -
tar -xzf wide-field-solver-v0.11.0.tar.gz
cd wide-field-solver-v0.11.0
```

For the ZIP archive, which contains the same files:

```sh
grep 'wide-field-solver-v0.11.0.zip$' SHA256SUMS | sha256sum -c -
unzip wide-field-solver-v0.11.0.zip
cd wide-field-solver-v0.11.0
```

## Quick start

Install [uv](https://docs.astral.sh/uv/) and use Bash. The first command may
need Internet access to download the pinned dependencies:

```sh
uv sync --project v11 --frozen
./demo.sh --output results/mmto-demo
```

The demonstration solve itself uses the included catalogue offline and
overwrites that explicitly named output directory on a rerun. To solve another
image:

```sh
./go11.sh /full/path/to/image.fits.bz2
```

## What is new

- A joint stellar/planetary epoch profile refits one Barghini camera using
  stellar proper motions and measured moving bodies, with conservative alias,
  visibility and catalogue-competition checks.
- Supplied observation timestamps remain validation information; they do not
  bound the global blind planet search or seed the blind stellar solution.
- Native colour FITS and compressed FITS inputs retain their detector values,
  and photometry records raw counts plus exposure-normalized count rates.
- The built-in MMTO regression demonstration converges with 1,409 associations,
  0.329 px RMS (2.543 arcmin), native R/G/B planes and no withheld stars.
- Release archives are built from a fail-closed allowlist and are reproducible,
  path-safe and independently checksummed.

Planet checks made at supplied metadata time are explicitly
**metadata-conditioned**; they are not described as blind epoch inference.

## Rights and credit

The project-authored software is Copyright (c) 2026 Peter Thejll and Chris
Flynn and is available under the BSD 3-Clause licence. Modification and
redistribution are permitted under its attribution and disclaimer conditions.

Required example credit: **MMTO all-sky-camera image courtesy of MMT
Observatory, provided with permission from Tim Pickering.** The BSD software
licence does not license the MMTO observation. No software-author copyright is
claimed over that observation.

Catalogue, scientific-model and dependency attributions are in `NOTICE.md`.
