# Point-source feature status, version 0.4.0

This inventory distinguishes implemented behavior from recorded proposals. A new
version must preserve implemented behavior or document an explicit change, and
must not describe a proposal as working merely because related products exist.

| Capability | Implemented status | Evidence / limitation |
|---|---|---|
| Lossless PNG output speedup | Preserved | Compression level 1; decoded pixels unchanged; report PDFs retain native PNG resolution |
| Ordinary plot names | Enabled by the versioned go launcher | Local display-only aliases, then SIMBAD after fitting; unresolved numeric labels omitted, source markers retained |
| Point-source detection, including large/saturated sources | Preserved | Historical demo and detection tests |
| Blind pattern bootstrap and Barghini lens fit | Preserved | Fresh pixels and bundled pattern database; no saved associations |
| Proper-motion propagation in the final astrometric solution | Added in 0.3.0 | Shared catalogue propagation, synthetic recovery and exported-coordinate checks |
| Stellar epoch fitted with all associations; final camera saved | Added in 0.3.0 | All-star robust profile; conditional or provisional date status |
| RGB instrumental photometry | Implemented | Aperture fluxes and flags retained in stellar_photometry.csv |
| Extinction as nuisance regression in blind zenith search | Added in 0.3.0 using robust regression | Fixed membership; no site/time-derived airmass; G plot uses the exact fitted line. The OLS reference specified in GOAL.md and its comparison remain unimplemented |
| Zenith estimated by minimising photometric regression scatter | Added in 0.3.0; conditional component | Synthetic recovery and degeneracy tests; real example remains unresolved under the radial-response check |
| Zenith fitted through astrometric refraction residuals | Implemented downstream diagnostic | Different objective from photometric zenith; does not establish that photometric proposal works |
| Joint photometric zenith/extinction and astrometric epoch constraint | **Not implemented** | Not part of the 0.3.0 proper-motion bugfix; must be designed and tested explicitly |
| Blind planetary epoch | **Not implemented** | Default metadata-centred lookup disabled; a separate blind positional search remains required |
| Post-fit metadata comparison, including pole–zenith latitude | Added in 0.3.0 | Explicit `--compare-metadata`; no refit, uncertainty/status retained |
| Gaia reference catalogue | Added in 0.4.0 as an opt-in alternative | Native DR3 epochs/PM, 36,663 Gaia rows plus 78 labelled bright supplements; `go_v0.4.0.sh` explicitly selects Gaia; bare solve/analyse CLI defaults remain Tycho/Hipparcos |
| Independent same-image catalogue comparison and paired spatial resampling | Added in 0.4.0 | Different associations allowed; 32 explicit spatial deletion refits; conditional sensitivity, not independent validation |

## Photometric zenith proposal: provenance and implementation

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
that history have not been established. The new version 0.3.0 implementation now supplies the missing outer loop in
`point_star_zenith.py`, called by `measure_photometry`. It preserves all measurement
rows while fixing the eligible photometric sample before the search.

Synthetic tests recover a known zenith with unknown zero point and extinction,
and reject weak extinction, insufficient coverage, coincident/nearly collinear
rays, a search-boundary solution and vignetting-only data. Metadata-independence
tests alter or poison the date/site and assert identical photometric products.
The preserved example fits 2432 photometric sources but remains unresolved because
the radial-response sensitivity solution reaches the altitude boundary. General
colour, cloud and lens-response biases still require scientific validation.

This is an integrated downstream photometric constraint, not a joint photometric/
refraction/epoch solution. If its future coupling changes astrometry, that change
must propagate into the saved Barghini camera and coordinates. See `GOAL.md` for
the durable scientific requirements.


## September 15 implementation audit

The v0.4 branch includes commits 66bbbc4 (lossless PNG speedup), 0833bee
(proper-motion/epoch loop and saved-camera fix), c2f0afc (blind photometric zenith)
and 94ca721 (Gaia comparison). Epoch trials propagate coordinates and refit the
camera; an outer loop reassociates until stable, then saves that fitted camera.
Photometric zenith and atmospheric refraction remain downstream. Their joint
coupling is unfinished; it must not be described as covered by the epoch bugfix.
The separate v2 magnitude-depth experiment is not merged. Use magnitude 7.5 until
Peter requests a change, as recorded in GOAL.md.
