# Frozen reference catalogue

## Planet reference (version 0.6.0)

`planet-reference-1850-2036.npz` is the metadata-independent daily TDB table
used to propose blind planetary epochs. It contains normalized geocentric
apparent GCRS directions for Mercury through Neptune from Julian year 1850 to
2036, inclusive. The upper limit deliberately leaves ten years beyond the 2026
release without spending runtime or repository space on implausible future
images. The solver still applies its causal run-time ceiling, so future dates
cannot seed or enter a fit.

The numerical-content SHA-256 is
`ebf09fdcde047cc8f0b1a0030e212590bcb2db1555ab824e060d46e27c00adac`.
Rebuild or verify it with the locked v6 environment:

```sh
uv run --frozen python scripts/build_planet_ephemeris_cache.py \
  --output data/planet-reference-1850-2036.npz
uv run --frozen python scripts/build_planet_ephemeris_cache.py \
  --verify data/planet-reference-1850-2036.npz
```

The table is a coarse proposal aid. Final gates, residuals, visibility and
reported epochs use exact Astropy builtin ephemeris evaluations. Its historical
1850--1900 tail is outside ERFA's best-characterised 1900--2100 interval and is
therefore approximate rather than a precision dating standard.

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


## Ordinary display names

`display_names.json` is a display-only SIMBAD alias cache: it combines the
preserved example's aliases with successful lookups for the inspected Warwick
image. Gaia IDs appearing in a cached alias list resolve to the same ordinary
name. Exact cached keys take precedence; ambiguous alias matches are not used.

Names are resolved only after the astrometric fit. The versioned go launcher
uses this local cache and queries SIMBAD for missing names; direct `--offline`
runs use available cached aliases. Unresolved stars retain their plotted marker
without a long Gaia numeric label. All source IDs remain in numerical records.
No alias, cached coordinate or lookup result seeds or adjusts astrometry.
