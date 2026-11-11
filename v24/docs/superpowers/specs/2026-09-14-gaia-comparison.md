# Gaia versus Tycho on the same image

Implement Peter's requested catalogue replacement experiment in isolated version
0.4.0, based on verified 0.3.0. Preserve both previous versions, all historical
assets and the clarified GOAL.md. This is an astrometric catalogue comparison;
OLS zenith changes and joint refraction fitting are separate unfinished work.

Fetch an all-sky Gaia DR3 G<=7.5 catalogue from the public ESA TAP archive. Write
the existing seven-column CSV schema with native ICRS positions, reference epoch
and pmra (including cos(dec))/pmdec. Preserve exact source identifiers, missing-PM
flags, raw Gaia G/BP/RP and quality data, query, row count and checksums. Retain
missing motions without inventing measurements. Supplement missing very bright
stars (existing catalogue magnitude <=3) from the local Tycho/Hipparcos catalogue,
deduplicating at J2016 within 3 arcseconds and explicitly labelling provenance.
No quality-based Gaia exclusions in this first comparison; retain diagnostics.

Run both catalogues independently from the same image pixels with identical
bootstrap, detection, magnitude progression, epoch range and Barghini settings.
The existing tetra3 pattern database stays common: this tests replacement of the
refinement/epoch catalogue, not a new Gaia-only blind bootstrap. Default solver
catalogue remains preserved Tycho until evidence supports adoption. No site/time,
saved associations or names seed either full run. Different identified stars are
allowed. G and VT limits are not physically equivalent; report the difference.

After full solves, perform 32 paired spatial block subsamples (fixed seed
20260914, keep 80% of occupied blocks, four radial bands and eight sectors).
Use the same image blocks for both catalogues, allowing different stars inside
them. Refit camera and stellar epoch on each retained association set. These
are explicit experimental subsamples, not a change to the no-withholding default.
Record all failures and unresolved/boundary epochs. Associations stay conditional
on each independent full solve; this is sensitivity analysis, not independent
validation or a calibrated confidence interval.

Compare full association counts, PM coverage, residuals, conditional epoch
profiles, fitted lens parameters, and residuals on shared measured detections.
Report paired resampling distributions of epoch and shared-detection RMS
differences, with an inspectable figure and machine-readable products. No claim
of improved absolute accuracy follows just from a lower training residual.
