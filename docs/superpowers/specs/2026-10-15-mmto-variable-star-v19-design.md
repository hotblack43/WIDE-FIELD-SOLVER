# MMTO Short-Period Variable-Star V19 Design

Date: 2026-10-15

## Purpose

Create a new v0.19.0 MMTO line based directly on frozen v0.16.0. V19 adds a
pipeline product showing nightly flux-averaged extinction-corrected machine
magnitudes of confirmed catalogue variable stars. The default strict selection
is `5 < period < 30` days and catalogue magnitude `< 5.0`. Every figure and data
product already produced by v16 remains present and unchanged; the
variable-star time-series products are additions.

This is a new version. V16, v17, v18, all existing launchers, and all existing
result directories remain unchanged.

## Version boundary

- Copy the complete v16 runtime into a new `v19/` runtime and deliberately
  update its version metadata and source manifest.
- Add `go19.sh`, `go_v0.19.0.sh`, and `go_mmto_photometry_v19.sh`.
- Preserve `go16.sh`, `go17.sh`, `go18.sh`, their version-specific aliases,
  their version directories, and their pipeline launchers byte for byte.
- V19 processing receipts use solver version `0.19.0`. A normal v19 pipeline
  invocation follows the v16 newest-incomplete-night processing policy while
  recognizing only v19 receipts as v19 work. It does not inherit v18's bounded
  downloader/backlog subsystem.
- No branch or worktree is created.

## Variable-star catalogue

V19 owns a frozen, local variable-star cross-match derived from the AAVSO
International Variable Star Index (VSX). Runtime plotting is offline and never
depends on a live network query.

The cross-match records the local stellar catalogue ID, VSX OID and name,
variability flag and type, period in days, angular match distance, catalogue
version/date, and retrieval provenance. Positions are propagated to the VSX
J2000 frame before matching. The positional gate is 1.0 arcsecond. Only VSX
rows whose variability flag is `0` (variable), whose period is finite and
positive, and whose match is unique inside that gate are eligible. Multiple
local catalogue IDs may share one VSX OID, but one local ID matching multiple
VSX OIDs is ambiguous. Suspected variables, constants, missing periods, and
ambiguous matches remain in an audit product but do not enter the figure.

The catalogue is post-fit diagnostic metadata. It cannot seed source
identification, astrometry, photometric zenith, refraction, or planet work.

## Photometric quantity

The plot consumes the v19 pipeline's existing nightly stellar-extinction
product after the nightly calibration stage. For each accepted row and native
camera channel:

```text
m_corrected = m_machine - k_night,channel * X
m_machine = -2.5 log10(count_rate_ADU_per_second)
```

No distance correction, catalogue zero-point correction, phase normalization,
or cosmetic vertical shift is applied. The figure and CSV label the ordinate
as extinction-corrected instrumental machine magnitude. Rows without an
accepted nightly extinction coefficient or usable unsaturated aperture
photometry are omitted from the plotted measurements and retained with an
explicit exclusion reason in the audit.

For each physical VSX object, MMTO observing night, and native channel, the
qualifying corrected magnitudes are converted to relative flux, averaged, and
converted back to one magnitude:

```text
m_night = -2.5 log10(mean(10^(-0.4 m_corrected)))
```

The plotted UTC coordinate is the median UTC of the contributing exposures.
The nightly CSV records that time, the observing-night key, contribution count,
catalogue magnitudes, catalogue IDs, and source hashes. The measurement audit
retains each unaggregated input row.

## Fixed-period sinusoidal fits

Each native channel is fitted independently to its nightly flux-averaged
magnitudes. The catalogue period is fixed and unweighted linear least squares
solves the equivalent cosine and sine coefficients of

```text
m(t) = mean - semi_amplitude *
       cos(2 pi ((t - reference_utc) / period - phase_brightest))
```

`reference_utc` is the earliest plotted nightly UTC across all channels for the
physical VSX object. `phase_brightest` is normalized to `[0,1)` and denotes the
minimum-magnitude, brightest-light phase after that common reference. Each fit
therefore also reports the phase offset in days and the first corresponding
brightest epoch after the reference.

A channel requires at least three nightly points and a rank-three design matrix
(three independent sampled phases). Otherwise it receives an explicit
`insufficient_nightly_points` or `insufficient_independent_phases` status. A
zero-amplitude solution has no defined phase and is separately labelled. The
fit is descriptive: it does not change, reject, phase-fold, or distance-correct
the plotted measurements.

## Selection and configurability

The standalone plot command accepts `--min-period-days FLOAT` and
`--max-period-days FLOAT`, defaulting to `5.0` and `30.0`. Selection is strictly
`min_period_days < period < max_period_days`. It also accepts
`--max-catalogue-magnitude FLOAT`, defaulting to `5.0`, and requires each
contributing local-catalogue measurement to be strictly brighter than that
limit. The v19 MMTO pipeline exposes the same controls with the `--variable-`
prefix and passes them to the plot stage.

The standalone plot command also accepts `--start-utc`, defaulting to
`2026-06-30T00:00:00Z`; the pipeline exposes it as `--variable-start-utc`.
This applies only to the added variable-star products and excludes the isolated
March 2026 observation. The row remains in the database and is recorded in the
variable-star audit as preceding the time-series boundary. It is not removed
from, or hidden in, any of the ordinary v16-derived products.

Each pipeline run rereads the complete database snapshot and regenerated
nightly-extinction table, so newly fetched and solved MMTO images automatically
extend the plotted light curves. Changing the period or brightness limits later
requires only command-line options; it does not require a code or catalogue
change.

## Figure and data products

The main product is one multipage PDF of chronological time series. Each panel
represents one physical VSX object and overlays one nightly flux-averaged R, G,
or B point per available channel against the median UTC of that night's
contributing exposures. Points are sorted chronologically within each channel.
Magnitude axes are inverted. No phase folding is performed. Each title gives
the ordinary VSX name, type, period, and number of plotted nightly points. A
shared legend appears once per page, and the selection limits are printed on
every page. Fitted channels also show a thin same-colour sinusoid across the
chronological time span and a panel annotation giving the brightest-light phase.

Pages contain twelve panels in a 4-by-3 layout. Stars are ordered by increasing
period and then name. Catalogue IDs that map to the same unambiguous VSX OID
share one panel, preventing the v16 Tycho/Hipparcos and Gaia lineages from
creating duplicate physical-star panels. The PDF may therefore grow to many
pages without silently dropping eligible stars.

The output directory also contains:

- the exact plotted nightly-average table as CSV;
- a one-row-per-object/channel fixed-period sine-fit CSV containing the common
  reference UTC, point count, brightest phase in cycles and days, first
  brightest epoch, mean magnitude, semi-amplitude, RMS, and fit status;
- a one-row-per-candidate star-selection audit;
- a one-row-per-input-measurement audit recording whether the row was plotted
  and, when it was not, the exact reason such as `before_start_utc`;
- a JSON summary containing both period limits, the catalogue-magnitude limit,
  extinction and flux-average formulas, catalogue provenance, UTC boundary,
  input hashes, selected-star/page/nightly-point/contributing-measurement
  counts, per-channel counts, excluded-pre-boundary count, and output names.

If the inputs are valid but no star has a qualifying corrected measurement,
the command writes a one-page explanatory PDF plus empty, schema-valid CSV and
summary products. Missing or malformed required inputs are operational errors.

## Pipeline integration

`go_mmto_photometry_v19.sh` runs the v19 solver and retains the established v16
products. Its post-processing order is:

1. ordinary stellar light curves;
2. nightly stellar extinction calibration;
3. short-period variable-star corrected light curves;
4. standard planetary photometry;
5. planet-only empirical-extinction diagnostics.

The variable-star stage receives the newly written nightly-extinction output,
the frozen v19 VSX cross-match, the configurable period and catalogue-magnitude
limits, and the UTC boundary. Its PDF is included automatically in the pipeline's final figure
listing and its paths are recorded in `pipeline_summary.json`. All other stage
arguments, products, and behavior remain those of v16.

## Verification

Tests cover both exclusive period boundaries, the exclusive catalogue-magnitude
boundary, VSX flag and ambiguity gates, Tycho/Gaia deduplication by VSX OID,
flux-space nightly averaging, the exact `m_machine - kX` inputs, absence of
distance correction, exact synthetic sine phase recovery, insufficient-point
and rank-deficient fit auditing, plotted curve overlays, R/G/B inclusion,
chronological ordering, exclusion and
auditing of pre-boundary rows, audit reasons, empty-data behavior, multipage
completeness, CLI propagation, pipeline stage ordering, v19 runtime ownership,
and preservation of v16-v18 bytes. V18 preservation is checked from a
before/after tree-hash snapshot without adding or changing anything in v18.

Before completion, run the focused tests, the full frozen unit suite, the root
demo required by `AGENTS.md`, the v19 demo, and a real read-only plot generation
against the current MMTO database and a fresh nightly-extinction output.
