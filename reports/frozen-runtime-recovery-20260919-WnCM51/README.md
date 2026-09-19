# Preservation repair, 2026-09-19

The user requested resolution of seven preservation-test failures in the existing
checkout, without branches/worktrees or interference with the active v11 work.

## V9: restore the recorded frozen runtime

Four working files differed from `docs/v9-runtime.json`. Their committed versions
match that checkpoint exactly. This directory preserves complete pre-restoration
copies and `v9-working-edits.patch` before restoring those four files:

- `v9/SOURCE_MANIFEST.json`
- `v9/docs/FEATURE_STATUS.md`
- `v9/point_star_report.py`
- `v9/test_point_star_report.py`

The removed working changes report an unconfirmed single-planet candidate date
and uncertainty. That report feature and its regression test already exist in
v10. This repair restores v9's report behavior; it does not change astrometric
fits or saved coordinates. No edits were discarded: copies and the forward patch
remain here for inspection or intentional future porting. Do not blindly reapply
the patch to a frozen runtime.

## V10: check the actual captured parent, not an older commit

`docs/v10-runtime.json` already contains two independently recorded inventories:
the committed checkpoint and `working_tree_parent_snapshot`. The v11 execution
ledger explicitly records that the working parent was captured without changing
its three existing exposure-rate edits. Those current v10 files match the saved
working snapshot exactly. The failing test mistakenly used the committed map.

The repaired boundary test checks the complete working snapshot, requires equal
file inventories, and verifies that its differences from the committed inventory
are exactly the recorded dirty paths. A separate test verifies the committed
inventory against its named git commit. A synthetic regression proves that the
captured working bytes pass while later edits or an incomplete inventory fail.

Neither hash inventory was rewritten. No v10 runtime, v11 runtime, launcher,
solver result or database was changed. Historical exposure-normalization behavior
in v10 remains frozen; correcting its scientific behavior belongs to a later
solver version, not this preservation repair.

## Verification

- The two original failing boundary tests now pass (all seven discrepancies
  resolved).
- The synthetic snapshot-policy regression and committed-checkpoint verification
  pass.
- Direct SHA-256 audit: all 136 v9 files and all 139 captured working-v10 files
  match their unchanged preservation records.
- Full root unittest discovery: 254 tests, OK with one optional h5py dependency
  skip. The root demonstration also passed after repair; logs are
  `/tmp/wfs-preservation-final-tests.log` and
  `/tmp/wfs-preservation-demo.log`.
- Demo output: `results/check-preservation-20260919-WnCM51`; baseline passes with
  3653 associations, 0.397892 px RMS and 40 distributed labels.
- Independent read-only review found no blocking issues and confirmed that the
  recovery patch passes `git apply --check`. It independently reran all four
  targeted preservation/regression tests successfully.
