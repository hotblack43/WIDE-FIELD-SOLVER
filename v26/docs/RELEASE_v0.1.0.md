# v0.1.0 — preserved wide-field point-star solution

First standalone release of the working Barghini O/Z fish-eye solver.

- Independent source, frozen Tycho-2/bright-Hipparcos catalogue, Python 3.12
  environment and pinned tetra3 pattern bootstrap.
- Original untrailed Milky Way example and 40-star annotation with ordinary
  names, including an offline, fresh-from-pixels demo.
- Verified baseline: 3,688 detections, 3,653 fitted catalogue associations,
  0.397892-pixel RMS, zero withheld stars.
- Broad/saturated blob retention, synthetic checks and full-image regression CI.
- README, method/provenance notes, bounded solve-field comparison and future
  extensions including bright stars plus Gaia DR3/DR4.

This private release preserves the successful experiment. Image redistribution
rights are undocumented; consult NOTICE before any public release. Fitted
residuals are conditional on association selection and fitting, with no
independent accuracy claim.
