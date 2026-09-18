# Reader-Facing Wide-Field Solver Paper Revision

**Date:** 2026-09-18  
**Status:** Approved in chat; written specification awaiting final review  
**Overleaf project:** `6aa662a9d1a00c33f9a82822`

## Purpose

Replace the current five-page feasibility note with a reader-facing research
paper that explains the scientific problem, method, evidence, capabilities and
limitations of the current wide-field point-source solver. Preserve the present
manuscript as an immutable, dated version inside the same Overleaf project and
keep the synchronized local manuscript under
`reports/wide-field-diagnostics/`.

The revised paper must not read as a software changelog. Internal version
numbers may appear only where required for reproducibility; they must not
organize the scientific narrative.

## Scientific framing

The paper will present an end-to-end solver for wide-field and all-sky
point-source images. Its central claims are:

1. Measured point sources can bootstrap a blind catalogue association and a
   Barghini O/Z fisheye-camera solution without using site, time, cached
   identities or saved solutions.
2. Catalogue proper motion, angular association, detector parity and the fitted
   camera are handled consistently through the saved astrometric products.
3. Native scientific image values support multi-channel instrumental
   photometry, explicit saturation handling and repeated-observation studies.
4. Image-derived zenith information supplies a conditional physical constraint
   for visibility, extinction and planetary analysis.
5. Planetary evidence is retained with its alternative identities and dates;
   observation metadata is introduced only after the stellar solution is fixed
   and is described as conditional identification or validation rather than
   blind epoch inference.
6. Heterogeneous archives with native colour FITS data and repeated exposures
   are essential for evaluating these capabilities beyond a single photograph.

Claims must remain bounded by the evidence in `GOAL.md`, the versioned
`FEATURE_STATUS.md` files, saved run products and regression documentation.

## Manuscript structure

The main Overleaf document remains `wide_field_diagnostics.tex` so the existing
project entry point continues to compile.

### Title and abstract

Use a title that describes blind wide-field point-source astrometry and
instrumental photometry rather than a version or development milestone. The
abstract will state the problem, the Barghini-model approach, the major image
classes supported, the main validation cases and the principal limitations.

### 1. Introduction

Motivate wide-field and all-sky images as scientifically valuable but difficult
because of strong lens distortion, variable plate scale, incomplete footprints,
detector reflection, saturation and uncertain observation metadata. State why
blind fitting and an explicit validation boundary matter.

### 2. Astrometric method

Describe measured-centroid detection, blind tetra3 bootstrap, progressive Gaia
association, proper-motion propagation, angular great-circle residuals,
detector-parity selection and robust fitting of the Barghini O/Z model. Explain
that all detected sources remain available to association and that fitted
coordinates arise from the saved camera rather than cosmetic plot adjustments.

Retain the scientific lineage from Ceplecha, Borovička and Barghini, but integrate
it into the method rather than leaving it as a detached historical appendix.

### 3. Native image data and instrumental photometry

Explain support for high-bit-depth raster images, monochrome and multi-plane
FITS, compressed FITS, explicit channel layouts, invalid samples, exposure
provenance and per-channel saturation. Define raw aperture counts,
exposure-normalized instrumental count rates and saturated-wing Moffat models.
State that these are instrumental measurements, not calibrated physical fluxes,
and that wing models never replace measured counts or enter the zenith/extinction
sample.

### 4. Zenith, extinction and visibility

Describe the fixed-sample stellar-extinction search for an image-derived zenith,
including zero point and extinction as nuisance parameters. Explain the
conservative centred full-horizon fallback and the use of the adopted zenith for
planet visibility. Clearly distinguish the physical zenith from the Barghini
reference Z and from the downstream refraction diagnostic.

### 5. Planetary analysis

Describe searches for the seven major planets, Ceres and Vesta; physical
visibility; solar consistency; competing Gaia associations; missing-bright-body
evidence; coherent multi-object configurations; and preservation of aliases.
Separate global blind candidate searches from exact supplied-time or
metadata-conditioned identification performed after the stellar fit is fixed.

### 6. Results on heterogeneous images

Lead with the original Milky Way image as the high-density feasibility example.
Then use scientific all-sky data to show capabilities absent from the original
experiment: native dynamic range, detector parity, repeated sampling, independent
colour planes and saturated-source recovery. Include numerical results only when
they can be traced to committed documentation or immutable saved run products.

### 7. Why repeated native-colour archives matter

Give MMTO a dedicated reader-facing subsection. Explain that repositories of
native R/G/B FITS exposures provide:

- independent colour planes rather than encoded display colour;
- preserved dynamic range and explicit saturation behavior;
- exposure timing needed for comparable count rates;
- repeated cadence across a night;
- enough sources across the field to examine spatial, brightness and colour
  systematics; and
- immutable originals and manifests that allow results to be audited.

Contrast these properties with processed JPEG archives without implying that the
current MMTO time series is calibrated photometry. Present the MMTO light curves
as demonstrations of repeatable instrumental measurement and a route toward
future extinction, transparency, vignetting and variability models.

### 8. Discussion and limitations

Discuss generality across ordinary photographs and scientific FITS, the value of
angular residuals and physical gates, and the role of archive-scale repeated
data. State all unresolved limitations listed below.

### 9. Reproducibility and conclusions

Describe machine-readable results, ZPN FITS/WCS export, append-only run storage,
source manifests and the public repository. Conclude with the scientific
capability and the next validation steps, not the software release history.

## Figures and tables

Use a small set of evidence-rich figures with captions that explain the
scientific point and all important plotting conventions.

1. **Dense-field astrometric overlay:** retain the original measured-centroid and
   fitted-prediction overlay. Symbols remain at their true positions.
2. **Astrometric residual diagnostics:** retain the original centre-to-edge
   residual panel with the explicitly labelled residual-vector magnification.
3. **Scientific colour-FITS solution:** use one representative MMTO R/G/B FITS
   solution to show the all-sky footprint, fitted sources and a detected bright
   object. Its caption must distinguish metadata-time identification from blind
   epoch inference.
4. **MMTO astrometric residuals:** show angular and pixel residual behavior for
   the same representative exposure.
5. **Photometric/zenith diagnostic:** include either the extinction relation and
   zenith profile as a paired figure or the single panel that most clearly
   communicates identifiability. The caption must report when the result is
   conditional or not identifiable.
6. **Repeated MMTO instrumental photometry:** include the consolidated light-curve
   panel generated from hash-matched archive timestamps and successful solver
   runs.
7. **Residual scatter versus catalogue magnitude:** include the MMTO ensemble
   diagnostic, explicitly noting that detrended residual scatter is not an
   independent estimate of absolute photometric precision.

Add one compact table summarizing image classes and demonstrated capabilities:
ordinary photograph, processed all-sky image, high-dynamic-range monochrome
FITS, reflected APICAM FITS, and repeated native-colour MMTO FITS. Do not create
a release/version table.

Every copied figure must have a local provenance record giving its original
path, source-image hash or run identifier where available, generation product,
and the numerical statement supported by the figure. Do not copy the full MMTO
FITS archive into either Git repository.

## Scientific limitations that must remain explicit

- Astrometric residuals of fitted associations are not independent accuracy or
  completeness validation.
- The photometric zenith can be conditional or non-identifiable.
- The OLS reference comparison requested in `GOAL.md` is not yet implemented;
  the current extinction fit uses its documented robust regression.
- Atmospheric refraction remains a downstream diagnostic rather than a single
  fully coupled astrometry--refraction--photometric-zenith--epoch fit.
- Global planetary epoch inference can remain ambiguous, especially for a
  single body.
- Metadata-conditioned planet analysis is post-fit validation/identification,
  not blind epoch inference.
- RGB magnitudes, aperture values, wing-model totals and count rates are
  instrumental rather than calibrated physical photometry.
- Light-curve detrending does not by itself separate airmass, vignetting,
  transparency, colour terms, clouds or intrinsic variability.
- Append-only SQLite data and saved identities are never used to seed a solve.

## Version preservation and synchronization

Before editing, clone or pull Overleaf project `6aa662a9d1a00c33f9a82822` into a
separate checkout and inspect its status. If it contains online changes absent
from the local manuscript, merge them into the preserved baseline before making
the revision.

Within the Overleaf repository, create a dated archive directory containing the
complete pre-revision compilable manuscript: main TeX source, bibliography,
figures and PDF. Add a short archive README recording the source commit and date.
The archive is immutable after creation.

Build the revised paper locally with `latexmk`, BibTeX and pdfLaTeX. Treat
undefined references, missing citations, missing figures and compilation errors
as failures. Inspect the compiled PDF for page layout, figure legibility,
caption placement and accidental version/process language.

Commit and push the archival snapshot and revised paper to the existing Overleaf
project. Then synchronize the same source, bibliography, selected figures,
provenance record and compiled PDF into `reports/wide-field-diagnostics/` in the
solver repository. Commit only manuscript-related files there; preserve the
unrelated working-tree modification to `goBIG`.

## Acceptance criteria

The revision is complete when:

1. the original manuscript is preserved as a compilable dated archive in the
   Overleaf project;
2. the Overleaf main document is the revised reader-facing paper;
3. the paper compiles without LaTeX or bibliography errors;
4. every figure is legible and has recorded provenance;
5. MMTO's scientific value as a repeated native-colour FITS archive is clear;
6. claims and limitations agree with `GOAL.md` and saved evidence;
7. no section is organized as a version history or development changelog;
8. the Overleaf and local manuscript sources and final PDF match byte-for-byte;
9. both Git histories contain dedicated manuscript commits; and
10. `goBIG`, preserved solver versions, historical examples and reference data
    are unchanged.
