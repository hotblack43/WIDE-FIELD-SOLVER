# Blind photometric zenith implementation

User-approved method and no-metadata constraint: see ../specs/2026-09-14-blind-photometric-zenith.md.
Proper-motion work is checkpointed at 0833bee. Continue inline in the isolated worktree.

- [x] Add synthetic physical zenith/photometry tests; implement point_star_zenith.py.
- [x] Add metadata-independence test at photometry boundary; replace the fixed site/time airmass path with the blind fit, preserving all photometry rows/flags.
- [x] Export zenith objective plot and regression products, conditional/provisional status and report description. Default planetary metadata diagnostics off; preserve them explicitly opt-in.
- [x] Check the full suite, unchanged historical demo and fresh blind scientific report, then commit separately from 0833bee.

Final evidence: 63 unit tests passed; historical demo passed with 3653 matches
and 0.397892 px RMS; fresh blind analysis completed at
`results/check-v03-final-blind`, with conditional stellar epoch and explicitly
provisional photometric zenith. Code review checked numerical degeneracies,
metadata isolation, fixed membership and consistency of plotted regressions.
The scientific contract is also committed in the original checkout (036cf2e).
