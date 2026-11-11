# Nested radial Barghini comparison

V12 provides an experimental batch study for deciding whether residual
radius-dependent structure earns extra plate parameters. It does not change the
ordinary blind solver, which continues to use the inherited eight-parameter
Barghini camera.

Run the study against one or more saved-solution trees and the exact catalogues
that those solutions record by SHA-256:

```sh
cd v12
uv run --frozen python scripts/compare_radial_models.py \
  /path/to/results /path/to/other-results \
  --catalogue data/stars_gaia_dr3_g75.csv \
  --catalogue data/stars_tycho2_mag75.csv \
  --output /path/to/radial-model-study \
  --workers 4 --max-order 5 --fold-count 8 --seed 20260924
```

For each unique image checksum, `M0` refits the current eight camera parameters.
`M1` through `M5` add one angular coefficient at a time for normalized odd
powers `rho^3` through `rho^11`. All models use the same saved stellar
associations. The Gaussian tangent-coordinate RSS is the fitted likelihood used
by AIC, AICc, and BIC; with `N` stars, the observation count is `2N`, the
camera has `8 + q` fitted parameters, and the criteria count one additional
fitted Gaussian variance parameter (`K = 9 + q`). A model needs delta AICc at most -10, an improved
BIC, improved spatially blocked validation, and a bootstrap upper confidence
limit below zero to be called supported.

Eight deterministic folds form two radial bands with four contiguous angular
blocks in each band. Each holdout is therefore a complete annular wedge. They
are a prediction diagnostic only: the final comparison fits use all fixed
associations. Fold refits are run for `M0` and for extensions that first pass
the necessary delta-AICc/BIC gate; the remaining fold rows explicitly record
`penalised_criteria_not_supported`, because no held-out result could make those
orders selectable. After selection, separate soft-L1 fits of `M0` and the
selected order test whether the result also helps the solver's operational
robust objective.

The radial derivative must remain positive over the complete rectangular
detector. The antipode/unique-sky-domain check uses the largest fitted-source
radius, rather than unused black detector corners outside the illuminated lens
circle. Inverse projection separately verifies monotonicity and brackets every
requested target. This distinction was required by real 1411x1422 data whose
fitted field ends at 675 px (1.582 rad) while an unused 1006 px corner maps to
3.153 rad.

The serialized `monotonic_on_detector` convenience boolean currently reflects
the combined full-corner validation, so it can be false solely because an
unused corner crosses the antipode. Fit validity uses the separate derivative
and active-radius checks described above; consult the detailed validation
reason rather than interpreting that boolean alone.

The association-yield stage keeps the source detections, catalogue bytes,
proper-motion epoch, and angular gate fixed. A `gained` row is an
already-detected source that becomes mutually associated; it is not a newly
detected image object. Lost matches and changed catalogue identities are
reported separately. Major-planet and Ceres/Vesta rows likewise keep the
detection, identity, and epoch fixed while comparing only the two camera
projections. They do not redo blind planet identification or epoch inference.

Every discovered result remains in `solution_inventory.csv`.
`operational_comparison.csv` retains the historical saved RMS plus both robust
cameras, radial coefficients, RMS values, and failure states. Fit, rank,
monotonicity, inversion, sample-size, input, and per-image execution failures
remain visible in the model and fold products. The JSON file records the same
evidence and configuration; `summary.md` and the PNGs are derived views. Camera
groups are cluster-bootstrapped so sequential images are not presented as
independent instruments.

The experiment alone does not promote an extended model to the normal solver.
That would require a separate documented decision after the full historical
batch evidence is reviewed.

## Corrected historical result, 24 September 2026

The first 432-image run was superseded after review found obsolete gate lookup,
default substitution for missing gate provenance, interleaved rather than
genuinely blocked validation, and omission of the fitted Gaussian variance from
the information-criterion parameter count. Its numerical conclusions are not
evidence.

The corrected run analyzed all 432 unique images and selected an extension for
51 (11.8%); 381 retained `M0`. Selected extensions improved ordinary fitted RMS
by a median 7.49% and held-out annular-wedge RMS by 0.2136 arcmin. The
source-group bootstrap 95% interval for the median held-out change was -0.7365
to -0.2027 arcmin. Support is concentrated in the main MMTO family (44/221);
only 1/111 APICAM images and no Subaru or Zenodo images selected an extension.

On 49 extension images with successful robust reassociation, the unchanged
detection lists gained 681 and lost 84 stellar associations. The outer
populated annulus contributed 648 gains and 54 losses, so extra terms can make
already-detected edge stars acceptable without detecting new objects. Fixed
planet candidates behaved oppositely: 8,709 residuals improved and 10,002
worsened, with 44 gate entries versus 341 exits. See
[radial-model-study/README.md](radial-model-study/README.md) for failure modes,
missing-gate counts, and the independent audit.
