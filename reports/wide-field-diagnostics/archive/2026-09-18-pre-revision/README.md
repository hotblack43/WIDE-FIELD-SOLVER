# Planetary dating of wide-field sky images

The Overleaf main document is main.tex, a short A&A-format paper demonstrating
blind recovery of the date of Fred Espenak's 2018 April 15 circular-fisheye
image from planetary ephemerides. It includes the stellar and Barghini lens
solution, daily and continuous epoch searches, limitations, and scientific
perspectives.

Keep main.tex selected as the main document in Overleaf. The current A&A class
and bibliography style are included locally as aa.cls and aa.bst.

The earlier feasibility report remains available as wide_field_diagnostics.tex;
it is no longer the main document. The figure-generation script, its tests, and
analysis_summary.json reproduce and audit the numerical values against the
saved local solver products. Figures are committed so Overleaf does not require
the solver data or Python environment.

## Build

Run:

    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

Temporary compilation files are ignored. This manuscript repository introduces
no changes to the solver's detection, fitting, coordinates, or preserved v0.1.0
baseline.

The supplied photograph remains credited to Fred Espenak. Its redistribution
rights are not asserted by this repository.

Overleaf project: https://www.overleaf.com/project/6aa662a9d1a00c33f9a82822
