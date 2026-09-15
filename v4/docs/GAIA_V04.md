# Version 0.4.0: Gaia / Tycho same-image experiment

This version adds Gaia as an explicit alternative to the refinement and stellar-
epoch catalogue. It is isolated on `feature/gaia-v0.4`; versions 0.1.0 and 0.3.0,
the original image/reference products and all regression thresholds are preserved.
The normal default remains Tycho/Hipparcos. This experiment does not implement the
separate OLS zenith reference, joint atmospheric correction or blind planetary clock.

## Data and scientific scope

The bundled Gaia DR3 catalogue contains 36,663 sources at G<=7.5 and 78 labelled
very bright supplements from the existing Tycho/Hipparcos catalogue. It uses the
same seven CSV fields, including native reference epoch and proper-motion pairs.
Positions and motions are changed together; Gaia motions are never applied to
unmatched Tycho positions. Native Gaia source IDs and numerical precision survive
conversion. A separate archive COUNT(*) verifies download completeness. See
[data provenance](../data/README.md) and the query/checksum sidecar.

Gaia G, BP and RP values and fetched quality fields are retained in the raw CSV.
G and VT are different passbands, so G<=7.5 and VT<=7.5 do not define equal stellar
populations. Missing motion pairs remain flagged, stationary approximations; they
are not dropped. No RUWE/duplicated-source cuts are applied in this first experiment.
Very bright supplements keep their own epochs and PM values and are deduplicated
within 3 arcseconds at J2016. Their TYC/HIP identifiers expose their provenance.

Both full solves start independently from the same pixels and use identical
point detection, tetra3 bootstrap, progressive association gates, Barghini fit and
epoch range (1850–2150). Different associations are allowed. The tetra3 pattern
database remains common: this is a Gaia refinement/epoch catalogue replacement,
not a newly constructed Gaia-only bootstrap. There are no supplied site/time,
saved-solution seeds, hidden identifiers or withheld stars in the full fits.

## Reproduce

From this checkout:

```sh
./solve.sh examples/milky_way/input.jpeg --offline \
  --catalog data/stars_gaia_dr3_g75.csv --output results/new-gaia-solve

OPENBLAS_NUM_THREADS=1 uv run --frozen python scripts/compare_catalogues.py \
  examples/milky_way/input.jpeg --output results/new-gaia-tycho-comparison
```

The second command writes separate `tycho/` and `gaia/` full solutions, the
comparison JSON/Markdown/PNG, paired residuals in `shared_residuals.csv`, explicit
membership in `resampling_membership.json`, and all per-sample camera/epoch fits
in `resampling.json`. Existing output directories are rejected. OpenBLAS is
restricted to one thread in this command to avoid thread overhead; solver
objectives and tolerances are unchanged. A fresh download is optional: the
included catalogue supports offline solves.

## Spatial sensitivity protocol

After the full solves, split the measured field into four radial bands and eight
azimuth sectors. With seed 20260914, generate 32 independent draws retaining
80% of occupied spatial blocks (rounded upward, at least one block omitted).
Use the same retained blocks for both catalogues. Stars may differ within each
block, but shared detections keep exactly the same measured centroid.

For each draw, refit the camera and stellar epoch using each catalogue's retained
full-solve associations. Save numerical best epochs, conditional intervals,
fit-status flags and physical camera parameters. Preserve failures explicitly.
These resamples are an opt-in experiment, not a change to the all-stars default.
They condition on the original associations and do not repeat bootstrap or
reassociation. Their 5th–95th percentile range is a sensitivity range, not a
calibrated confidence interval or an independent test of astrometric accuracy.

Shared-detection RMS compares the same measured centroids against each catalogue's
fitted predictions. It avoids comparing only differently selected populations,
but remains an in-sample residual metric. Neither lower RMS nor resampling removes
refraction, lens-model error, blending, catalogue correlations or unmodelled
parallax/perspective effects. A stable relative epoch shift can coexist with broad,
overlapping absolute epoch intervals. Metadata is not revealed by this experiment.


## Measured result on the preserved Milky Way image

| Quantity | Tycho/Hipparcos | Gaia DR3 + bright supplement |
|---|---:|---:|
| Associations | 3653 | 3665 |
| Complete proper-motion pairs in fit | 3488 | 3521 |
| Flagged missing motion pairs in fit | 165 | 144 |
| All-association RMS [px] | 0.397811 | 0.396424 |
| RMS on 3652 shared measured detections [px] | 0.397824 | 0.395547 |
| Numerical stellar epoch [Julian year] | 2024.96 | 2008.72 |
| Approximate conditional 95% epoch interval | 2002.62–2046.93 | 1989.22–2027.92 |

The Gaia solution contains 3643 native Gaia associations and 22 bright supplements.
It gains 13 measured associations absent from the Tycho solve and loses one.
Both full solutions have closed conditional epoch profiles; these intervals do
not include catalogue or lens/atmospheric systematic errors.

All 32 paired spatial resamples completed, and both epoch profiles remained
conditional in every pair. Gaia's RMS on shared retained detections was lower
in all 32, with median difference (Gaia minus Tycho) -0.002351 px and 5th–95th
percentile range -0.003103 to -0.001193 px. Its numerical epoch was earlier in
all 32, with median difference -15.98 years and range -19.82 to -11.28 years.
These are relative sensitivity results, not confidence bounds on the true date.

The experiment supports a small, repeatable improvement in the fitted residuals
for this image when using Gaia. It does not establish improved absolute epoch
accuracy: the two broad absolute intervals overlap, and common model biases remain.
The default catalogue is therefore preserved; Gaia is available explicitly for
further images and tests. Compact numeric evidence and replicate differences are
in [GAIA_V04_RESULTS.json](GAIA_V04_RESULTS.json).
