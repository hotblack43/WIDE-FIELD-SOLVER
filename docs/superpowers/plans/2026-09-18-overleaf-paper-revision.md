# Reader-Facing Wide-Field Solver Paper Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the short feasibility note with a reader-facing research paper, preserve the former manuscript inside the same Overleaf project, add evidence-rich solver/MMTO figures, and leave byte-identical synchronized manuscript copies in Overleaf and the solver repository.

**Architecture:** Work in a separate temporary checkout of the existing Overleaf Git repository, pulling its current main branch before any edits. Archive the pulled pre-revision document in that repository, revise the main TeX document and its self-contained figure bundle, compile and visually inspect it, then push Overleaf and copy the exact final source bundle into `reports/wide-field-diagnostics/` for a dedicated solver-repository commit.

**Tech Stack:** Git, Overleaf Git bridge, LaTeX/pdfLaTeX, BibTeX, `latexmk`, PNG/PDF scientific figures, JSON/CSV provenance, shell verification tools.

**Spec:** `docs/superpowers/specs/2026-09-18-overleaf-paper-revision-design.md`

## Global Constraints

- Keep all prose reader-facing; do not organize the paper by software version or development history.
- Preserve the current manuscript as a complete, compilable dated archive in the Overleaf repository.
- Pull Overleaf before editing and preserve online changes.
- Metadata may be described only as post-fit validation or conditional identification, never as blind epoch inference.
- Plot measured centroids and model predictions faithfully; any residual-vector magnification must be explicit.
- Instrumental counts, count rates, RGB comparisons and detrended scatter must not be described as calibrated photometry or independent precision.
- Do not copy the MMTO FITS archive into Git; copy only selected derived figures and provenance.
- Leave `goBIG`, frozen solver versions, historical inputs and reference products unchanged.
- The final local and Overleaf manuscript source bundles and PDFs must match byte-for-byte.

---

### Task 1: Establish and archive the current Overleaf baseline

**Files:**
- Create in Overleaf checkout: `archive/2026-09-18-pre-revision/README.md`
- Create in Overleaf checkout: `archive/2026-09-18-pre-revision/wide_field_diagnostics.tex`
- Create in Overleaf checkout: `archive/2026-09-18-pre-revision/references.bib`
- Create in Overleaf checkout: `archive/2026-09-18-pre-revision/figures/*`
- Create in Overleaf checkout: `archive/2026-09-18-pre-revision/wide_field_diagnostics.pdf`

**Interfaces:**
- Consumes: Overleaf project `6aa662a9d1a00c33f9a82822` and the current local manuscript for comparison.
- Produces: a pulled, clean Overleaf checkout and an immutable compilable archive of its pre-revision state.

- [ ] **Step 1: Clone the existing Overleaf project into a unique temporary directory**

  Use `mktemp -d` and clone `https://git@git.overleaf.com/6aa662a9d1a00c33f9a82822`; do not initialize a replacement project.

- [ ] **Step 2: Inspect the pulled branch, working tree and document entry point**

  Record `git status -sb`, `git log -1`, tracked files, and compare the live Overleaf TeX/bibliography/figures with `reports/wide-field-diagnostics/`.

- [ ] **Step 3: Build the unmodified Overleaf manuscript**

  Run `latexmk -pdf -interaction=nonstopmode -halt-on-error` in the checkout and retain the build transcript. Failure blocks revision until diagnosed.

- [ ] **Step 4: Create the dated pre-revision archive**

  Copy the pulled main TeX, bibliography, referenced figures and compiled PDF into `archive/2026-09-18-pre-revision/`. Adjust only relative figure/bibliography paths needed for the archived TeX to compile from its directory.

- [ ] **Step 5: Verify the archive compiles independently**

  Run `latexmk` from the archive directory and verify its generated PDF exists and contains the same page count as the pulled baseline.

### Task 2: Assemble the evidence figure bundle and provenance

**Files:**
- Create/modify in Overleaf checkout: `figures/astrometry_overlay.png`
- Create/modify in Overleaf checkout: `figures/astrometry_residuals.png`
- Create in Overleaf checkout: `figures/mmto_sky_overlay.png`
- Create in Overleaf checkout: `figures/mmto_astrometry_residuals.png`
- Create in Overleaf checkout: `figures/mmto_extinction_fit.png`
- Create in Overleaf checkout: `figures/mmto_zenith_profile.png`
- Create in Overleaf checkout: `figures/mmto_lightcurves.png`
- Create in Overleaf checkout: `figures/mmto_scatter_vs_magnitude.png`
- Create in Overleaf checkout: `data/figure_provenance.json`

**Interfaces:**
- Consumes: original committed diagnostic figures, immutable MMTO run products, MMTO manifest-backed light-curve products, and their result/summary JSON.
- Produces: a compact publication figure bundle with auditable source paths, hashes, run identifiers and supported claims.

- [ ] **Step 1: Verify the original astrometric figures against the committed copies**

  Compute SHA-256 hashes for the retained original overlay and residual diagnostics and record their repository provenance.

- [ ] **Step 2: Select one representative MMTO exposure**

  Select a successful native R/G/B FITS run with a converged blind stellar fit, mirrored parity, saved residual diagnostics, exposure provenance and exact post-fit Jupiter association. Record its compressed-input SHA-256 and run identifier.

- [ ] **Step 3: Copy only the selected derived MMTO figures**

  Copy the sky overlay, astrometric residuals, extinction fit and zenith profile from the selected immutable run. Do not copy source FITS data.

- [ ] **Step 4: Copy the consolidated MMTO repeated-photometry figures**

  Use the latest complete hash-matched output containing both `lightcurves.png` and `sd_vs_magnitude.png`, plus its `summary.json` and CSV audit values.

- [ ] **Step 5: Write and validate figure provenance**

  Store for every figure: destination name, original absolute/local source path, SHA-256, associated input hash or run ID, generation role, plotting caveat and manuscript claim. Validate the JSON with `python -m json.tool`.

### Task 3: Rewrite the manuscript as a reader-facing research paper

**Files:**
- Modify in Overleaf checkout: `wide_field_diagnostics.tex`
- Modify in Overleaf checkout: `references.bib`
- Modify in Overleaf checkout: `README.md`

**Interfaces:**
- Consumes: the approved design, `GOAL.md`, versioned feature-status evidence, selected figure provenance and saved numerical results.
- Produces: a self-contained paper organized by scientific question, method, evidence and limitations.

- [ ] **Step 1: Replace the title block and add an abstract**

  Frame blind wide-field astrometry, native instrumental photometry and archive-scale validation without mentioning development versions.

- [ ] **Step 2: Write the introduction and scientific requirements**

  Explain wide-field distortions, incomplete footprints, parity, saturation and uncertain metadata, then state the blind-fit/post-fit-validation boundary.

- [ ] **Step 3: Write the astrometric method and lineage**

  Integrate centroiding, tetra3 bootstrap, Gaia/proper motion, angular association, detector parity and the Barghini O/Z mapping with the Ceplecha--Borovička--Barghini lineage.

- [ ] **Step 4: Write native-data and instrumental-photometry methods**

  Define supported raster/FITS layouts, provenance, count rates, per-channel saturation and wing models with calibration limitations.

- [ ] **Step 5: Write zenith, extinction and planet methods**

  Separate physical zenith from reference Z, describe conditional extinction fitting and geometric fallback, then describe planetary visibility, solar consistency, Gaia competition, absence evidence, aliases and supplied-time validation.

- [ ] **Step 6: Write the heterogeneous-data results and MMTO section**

  Present the dense-field result, APICAM/parity evidence and native-colour MMTO results. Explain why independent colour planes, native dynamic range, exposure times, repeated cadence and immutable manifests make MMTO-like repositories important.

- [ ] **Step 7: Add figures and a reader-facing capability table**

  Use captions to state symbol meaning, residual magnification, conditional status and provenance. The table compares data classes and demonstrated capabilities, never software versions.

- [ ] **Step 8: Write discussion, limitations, reproducibility and conclusions**

  Include every limitation in the approved spec and conclude with scientific utility and validation needs.

- [ ] **Step 9: Update bibliography and README**

  Retain verified lineage references, add only directly used archive/catalogue/software references, document compilation and explain the archive/current layout.

### Task 4: Compile and inspect the revised paper

**Files:**
- Generate in Overleaf checkout: `build/wide_field_diagnostics.pdf`
- Modify in Overleaf checkout: `wide_field_diagnostics.pdf`

**Interfaces:**
- Consumes: revised TeX, bibliography and figures.
- Produces: a verified final PDF with resolved references and legible figures.

- [ ] **Step 1: Run a clean full LaTeX/BibTeX build**

  Run `latexmk -C` followed by `latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build wide_field_diagnostics.tex`.

- [ ] **Step 2: Check the build log**

  Fail on undefined citations/references, missing files, overfull boxes that obscure content, or fatal package warnings.

- [ ] **Step 3: Render every PDF page for visual inspection**

  Convert pages to PNG previews and inspect title/abstract, tables, every figure, captions, page breaks, bibliography and archive references.

- [ ] **Step 4: Search the manuscript for process-facing language**

  Check for headings or prose organized around `v4`, `v5`, `v6`, `v7`, `v8`, “added”, “development”, or “feature”. Keep a version string only when required for reproducibility.

- [ ] **Step 5: Copy the verified PDF to the project root**

  Copy `build/wide_field_diagnostics.pdf` to `wide_field_diagnostics.pdf` and record its SHA-256.

### Task 5: Synchronize Overleaf and the local solver repository

**Files:**
- Modify in solver repository: `reports/wide-field-diagnostics/**`
- Preserve in solver repository: `goBIG`

**Interfaces:**
- Consumes: the verified Overleaf checkout.
- Produces: matching Overleaf and local manuscript bundles with dedicated commits.

- [ ] **Step 1: Commit the Overleaf archive and revision**

  Stage only manuscript/archive files, inspect `git diff --cached --check`, and commit with a manuscript-specific message.

- [ ] **Step 2: Push the Overleaf main branch**

  Push to the existing project remote and verify the local branch matches its remote-tracking branch.

- [ ] **Step 3: Replace the local report bundle with the exact verified files**

  Synchronize TeX, bibliography, README, selected figures, provenance data and final PDF from the pushed Overleaf checkout into `reports/wide-field-diagnostics/`. Do not copy Overleaf `.git` metadata or temporary build files.

- [ ] **Step 4: Verify byte identity**

  Compare SHA-256 hashes for every synchronized source, figure, data and PDF file between Overleaf checkout and the local report directory.

- [ ] **Step 5: Run repository preservation and manuscript checks**

  Run the relevant manuscript build again locally, `git diff --check`, and checks that frozen runtime manifests, historical example evidence and `goBIG` are unchanged by this task.

- [ ] **Step 6: Commit and push only local manuscript changes**

  Stage `reports/wide-field-diagnostics/` and this plan/spec only as applicable, commit with a manuscript-specific message, and push `main`. Confirm `goBIG` remains modified but uncommitted.

- [ ] **Step 7: Report synchronization evidence**

  Report both commit IDs, push results, PDF page count and hash, selected MMTO run/input hashes, and the remaining unrelated working-tree status.
