# Preserved local v6 development code

This is a backup on **main**, not a new branch, release or runtime change.
The investigator requested preservation of local code not already on GitHub,
without overwriting the published solvers. The accompanying patch preserves
12 locally modified files from the old `v6-release-fixes` development checkout:
planet ephemeris/refinement/search code, its benchmark script and regression
tests, associated documentation, benchmark evidence and source manifest.

[Complete recoverable patch](v6-local-development-20260919.patch)

- Base commit: `e119bc87800ff6c91d41d3f2e4e75ff848639d95`.
- Exact resulting Git tree: `cff28cbe4889a3418b831fb0d499419cec850e9c`.
- The patch is the complete difference from that historical base, not a patch
  intended for current main. Files unchanged from the base are already in Git
  history and are not duplicated here.

Recovery was verified by applying this patch to an isolated index of the base
and checking the resulting tree checksum. Keep this as historical development
evidence: **do not apply it over current main or the frozen v6 runtime**.
Neither the original development checkout nor any published runtime was changed.

Downloaded observations, live local databases, generated scratch outputs and
the empty local `goBIG` were excluded. In particular, the working script already
on GitHub is not replaced by that empty file.
