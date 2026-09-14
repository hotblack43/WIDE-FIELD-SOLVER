# Point-source feature status, version 0.3.0

This inventory distinguishes implemented behavior from recorded proposals. A new
version must preserve implemented behavior or document an explicit change, and
must not describe a proposal as working merely because related products exist.

| Capability | Implemented status | Evidence / limitation |
|---|---|---|
| Point-source detection, including large/saturated sources | Preserved | Historical demo and detection tests |
| Blind pattern bootstrap and Barghini lens fit | Preserved | Fresh pixels and bundled pattern database; no saved associations |
| Proper-motion propagation in the final astrometric solution | Added in 0.3.0 | Shared catalogue propagation, synthetic recovery and exported-coordinate checks |
| Stellar epoch fitted with all associations; final camera saved | Added in 0.3.0 | All-star robust profile; conditional or provisional date status |
| RGB instrumental photometry | Implemented | Aperture fluxes and flags retained in stellar_photometry.csv |
| Extinction regression using site/time-derived airmass | Implemented downstream | Requires supplied/recovered metadata; not a constraint on the stellar epoch objective |
| Zenith estimated by minimising photometric regression scatter | **Not implemented** | Exact proposal recorded 13 September in PHOTOMETRY_ZENITH_EXTINCTION_NOTE.md |
| Zenith fitted through astrometric refraction residuals | Implemented downstream diagnostic | Different objective from photometric zenith; does not establish that photometric proposal works |
| Joint photometric zenith/extinction and astrometric epoch constraint | **Not implemented** | Not part of the 0.3.0 proper-motion bugfix; must be designed and tested explicitly |
| Gaia reference catalogue | **Not implemented** | Compatibility assessed; current data remain Tycho-2 plus Hipparcos |

## Photometric zenith proposal: provenance and missing step

Commit 8247c33 (13 September 2026, 13:16 CEST) records Peter's proposed outer loop:
for each candidate physical zenith, calculate airmasses; regress instrumental
minus catalogue magnitude on airmass; compare residual scatter on consistent
stars and adjust zenith to minimise it. Extinction slope and zero point are
nuisance fit parameters in this zenith constraint. The original note explicitly
labels the work deferred and prescribes tests for extinction, vignetting and
cloud degeneracies.

Commit a3317ec (14 September 2026, 10:26 CEST) introduced point_star_science.py.
It obtains altitudes from site/time metadata and regresses dimming on those
fixed airmasses. There is no outer photometric zenith search. The v2 catalogue-
depth branch does not add one either. No deletion of such a working loop was
found in the available point-source repository history; versions or work outside
that history have not been established. Version 0.3.0 does not remove the proposal
or claim to implement it.

Before calling this method implemented, test recovery of synthetic zenith with
unknown regression slope/zero point; use the same usable stars across candidate
zeniths; demonstrate unresolved behavior for insufficient extinction/coverage;
and test sensitivity to vignetting, colours and clouds. If this constraint later
changes the astrometric fit, it must propagate into the saved camera and coordinates.
