# V11 joint epoch implementation

Spec: ../specs/2026-09-19-v11-joint-stellar-planet-epoch-design.md

Implement inline. User has approved implementation repeatedly; no further review
gate is pending. Preserve other windows' working-tree changes.

## Tasks

1. Create a self-contained v11 snapshot and separate launchers; record v10 hashes.
2. Test and implement full-range planet context, positive relative brightness,
   and common-camera/epoch profiles for distinct multi-body assignments.
3. Integrate conservative selection, consistent saved coordinates and explicit
   initial-versus-joint diagnostics. Never adopt ambiguous candidates.
4. Run synthetic/regression tests and a fresh MMTO solve; inspect and link the
   PDF and actual-position/profile comparison. Review the implementation.

## Global constraints

No existing runtime edits. No metadata-bounded search. No claimed joint date
from fewer than two distinct bodies/detections. Brightness is soft identity
evidence, never an astrometric displacement or sole alias discriminator.
Conditional intervals exclude unmodelled atmosphere/frame systematics.

## Verification

New behavior has failing tests before implementation. Run complete v11 and root
unittest discovery, root and v11 demos, manifest/launcher tests, then the MMTO
acceptance image. Preserve pre-existing failures rather than hiding them.

## Execution ledger

Ruling: Work directly in the new, independent v11 directory, with no edits to
existing runtime packages or shared index. This follows the user's explicit
version boundary and avoids another worktree handoff; cost is no git-level
isolation, mitigated by narrow file targets and preservation hashes.

Ruling: Snapshot the current v10 runtime, including its existing exposure-rate
fix, without committing or modifying another window's work. Record the exact
bytes and dirty parent provenance. The older spec's commit-first gate is
superseded by the user's instruction to proceed; the snapshot is not represented
as a committed release.

Task 1: complete. Independent package and launchers created; v10 bytes unchanged.

Task 2: complete. Synthetic two-body epoch/camera recovery, duplicate/single
rejection, metadata-independent bounds, relative brightness and saturation tests
pass. Initial full v11 suite: 348 tests, 1 skip, no failures.

Task 3: review fixes implemented. Common product authority, distinct initial and
coordinate epoch labels, controls preserved, recovery on staged-publication
failure. Candidate epochs and coordinates propagate together.

Ruling: Optional metadata-assisted acceleration is omitted; full blind global
search always runs. This avoids trusting metadata proposals; cost is runtime.

Ruling: Never compare different stellar-membership objective sums as evidence
against an alias. Retain different-membership peers conservatively; cost is more
ambiguous results until a common-evidence model is implemented.

Ruling: Fix the inherited exposure normalization caller in v11 only. It divided
already-normalized rates a second time. Pipeline regression: 3600 ADU / 2 s
gives -2.5 log10(1800). Parent v10 bytes remain untouched.

Final review: six important findings addressed; dedicated tests exercise
membership ambiguity, fixed/catalogue control preservation, recoverable
publication, regenerated product failure, shared FITS/PDF candidate identities,
joint epoch in identified photometry, and current coordinate epoch display.

Final: minor (deferred): adoption uses 40-label/offline defaults rather than
propagating custom label/cache options.

Ruling: Calibration of interval coverage, topocentric/frame corrections and
exhaustive joint global search remain limitations, not completed capabilities.
The cost is conditional timing rather than a precision dating claim. The final
review left preserved-version/full-suite verification to this main session.

Investigator correction: replace "unbounded" UI wording with the finite allowed
interval and labelled causal/search truncation; missing contour crossings do not
mean absent timing information.

Task 4: complete as a development handoff, not publication.

Final evidence:

- Full v11 unittest discovery: 351 tests, OK, 1 skip.
- Root discovery: 243 tests, four pre-existing v9 preservation subtest failures
  (`v9/SOURCE_MANIFEST.json`, `v9/docs/FEATURE_STATUS.md`,
  `v9/point_star_report.py`, `v9/test_point_star_report.py`); 1 skip. Those other
  window edits were not changed or hidden.
- Root demo: 3653 associations, RMS 0.397892 px, baseline PASS.
- V11 demo: 3611 associations, RMS 0.370165 px, baseline PASS.
- V11 version/manifest and v10 preservation boundary: 3 tests pass.
- Fresh integrated MMTO solve: 1128 global hypotheses, 32 joint multi-body
  profiles, no profile failures. Best candidate 13:04:23.755 UTC; conditional
  allowed interval 08:31:46.200 to run-start ceiling 16:05:24.834 UTC. Initial
  scientific camera retained because the interval is causally truncated and
  physical zenith remains unresolved.
- Report PDF and comparison PNG visually inspected. Header-clock validation was
  appended after numerical selection, without refitting: DATE-OBS versus DATE
  differs by seven hours plus exposure/readout. Raw timestamps are unmodified.
- Source, tests and manifests remain uncommitted; no other window's changes staged.

Final run:
`results/v11-final-20260919/runs/2026_09_19__05_00_17.fits-v0.11.0-20260919T160524Z-pJDF70/analysis/`
