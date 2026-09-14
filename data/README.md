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

The preserved v0.1.0 baseline and explicit `--epoch-mode catalog` replay read
the stored RA/Dec directly. Version 0.3.0 propagates each entry from its own
reference epoch in the normal solve. Missing proper motions are flagged and
use stationary reference positions; these stars remain available for fitting.
See [version 0.3 notes](../docs/PROPER_MOTION_V03.md).

To download a new candidate catalogue from VizieR (requires network access):

```sh
uv run --frozen python scripts/rebuild_catalogue.py \
  --output results/catalogue-candidate.csv
```

Review and test a new catalogue before adopting it. Preserve the frozen file
for replaying `v0.1.0`; its SHA-256 is recorded in the example baseline.


## Gaia DR3 alternative (version 0.4.0)

`stars_gaia_dr3_g75.csv` has the same seven solver columns as the preserved
Tycho/Hipparcos file. It contains 36,663 Gaia DR3 sources selected at G<=7.5,
plus 78 missing very bright references from the local Tycho/Hipparcos catalogue
(magnitude <=3). Gaia source IDs are exact strings prefixed `Gaia DR3`; supplements
keep their TYC/HIP identifiers, magnitudes and native astrometry. Gaia rows use
the native `ref_epoch` (J2016.0), ICRS RA/Dec, and pmra/pmdec in mas/year, with the
cos(dec) factor already included in pmra. No frame rotation or rounded identifiers.

The supplement is deduplicated within 3 arcseconds after both catalogues are
propagated to J2016.0 using the same vector motion code as the solver. All returned
Gaia sources are retained, including missing proper motions; no RUWE or duplicate
flag cuts have been applied. A missing pair uses the solver's flagged stationary
approximation. The combined catalogue has 36,068 complete motion pairs.

`stars_gaia_dr3_g75.gaia-source.csv` retains the original archive astrometry,
G/BP/RP photometry, marginal errors, RUWE and other fetched quality fields.
The `.provenance.json` sidecar records the exact ADQL query, archive count,
retrieval timestamp, supplement IDs and checksums. The seven-column fit still
omits annual parallax, radial/perspective motion and catalogue covariance.

Rebuild into a new path (network access required only for this step):

```sh
uv run --frozen python scripts/build_gaia_catalogue.py \
  --output results/new-gaia-catalogue.csv
```

The public ESA TAP response is checked against a separate COUNT(*) query to
reject truncated downloads. Existing catalogue and sidecar files are protected.
The bundled CSV permits offline normal solves. Gaia G and Tycho VT are different
passbands, so equal numerical limits do not select the same stellar population.
Neither catalogue is an independent truth standard for the same-image comparison.

References: [ESA Gaia DR3 contents](https://www.cosmos.esa.int/web/gaia/dr3),
[Gaia DR3 source data model](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html).
