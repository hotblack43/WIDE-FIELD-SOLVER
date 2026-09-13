# Short wide-field astrometry report

`wide_field_diagnostics.pdf` is the compiled research note. The source uses
A4 paper, 12-point body text, a landscape diagnostic page, author–year
citations, and clickable figure/table references, DOI and repository links.
The scientific-lineage section traces Ceplecha (1987), Borovička (1992, 1995)
and Barghini et al. (2019), distinguishing inherited models from later changes.

This directory is self-contained for compilation: the TeX source, bibliography,
and two unchanged PNG figures are included. The figure copies are byte-for-byte
identical to `examples/milky_way/diagnostics/` at repository revision
`e157db1296aa6beea17283c1920c21bc45eb618f`. The same numerical radial report is
included in `data/radial_residuals.json` for auditing the table.

## Build

Requires a LaTeX installation with `latexmk`, pdfLaTeX and BibTeX, including
the standard `natbib`, `hyperref`, `pdflscape`, `caption`, `geometry`, `microtype`
and Latin Modern packages.

From this directory:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build wide_field_diagnostics.tex
cp build/wide_field_diagnostics.pdf wide_field_diagnostics.pdf
```

Only temporary compilation files are ignored. The source, bibliography, figures
and final PDF are eligible for version control. The report introduces no changes
to detection, fitting, coordinates or the preserved `v0.1.0` baseline.

The supplied photograph's attribution and redistribution rights remain
undocumented; retain this report within the private research project.

## Source checks

The 2019 paper was read from the nearby local copy in
`FITSIMAGES/STARTRAILS/PAPERS/2019_Barghini_et_al_All_Sky_Astrometric_Calibration.pdf`.
Sections 2, 4.2, 5 and 6.4 establish the lineage and implementation distinctions.
The original 1995 paper was retrieved from ADS; its Sections 1.2 and 2.1 and
Figures 2–3 directly support the older model and edge-error discussion.
The 1992 publication details were checked against the author's publication
list; its model is reproduced in the 1995 paper. The Ceplecha attribution is
explicitly reported through Barghini's historical account. No claim is made
that the 1987 or 1992 full texts were inspected for this report.

Overleaf project: https://www.overleaf.com/project/6aa662a9d1a00c33f9a82822.
Its separate Git checkout preserves Overleaf history; pull it before syncing
later revisions to avoid overwriting online edits.
