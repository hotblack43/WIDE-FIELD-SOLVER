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

Overleaf project: https://www.overleaf.com/project/6aa662a9d1a00c33f9a82822
