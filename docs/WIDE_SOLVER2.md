# Wide-field solver 2: catalogue-depth exploration

Version 2 explores how the global Barghini fit changes when the Tycho-2
limiting magnitude is increased modestly. It is separate from the preserved v1
solver and does not replace the frozen v1 catalogue or historical example.

## New files

- `point_star_barghini2.py`: v2 solver with explicit limiting-magnitude
  filtering in both progressive and final association.
- `analyse_image2.py`: comparison driver for independent 7.5, 8.0, and 8.5
  candidate solutions.
- `scripts/rebuild_catalogue2.py`: Tycho-2 catalogue builder defaulting to
  VT <= 8.5 and retaining the Hipparcos V <= 2.0 bright-star supplement.
- `data/stars_tycho2_mag85_v2.csv`: frozen v2 candidate catalogue.
- `test_point_star_barghini2.py`, `test_analyse_image2.py`, and
  `test_rebuild_catalogue2.py`: v2 behavior tests.

The existing `point_star_barghini.py`, `analyse_image.py`,
`scripts/rebuild_catalogue.py`, and `data/stars_tycho2_mag75.csv` remain the
v1 path.

## Catalogue provenance

The v2 catalogue was built on 14 September 2026 from CDS/VizieR Tycho-2
(I/259/tyc2), selecting 71,412 rows with VT <= 8.5. The existing Hipparcos
(I/239/hip_main) supplement procedure added 44 stars with V <= 2.0 that were
not within 60 arcseconds of a selected Tycho-2 position. The resulting 71,456
identifiers are unique. Its SHA-256 is:

`4b63c2f138550fc5e74db898a2b5308519047221b965c5c609dc0d7bb8f7b28d`

Rebuild it with:

```sh
uv run --frozen python scripts/rebuild_catalogue2.py
```

## Running the comparison

```sh
uv run --frozen python analyse_image2.py \
  examples/milky_way/input.jpeg \
  --output results/wide-solver2 \
  --catalog data/stars_tycho2_mag85_v2.csv \
  --offline \
  --names-cache examples/milky_way/reference/display_names.json
```

Each limit is solved independently into `vlim_7p5/`, `vlim_8p0/`, or
`vlim_8p5/`. The top-level
`limiting_magnitude_comparison2.json` records fit metrics and identity
stability. It deliberately contains
`"selection": "none_exploratory_comparison_only"`.

## First preserved-image experiment

The Milky Way input produced:

| VT limit | Catalogue rows | Associations | RMS [px] | Median [px] | 90th pct. [px] | Unmatched |
|---:|---:|---:|---:|---:|---:|---:|
| 7.5 | 24,531 | 3,653 | 0.397892 | 0.248944 | 0.605858 | 35 |
| 8.0 | 41,987 | 3,674 | 0.394984 | 0.248041 | 0.600484 | 14 |
| 8.5 | 71,456 | 3,675 | 0.386931 | 0.245621 | 0.592759 | 13 |

From 7.5 to 8.0, 3,583 detector-to-star pairs remain stable, 91 catalogue
identities are gained, 70 are lost, and 70 shared detections are reassigned.
From 8.0 to 8.5, 3,613 pairs remain stable, 62 identities are gained, 61 are
lost, and 61 detections are reassigned.

The additional depth therefore changes associations even when the net match
count changes little. In particular, 8.5 adds only one net association over
8.0. The lower fitted RMS at 8.5 is not sufficient evidence that 8.5 is the
best limit, because every accepted association participates in the fit. These
are fit diagnostics, not independent validation. V2 reports the comparison
without choosing a winner.

All 3,688 detected sources remain available for association and fitting at
every limit. No withheld-star default, cosmetic coordinate shift, or change to
the Barghini model is introduced.
