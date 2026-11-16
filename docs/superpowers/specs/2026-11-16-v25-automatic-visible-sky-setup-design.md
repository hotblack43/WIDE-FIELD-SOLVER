# V25 automatic visible-sky setup design

## Intent

Make the generalized v25 camera-mask workflow practical for one operator to run
without copying configuration, proposal paths, hashes, mask identifiers, or
registry commands. One command should discover sufficiently populated cameras
from the managed archive, then create, validate, accept, register, and activate
a mask. The command must stop without activation
when the available images do not independently support the generated boundary.

The requested interface is:

```sh
./go_visible_sky_v25.sh
```

Source and camera IDs come from verified manifest rows. The automatic
installation ID is derived deterministically from those managed IDs, and the
orientation is the native decoded-array convention. Physical movement or crop
changes produce new immutable mask evidence. A strict TOML file remains an
advanced override for external archives or an operator-chosen installation ID.

## Goals

- Perform cold-start proposal, independent validation, acceptance, registration,
  and activation in one command.
- Use only checksum-verified native originals recorded in the managed download
  manifest.
- Reserve complete observing dates before proposal generation and keep the
  held-out images out of the proposal.
- Require reproducibility across date folds, not merely success on the images
  used to construct the mask.
- Record automated acceptance honestly and separately from human visual review.
- Preserve every proposal, diagnostic image, validation table, failure reason,
  acceptance receipt, approved mask, registry record, and activation record.
- Keep the existing manual `propose`, `revise`, `approve`, and `activate`
  commands unchanged.
- Never modify or delete archived originals, previous proposals, masks,
  registry history, assignments, or solver receipts.

## Non-goals

- Do not claim that automated validation is equivalent to visual inspection.
- Do not infer source or camera identity from filenames or pixels; use the
  managed manifest. Do not infer detector orientation from scene content.
- Do not automatically correct a failed proposal or weaken a threshold.
- Do not reassign historical downloads when a new installation is activated.
- Do not replace the accepted MMTO mask or alter frozen v24.
- Do not publish a tag or GitHub release as part of this change.

## Anti-goals

The feature is a failure if it can activate an all-visible, all-excluded,
unstable, mixed-detector, unsealed, tampered, or insufficiently tested mask. It
is also a failure if an automatically accepted mask is recorded as having been
visually approved by Peter or another person.

## Approaches considered

### Selected: measured automatic acceptance

Build a sealed cold-start proposal, audit untouched dates, measure stability
across date folds, and activate only after fixed conservative gates pass. This
is the only approach that supplies the requested one-command operation while
retaining an evidence-based fail-closed boundary.

### Rejected: unconditional automatic activation

Generate a mask and activate it regardless of the evidence. This is shorter,
but a pathological proposal could silently exclude real stars or admit fixed
foreground detections. It was rejected even though it is mechanically simple.

### Rejected: automatic proposal with a mandatory visual pause

Automate all paths and hashes but still wait for human approval. This preserves
the strongest review boundary, but it does not meet the explicit request that
everything be automatic.

## Command and orchestration

Add an `auto` subcommand to `v25/visible_sky_operator.py` and expose it through
the existing `go_visible_sky_v25.sh` launcher. With no arguments, the operator
uses the repository source registry, manifest, and archive. For an uncalibrated
camera with an explicitly enabled public RAW adapter, it requests at most ten
recent completed nights and ten originals per night before evaluating the
count gates. Acquisition and calibration can therefore complete in one
invocation, while an undersupplied archive reports `ACQUIRING` and resumes on a
later invocation. It automatically selects populations that meet the count
gates and do not already have a registered approved mask. Archive growth alone
never invalidates an installation mask. `auto
--config` loads the existing strict TOML
schema as an advanced override and resolves every path relative to that file.

Each invocation creates a new immutable run directory below:

```text
<review_root>/<installation_id>/auto-<UTC timestamp>/
```

It refuses a path collision. The run writes `automatic_run.json` immediately
with status `running`, exact configuration values, v25 version, code hashes,
and source manifest identity. It updates the receipt atomically to `failed` or
`activated`; interrupted runs remain visibly incomplete and are never treated
as accepted.

The stages are:

1. Select checksum-verified sources and require one detector signature.
2. Split by complete observation date before reading proposal pixels.
3. Create and seal the primary proposal using calibration dates only.
4. Audit every held-out original with the production detector.
5. Construct additional date-fold proposals for stability testing.
6. Evaluate the fixed automatic gates.
7. If any gate fails, write the receipt and stop without approval,
   registration, or activation.
8. If all gates pass, finalize the primary draft with the existing five-pixel
   inward safety margin.
9. Write an approved production manifest whose review provenance explicitly
   says `approval_mode: automated_validation` and whose actor is
   `wide-field-solver-v25-auto`.
10. Register the exact mask and activate the installation using the existing
    append-only registry functions.
11. Write the final receipt with the production manifest path, mask checksum,
    registry line, activation line, metrics, thresholds, and artifact hashes.

The automatic acceptance evidence is split into two records. The run-local
`automatic_run.json` may contain timestamps and absolute inspection paths. A
canonical `automatic_acceptance.json` contains no timestamps or absolute paths;
it is determined only by configuration identity, source checksums, code hashes,
thresholds, and measured results. On acceptance it is copied beneath
`<calibration_root>/automatic-acceptance/<installation_id>/` using its SHA-256
as the filename. The production manifest references that canonical relative
path and hash, never the run-local path.

The automatic mask ID is deterministic rather than timestamp-derived and binds
both the finalized pixels and their acceptance evidence:

```text
<installation_id>-auto-<mask SHA-256 first 12>-<acceptance SHA-256 first 12>
```

Repeating the same accepted calibration is therefore idempotent at the registry
boundary. Changed mask pixels or changed acceptance evidence necessarily
receive a different ID and cannot conflict with the first production manifest.

Only one automatic run for a given calibration root, source, and camera may run
at a time. The command acquires an exclusive advisory lock at
`<calibration_root>/.auto-<safe source>-<safe camera>.lock` before creating its
run directory and holds it through the final receipt and activation. A second
process exits without generating or registering anything.

If no installation is active, or the configured installation is already active,
successful validation proceeds automatically. If a different installation is
active for the same source/camera, the command stops before proposal generation
unless the operator supplied `--replace-active`. With that explicit flag the
same one command performs validation and switches activation only after all
gates pass. Historical checksum assignments remain unchanged.

## Fixed automatic gates

Automatic validation has no pre-existing approved mask for a new camera, so it
must not reuse the MMTO reference-comparison receipt or claim cross-camera
accuracy. It instead checks data sufficiency, mask sanity, held-out behavior,
and resampling stability.

The initial fixed gates are deliberately conservative and versioned in code:

- at least 10 distinct observing dates in total;
- at least 8 calibration dates and 2 held-out dates;
- at least 20 held-out originals;
- one exact detector signature across every selected and held-out original;
- proposal visible fraction between 0.10 and 0.95;
- finite proposal metrics and a nonempty single connected visible component;
- median held-out image-footprint IoU with the proposal at least 0.80;
- minimum held-out image-footprint IoU at least 0.50;
- at least 100 held-out unmasked detections in aggregate;
- held-out source supports intersecting the boundary at most 0.05 of all
  unmasked detections;
- five leave-one-date-fold proposal comparisons, each with mask IoU at least
  0.95 against the primary proposal;
- fold/primary symmetric mean boundary separation at most 10 pixels; and
- fold/primary symmetric p95 boundary separation at most 24 pixels.

All ratios use explicit integer numerators and denominators in the receipt.
Boolean values, missing values, zero denominators, NaN, and infinity are fatal.
Thresholds are constants covered by regression tests and cannot be changed by
the TOML file or command line. Later scientific adjustment requires a new
version and documented evidence; it must not silently change v25 acceptance.

The fold test uses deterministic date ordering. Each fold omits a different
fifth of calibration dates, cycles early/middle/late-night representative
selection as the current proposal does, and never reads the held-out dates.
Every fold mask and comparison JSON remains in the run directory.

## Provenance and scientific wording

Extend production-mask review provenance with:

```json
{
  "approval_mode": "automated_validation",
  "approved_by": "wide-field-solver-v25-auto",
  "automatic_acceptance_receipt": ".../automatic_acceptance.json"
}
```

Manual approval continues to write `approval_mode: human_review`. Existing
manifests without this new field remain readable as historical human-review
manifests; the loader does not reinterpret or rewrite them.

`automatic_acceptance.json` receives its own schema. It contains the fixed
threshold dictionary, measured metrics, pass/fail result for every gate,
proposal seal hash, source checksums, date split, fold artifact hashes,
point-source audit hash, finalized mask hash, code hashes, and v25 source
manifest hash. It never contains `visual_review: accepted`.

Console output is compact: stage name and progress, followed by either one
`ACTIVATED` line naming the manifest and inspection figure, or one `NOT
ACTIVATED` line naming the failed gates and receipt. Full per-frame evidence
goes to files.

Exit status zero means the configured installation is active at command
completion. A completed scientific validation that fails one or more gates exits
one. Argument or configuration errors exit two. Operational failures after
argument validation exit three. Callers never need to parse a receipt to know
whether activation succeeded, although the receipt remains authoritative detail.

## Error handling and repeatability

- Validate the complete config, manifest, archive root, identifiers, and
  detector signatures before creating a production mask.
- Proposal and fold directories are immutable.
- Write JSON receipts through a sibling temporary file followed by atomic
  replacement.
- Approval/registration/activation occur only after all evidence is written and
  re-hashed.
- A failure after registration but before activation leaves a registered but
  inactive mask and records that exact partial state; rerunning can complete
  idempotently.
- A failure after activation is reported as activated and must never be rolled
  back automatically.
- Existing active installations and historical checksum assignments are never
  edited in place; activation remains append-only.

## Code and documentation changes

- Add the `auto` command and orchestration to `v25/visible_sky_operator.py`.
- Add reusable automatic-gate and fold-comparison functions under v25 rather
  than importing another version.
- Extend `v25/visible_sky_calibration.py` to record explicit approval mode while
  preserving manual defaults.
- Reuse cold-start sealing, held-out audit, mask comparison, approval,
  registration, and activation functions instead of duplicating them.
- Extend `v25/test_visible_sky_operator.py` and calibration/cold-start tests for
  success, every failed gate, tampering, partial failures, idempotency, and the
  absence of activation on failure.
- Update the example TOML comments, v25 README, root README, feature status,
  source manifest, and CI job with the one-command workflow and its limitations.
- Keep v24 files and `docs/v24-runtime.json` byte-identical.

## Verification

Required focused evidence:

- TDD tests for config resolution and exact stage order.
- A synthetic multi-date successful auto run that produces an automated receipt,
  production mask, registry record, and activation record.
- Separate failure tests for every fixed gate proving registry bytes do not
  change.
- Tamper tests for proposal seal, fold evidence, held-out sources, receipt, and
  finalized mask.
- Existing manual lifecycle tests unchanged and passing.
- Existing v24 snapshot and v25 package-boundary tests passing.
- `./go_visible_sky_v25.sh auto --help` from outside the repository with a
  deliberately wrong inherited virtual environment.
- The exact root unit-test command and both preserved root and v25 demos.

The existing MMTO accepted mask remains the production MMTO mask. The automatic
path is tested on synthetic fixtures and may be exercised on MMTO read-only as
an additional reproducibility check, but it must not activate a replacement
MMTO installation during verification.
