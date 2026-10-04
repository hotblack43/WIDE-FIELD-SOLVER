# Blind wide-field astrometry and native-colour photometry

The Overleaf main document is main.tex, an A&A-format paper on blind
wide-field astrometry, native-plane instrumental photometry, repeated MMTO
light curves, and conditional planetary validation. Its organization is
reader-facing: scientific questions, methods, evidence, limitations, and
archive value rather than solver development history.

Keep main.tex selected as the main document in Overleaf. The current A&A class
and bibliography style are included locally as aa.cls and aa.bst.

The earlier feasibility report remains available as wide_field_diagnostics.tex;
it is no longer the main document. The figure-generation script, its tests, and
analysis_summary.json reproduce and audit the numerical values against the
saved local solver products. Figures are committed so Overleaf does not require
the solver data or Python environment.


The exact tracked project state pulled before this revision is preserved under
archive/2026-09-18-pre-revision/ and compiles independently. Selected MMTO
figures are derived products only; their immutable run paths, hashes, numerical
claims, and interpretation boundaries are recorded in
data/figure_provenance.json. Source FITS data are deliberately not copied
into this manuscript repository.

## Build

Run:

    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

Temporary compilation files are ignored. This manuscript repository introduces
no changes to the solver's detection, fitting, coordinates, or preserved v0.1.0
baseline.

The supplied Espenak photograph remains credited to its photographer. The MMTO
products remain subject to their archive access terms.

## Current MMTO colour and response diagnostics

The manuscript now retains three October 2026 diagnostics: the orthogonal
planet-colour panels, extinction-corrected machine magnitude against Gaia
catalogue magnitude, and the held-out same-star natural-attenuation test. The
two stellar figures are regenerated from the saved nightly-calibration sidecar
with:

    uv run --frozen python scripts/plot_stellar_linearity.py \
      --input-root results/nightly-extinction/20261002T-fixed-effects-final-code \
      --catalogue v13/data/stars_gaia_dr3_g75.gaia-source.csv \
      --output reports/wide-field-diagnostics/figures/mmto_machine_magnitude_vs_catalogue_magnitude.png

    uv run --frozen python scripts/plot_stellar_natural_attenuation.py \
      --measurements results/nightly-extinction/20261002T-fixed-effects-final-code/calibration_star_measurements.csv \
      --output reports/wide-field-diagnostics/figures/mmto_natural_attenuation_response.png

The natural-attenuation script also writes a row-level CSV and a JSON summary.
The numerical manuscript claims are mirrored in `analysis_summary.json`. The
planet-colour figure is currently preserved from
`results/planet-colour-preview-20261004/planet_colour_colour_orthogonal_by_planet.png`.

Overleaf project: https://www.overleaf.com/project/6aa662a9d1a00c33f9a82822
