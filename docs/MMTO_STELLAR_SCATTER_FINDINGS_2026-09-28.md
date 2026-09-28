# MMTO stellar scatter findings, 28 September 2026

## Scope and status

This note records an inspection of the stellar ensemble scatter product from
the completed MMTO photometry run `20260928T170055Z`. It is an observational
diagnostic, not a claim that a physical cause has been identified. The
historical run and its products were not modified.

The inspected figure used in-sample residual standard deviation after
per-star polynomial detrending. The companion CSV also contains the
leave-one-out cross-validated root-mean-square error (LOOCV RMSE) used to select
the polynomial degree. Subsequent plotter changes described below affect new
outputs only.

## Source provenance

Repository-relative source files and SHA-256 digests:

| File | SHA-256 |
|---|---|
| `results/photometry-runs/20260928T170055Z/stellar-lightcurves/sd_vs_magnitude.pdf` | `80aa06ebeb43768092daf2d70329ce8715337d7bafe28ecb2209f8f31b600085` |
| `results/photometry-runs/20260928T170055Z/stellar-lightcurves/sd_vs_magnitude.csv` | `4b2607ee8cc7ba37b48af635c3f3bff97e334ffc210310b7626d9771f2bd55eb` |
| `results/photometry-runs/20260928T170055Z/stellar-lightcurves/summary.json` | `85a9c6117889a78e2094c2d563fe2f5f13e5cb98eebeb511627fa6b79d436f32` |
| `results/photometry-runs/20260928T170055Z/pipeline_summary.json` | `494f27a1b4b4e5a694ca7c04c0c9029bb4021461e614632aeb2c1baf0b0a2653` |

The run started at `2026-09-28T17:00:55Z` and finished at
`2026-09-28T17:21:13Z`. It used solver version `0.11.0`. All 1,196 verified
MMTO images already had v11 receipts, so this invocation processed no new
images and regenerated the downstream products from the saved database.

The plotted ensemble contains 19 qualifying instrumental-G series. Each has
448–589 usable measurements. Saturated or otherwise unusable channel
measurements had already been excluded by the light-curve quality rules.
Catalogue magnitude is heterogeneous: Gaia rows use Gaia G, while bright
supplement rows use Tycho VT or Hipparcos V.

## Numerical findings

Statistics below were calculated directly from every row of
`sd_vs_magnitude.csv`, without an additional cut.

| Population | N | Residual SD mean (mag) | LOOCV RMSE mean (mag) | LOOCV RMSE range (mag) | Selected degrees |
|---|---:|---:|---:|---:|---|
| All qualifying series | 19 | 0.465560 | 0.469497 | 0.264318–0.595324 | 0, 1, 4, 6 |
| First usable measurement 2026-03-15 | 6 | 0.355480 | 0.356194 | 0.264318–0.463996 | degree 0: 4; degree 1: 2 |
| First usable measurement 2026-08-19 | 13 | 0.516366 | 0.521791 | 0.448063–0.595324 | degree 4: 6; degree 6: 7 |

For the full sample, catalogue magnitude and scatter are strongly
anticorrelated:

- magnitude versus residual SD: Pearson `r = -0.852356`; Spearman
  `rho = -0.728070`;
- magnitude versus LOOCV RMSE: Pearson `r = -0.846951`; Spearman
  `rho = -0.728070`.

This is opposite the usual photon-noise expectation that fainter sources have
larger measurement scatter. The result must not be interpreted as evidence
that faint stars are intrinsically measured more precisely.

The first-observation cohorts are sharply separated. Their mean LOOCV RMSE
differs by about 0.166 mag, and polynomial degree is completely confounded with
cohort in this 19-star sample: the March cohort selects only degrees 0–1,
whereas the August cohort selects only degrees 4–6. The cohort separation is
therefore an important part of the apparent relation.

It is not the whole relation. Magnitude and LOOCV RMSE remain negatively
correlated within each cohort: Pearson `r = -0.940932` for the six March series
and `r = -0.630384` for the thirteen August series. The March estimate is based
on only six objects. Magnitude, observing window, sky position and selected
model complexity remain confounded, so these correlations are descriptive,
not causal.

The overall mean LOOCV RMSE exceeds mean in-sample residual SD by only about
0.00394 mag. Cross-validation therefore does not remove the broad 0.26–0.60 mag
scatter. The poor repeatability is not merely an artefact of reporting an
optimistic in-sample residual statistic.

## Interpretation and limitations

The figure is useful as evidence of a substantial systematic effect. It is not
yet a photometric noise curve. Plausible contributors that remain to be tested
include:

- observing-night transparency and cloud structure;
- airmass and colour-dependent extinction;
- detector position, vignetting and stellar sky track;
- bright-source response nonlinearity below the explicit saturation flag;
- the Gaia G versus Tycho VT/Hipparcos V passband mixture;
- genuine stellar variability;
- smooth temporal structure that drives the polynomial selection to its upper
  tested degrees.

Seven of nineteen series select the maximum allowed degree 6. This boundary
occupancy is a reason to inspect the residual time structure and candidate
cross-validation scores. It is not by itself a reason to raise the degree cap:
a higher cap could remove genuine variability or absorb unmodelled observing
systematics.

The sample contains only 19 stars, covers two distinct start-date cohorts and
does not independently vary magnitude, sky position, passband and observing
window. Any physical explanation is therefore provisional.

## Plotting change prompted by the inspection

Newly generated `sd_vs_magnitude.pdf` files retain the established filename but
now plot LOOCV RMSE rather than in-sample residual SD. They encode the UTC date
of the first usable measurement by colour, the selected polynomial degree by
marker shape, and the selected light-curve panel stars by orange rings. The axes
explicitly distinguish instrumental camera G from the heterogeneous stored
catalogue passbands. The companion CSV continues to retain both residual SD and
LOOCV RMSE.

This change does not alter measurements, fits, polynomial selection, numerical
residuals or the historical `20260928T170055Z` products. It changes only which
already-recorded statistic is plotted and makes the principal confounders
visible.

## Recommended follow-up

1. Plot per-measurement residuals and per-star scatter against airmass,
   altitude, detector radius and observing night, preserving cohort labels.
2. Separate Gaia G rows from Tycho VT/Hipparcos V supplement rows.
3. Compare scatter at fixed magnitude within overlapping sky-position and
   observing-window strata; the present cohorts have limited overlap.
4. Inspect the candidate LOOCV score curves and residual autocorrelation for
   the seven degree-6 series.
5. Compare raw, nightly-extinction-corrected and detector-position-corrected
   repeatability without changing sample membership.

These checks should precede any claim that source brightness itself causes the
observed inverse trend.
