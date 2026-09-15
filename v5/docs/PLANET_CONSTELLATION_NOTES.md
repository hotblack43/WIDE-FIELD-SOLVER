# Planet-constellation follow-up

## Motivation and observed failure

The circular Fred Espenak image
`FishEye18-1032w_Espenak.jpg` is a useful regression case. After the dark-frame
footprint was excluded, the unchanged v0.5.0 planet stage selected a conditional
two-body candidate at 2018-04-16T23:29:43.878 TDB:

- Jupiter at detection 6, with a 0.283-pixel residual;
- Saturn at detection 37, with a 0.375-pixel residual;
- Mars predicted beside a measured source but not admitted as a match.

The third source is detection 22 at `(118.6313, 584.6977)` pixels. The stellar
association stage assigned it to Gaia DR3 4080503709018054400 with a
1.126-pixel residual. The planet stage applies its catalogue-competition rule
before forming joint candidates:

```text
planet_gate_squared = star_residual_squared - 9 * positional_sigma_squared
```

Consequently, a catalogue residual below three positional sigmas makes the
source ineligible even if a planet would land exactly on it. This is appropriate
for rejecting isolated coincidences, but too strong when several planets form a
coherent constellation. A chance Gaia neighbour can veto one member before the
joint evidence is evaluated.

As a diagnostic only, detection 22 was allowed to challenge its Gaia label; no
date, site, filename, EXIF field or saved identity was supplied to the search.
The complete 1850-to-run-time search then found exactly one candidate containing
three planets:

| Planet | Detection | Residual (px) |
|---|---:|---:|
| Mars | 22 | 0.0996 |
| Jupiter | 6 | 0.4702 |
| Saturn | 37 | 0.3816 |

The common epoch is 2018-04-16T07:37:57.220 TDB and the three-source RMS is
0.3543 pixels. No competing three-planet epoch survived. Only after fixing that
blind diagnostic was the embedded timestamp inspected: it records
2018-04-16T04:55:31, independently confirming the recovered date. Metadata must
remain validation-only and must never seed or rank the blind result.

## Proposed constellation search

Catalogue association should remain an alternative explanation rather than an
irreversible per-source veto. Candidate generation can still use conservative
individual gates, but a joint stage should be able to add a catalogue-associated
source when doing so creates a stronger multi-planet solution. It should compare
the complete alternatives:

1. every selected source is explained by its stellar association;
2. one or more sources are reassigned to distinct planets at one common epoch;
3. unmatched planets are allowed, and no measured source can represent two
   planets.

Rank first by the amount of coherent evidence, then by a documented joint
objective. The objective should include the planet residuals and the cost of
displacing catalogue explanations. The present nine-sigma-squared rule can
remain useful for isolated one-body claims, but must not discard a source before
the multi-body likelihood is known. Any resulting confidence term needs a
look-elsewhere calibration across searched dates, planets and measured sources;
the number of matched bodies alone is not a false-alarm probability.

Pairwise angular separations provide an efficient, camera-orientation-independent
coarse index. For two planets, their angular distance sharply reduces candidate
epochs but can recur. For three or more planets, the set of side lengths plus an
oriented triangle or polygon removes many aliases. These invariants should be a
prefilter only. The final fit should use the original measured centroids and full
projected planet positions at one epoch, so correlated distance and angle terms
are not counted twice.

## Relative brightness evidence

Predicted relative brightness can help rank otherwise competitive identities.
JPL Horizons observer-table quantity 9 supplies approximate airless apparent
visual magnitude and surface brightness. A local, versioned cache or a validated
local implementation should be used so the normal solver stays offline and
reproducible; a live network response must not become an analysis dependency.

For the Espenak three-body diagnostic, the existing local model predicts this
ordering:

| Planet | Predicted V | Thresholded measured flux |
|---|---:|---:|
| Jupiter | -2.46 | 3065 |
| Mars | -0.06 | 999 |
| Saturn | +1.02 | 837 |

The ordering agrees, but the flux ratios must not be treated as calibrated
photometry. The JPEG response, saturation, sky background, fitted radial
response, atmospheric extinction and passband mismatch all matter. A safe first
use is a broad rank or censored likelihood:

- saturated measurements provide lower limits, not exact fluxes;
- compare relative brightness only after applying the fitted radial and
  extinction terms;
- attach generous model and camera-band uncertainty;
- use agreement as supporting evidence and strong, measurable contradictions as
  penalties, never as an unreported hard identity veto.

## Regression requirements

The implementation should add evidence for all of the following without
relaxing the astrometric thresholds:

- a planet superposed near a plausible Gaia star remains available to a coherent
  three-planet hypothesis;
- the Espenak sources recover the unique Mars/Jupiter/Saturn date without image
  metadata;
- two-planet aliases remain explicitly conditional when geometry does not make
  them unique;
- triangle indexing and the final full-position objective return the same
  physical candidate;
- brightness ordering can improve ranking but cannot erase an otherwise valid
  positional solution when photometry is saturated or uncalibrated;
- all alternative dates and identity changes remain available in CSV/JSON audit
  products;
- the concise report keeps the sky-position overlay and omits the crowded
  epoch-candidate appendix.

## Implemented presentation boundary

The search continues to save every positional passage, including one-planet
aliases. After candidate-specific absence checks, however, a result whose best
remaining candidate contains only one planet is now reported as
`planet_epoch_not_identifiable`. It has no selected epoch or selected planet
match, and unmatched planets are not projected at that arbitrary alias date.
The complete candidate list remains available for audit. This presentation
boundary does not implement the joint constellation scoring proposed above.
