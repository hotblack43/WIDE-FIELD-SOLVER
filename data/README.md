# Frozen reference catalogue

`stars_tycho2_mag75.csv` contains 24,531 rows: 24,487 Tycho-2 stars selected at
VT ≤ 7.5, plus 44 exceptionally bright Hipparcos stars missing from the
positional cross-match. It is included so a normal solve needs no live
catalogue download.

- Tycho-2: Høg et al. (2000), [CDS I/259](https://cdsarc.cds.unistra.fr/viz-bin/cat/I/259).
- Hipparcos: ESA (1997), [CDS I/239](https://cdsarc.cds.unistra.fr/viz-bin/cat/I/239).

Columns are catalogue ID, RA/Dec in degrees, magnitude, reference epoch in
Julian years, and proper motions in mas/year (RA includes cos Dec).
Tycho-2 rows use epoch 2000.0; the Hipparcos rows retain epoch 1991.25.
The builder propagates the Hipparcos positions to 2000.0 for duplicate
checking within 60 arcseconds, while writing the original positions and epoch.
The Hipparcos supplement uses V ≤ 2.0, rather than Tycho VT.

The baseline solver reads the stored RA/Dec directly. Observation-epoch
propagation is future work. Keep this distinction when interpreting precision.

To download a new candidate catalogue from VizieR (requires network access):

```sh
uv run --frozen python scripts/rebuild_catalogue.py \
  --output results/catalogue-candidate.csv
```

Review and test a new catalogue before adopting it. Preserve the frozen file
for replaying `v0.1.0`; its SHA-256 is recorded in the example baseline.
