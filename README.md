# WIDE-FIELD SOLVER

by Peter Thejll and Chris Flynn

Find stars in a wide-field image, identify them against a catalogue, fit the
Barghini fish-eye lens model, and produce an annotated scientific report.
This guide covers **`go.sh`, `go4.sh`, `go5.sh`, `go6.sh` and `go7.sh`**.

## 1. Choose a version

| | `go.sh` — legacy | `go4.sh` — preserved v4 | `go5.sh` — preserved v5 | `go6.sh` — preserved v6 | `go7.sh` — v7 |
|---|---|---|---|---|---|
| Use it for | Reproducing the established Tycho workflow | Reproducing Gaia v0.4.3 | Reproducing v0.5.0 | Reproducing v0.6.0 | New analyses with v0.7.0 and blind detector parity |
| Stellar catalogue | Tycho-2/Hipparcos | Gaia DR3 plus bright supplement | Gaia DR3 plus bright supplement | Gaia DR3 plus bright supplement | Gaia DR3 plus bright supplement |
| Planet analysis | Historical metadata-assisted diagnostics | Blind positional search | Blind search with absence evidence | Bundled reference and batched/parallel refinement | Metadata-conditioned local fit by default; full blind search by option/fallback |
| Repeated runs | Replace previous output | New folder per run | New folder per run | New folder per run | New folder per run |

All five versions are included and accept monochrome and RGB images. You do not
need to switch branches or edit code. `go_v0.4.3.sh` selects the preserved v4
release; `go_v0.5.0.sh`, `go_v0.6.0.sh` and `go_v0.7.0.sh` select v5, v6 and v7.
The versioned
packages each contain their own modules, catalogues and pinned dependencies.

## 2. Install

You need Git, Bash and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Linux is the tested platform. `uv` manages Python 3.12 and the pinned dependencies.

Install the dependencies for the versions you want to run:

```sh
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
uv sync --frozen
uv sync --project v4 --frozen
uv sync --project v5 --frozen
uv sync --project v6 --frozen
uv sync --project v7 --frozen
```

The first setup needs internet access to download dependencies. The stellar
catalogues are included. During analysis, ordinary star names may be looked up
online after fitting; those names never seed the astrometric solution.

If you already have this checkout, run the corresponding `uv sync` commands
from its root directory.

## 3. Run your image

Run **one** of these commands from the repository root. Quote paths containing spaces.

**Legacy Tycho-2:**

```sh
./go.sh "/full/path/to/image.jpg"
```

**Preserved Gaia v0.4.3:**

```sh
./go4.sh "/full/path/to/image.jpg"
```

**Gaia v0.5.0:**

```sh
./go5.sh "/full/path/to/image.jpg"
```

**Gaia v0.6.0 (faster planetary search):**

```sh
./go6.sh "/full/path/to/image.jpg"
```

**Gaia v0.7.0 (normal or mirrored detectors):**

```sh
./go7.sh "/full/path/to/image.fits"
```

Each command prints the PDF report location when finished. The Gaia launchers
also print their run folder and log location at startup. A complete run can take
several minutes, especially when bootstrap or planetary searches need more work.

### Where are the results?

| Command | Output folder | What happens on the next run? |
|---|---|---|
| `go.sh` | `results/IMAGE_STEM/` | The folder is replaced |
| `go4.sh` | `results/runs/IMAGE-v0.4.3-TIMESTAMP-UNIQUE/analysis/` | A new folder is created; the run log is alongside `analysis/` |
| `go5.sh` | `results/runs/IMAGE-v0.5.0-TIMESTAMP-UNIQUE/analysis/` | A new folder is created; the run log is alongside `analysis/` |
| `go6.sh` | `results/runs/IMAGE-v0.6.0-TIMESTAMP-UNIQUE/analysis/` | A new folder is created; the run log is alongside `analysis/` |
| `go7.sh` | `results/runs/IMAGE-v0.7.0-TIMESTAMP-UNIQUE/analysis/` | A new folder is created; the run log is alongside `analysis/` |

`IMAGE_STEM` means the input filename without its extension.
For `go4.sh` through `go7.sh`, open **`report.pdf`** in the printed output folder; its parent run
folder identifies the input image. Legacy `go.sh` retains its `report_*.pdf` name.

The v6 and v7 launchers automatically append every analysis to
`results/stars.sqlite`. Repeated images and quality-flagged measurements all
remain in the database; ordinary failures save their available partial results.
See [database storage](v6/docs/DATABASE.md). This feature was added after the
published v0.6.0 download; it is available in the updated checkout.

Regenerate the repeated-star photometry tables and plots from that database with:

```sh
./make_repeated_star_photometry_plots.sh
```

The wrapper is independent of the current directory. By default it reads
`results/stars.sqlite`, uses the v7 Gaia source-photometry table, and writes to
`results/subaru-repeated-star-colours/`. The underlying options can be overridden,
for example:

```sh
./make_repeated_star_photometry_plots.sh \
  --database /path/to/stars.sqlite \
  --output /path/to/plots
```

The output includes the complete repeated-star CSV, catalogue-colour diagrams,
the four-star RGB-pair grid, the nine-star airmass diagnostics, and the audited
bright/well-observed G-channel plot with shared axes and the `X <= 5` cutoff.
The catalogue-colour plots retain all measurements in the CSV but exclude from
the plotted fit and axis scaling observations more than six scaled MADs from a
preliminary per-star-median colour relation.  Each plot and its JSON audit state
the number excluded.  This conservative filter prevents isolated failed colour
measurements from obscuring the main relation without silently deleting them.

For v5, [bright-planet absence checks](v5/docs/PLANET_NONDETECTIONS.md) explain
how missing Mercury, Venus, Mars, Jupiter or Saturn can count against an epoch,
and when the image is too uncertain to judge.
V6 preserves those rules and adds a bundled 1850--2036 reference, batched exact
refinement and up to four planet workers. Its controlled benchmark measured a
[3.09x median planetary-stage speedup](v6/docs/PLANET_SEARCH_PERFORMANCE.md).
V7 preserves that science and adds blind normal/mirrored detector-parity
selection, propagated through coordinates, reports and FITS WCS products. Its
planet stage defaults to a ±1-day local fit when an explicit, FITS, EXIF or
filename observation time is available, and records the fitted timing error
against that reference. Use `./go7.sh IMAGE --blind-planets` for the inherited
full 1850-to-present search; missing metadata triggers that fallback automatically.

Other useful products include:

- `result.json`: fitted camera, residuals and provenance.
- `star_coordinates.csv`: measured positions, model predictions and catalogue identities.
- `stellar_photometry.csv`: instrumental fluxes, magnitudes and quality flags.
- In v5/v6/v7 `report.pdf`, page 3 compares camera R/G/B instrumental magnitudes
  with Gaia RP/G/BP in one row. Both magnitude axes put brighter stars toward
  the upper right; the displayed fit is ordinary least squares, with no 1:1 line.
- In Gaia results, `solution.fits`: image, ZPN coordinates and embedded overlays.
  Open with `./v4/view_fits.sh /path/to/solution.fits`; use DS9 **Region → Show**
  to toggle overlays, or use `./v5/view_fits.sh` for v5. See
  [v4 FITS export](v4/docs/FITS_EXPORT.md) and [v5 FITS export](v5/docs/FITS_EXPORT.md).
- In Gaia results, `planet_epoch.json` and `planet_candidates.csv`: the best planetary fit and retained alternatives.

## 4. Read the result

A successful plate solution does not guarantee that the observation date or
physical zenith has been determined. Read the reported status and uncertainty.
For the Gaia versions, thick hollow stars label the planets in the number-one candidate
fit. Thinner hollow stars labelled “predicted” show the other planets expected
in view at that same candidate epoch; they are not measured identifications.
Other date/identity alternatives remain in the numerical records.

All versions fit stellar astrometry and photometric zenith from the image and
reference catalogues without observation metadata. In v7 only, after those
results are fixed, observation time may bound the default planetary analysis;
the report labels it metadata-conditioned rather than blind.
The legacy analyser's metadata-assisted diagnostics retain their historical
behaviour. Instrumental image photometry is not automatically calibrated
astronomical photometry.

See [v4 capabilities and limitations](v4/docs/FEATURE_STATUS.md),
[v5 capabilities and limitations](v5/docs/FEATURE_STATUS.md), and
[v6 status](v6/docs/FEATURE_STATUS.md), and
[v7 status](v7/docs/FEATURE_STATUS.md) for each version's scientific status.

## Try the included example

```sh
./demo.sh --output results/example-check
```

This checks the preserved Tycho baseline from fresh image pixels. It produces
**3,653 catalogue associations at 0.398-pixel RMS**, with 40 named stars.
Use a new output folder if you want to retain an earlier example run.

To run the same historical regression through either Gaia-capable implementation:

```sh
./v4/demo.sh --output results/example-check-v4
./v5/demo.sh --output results/example-check-v5
./v6/demo.sh --output results/example-check-v6
./v7/demo.sh --output results/example-check-v7
```

All demo commands deliberately use the historical Tycho catalogue for comparison;
use `go4.sh` through `go7.sh` for the corresponding Gaia analysis.

![Preserved Milky Way example with 40 named stars](examples/milky_way/reference/identified_40_stars.png)

## More options and help

The one-command launchers above select the intended catalogue for you. Advanced
options belong to the corresponding analyser:

```sh
./analyse.sh --help       # legacy Tycho workflow
./v4/analyse.sh --help    # preserved Gaia v4 workflow
./v5/analyse.sh --help    # Gaia v5 workflow
./v6/analyse.sh --help    # Gaia v6 workflow
./v7/analyse.sh --help    # Gaia v7 workflow
```

For an advanced Gaia run, select its catalogue explicitly:

```sh
./v5/analyse.sh "/full/path/to/image.jpg" \
  --catalog v5/data/stars_gaia_dr3_g75.csv \
  --epoch-mode fit --output results/custom-gaia-run --offline
```

`--offline` disables online display-name queries. It does not change the
astrometric catalogue. Direct v4/v5 analysers default to Tycho when `--catalog`
is omitted; both Gaia launchers always supply Gaia. Use `v4/` in the advanced
command above for the preserved release.

- [Legacy commands, report details and residual diagnostics](docs/LEGACY_GUIDE.md)
- [Bootstrap failure diagnosis and recovery in v4](v4/docs/BOOTSTRAP_FAILURES.md)
- [Scientific goals](GOAL.md), [v4 feature status](v4/docs/FEATURE_STATUS.md) and [v5 feature status](v5/docs/FEATURE_STATUS.md)
- [Historical solve-field comparison](docs/COMPARISON.md)
- [Tycho catalogue provenance](data/README.md) and [Gaia catalogue provenance](v4/data/README.md)
- [Preservation and developer instructions](docs/CONSOLIDATION.md)
- [Attribution and redistribution notice](NOTICE.md)

The original `v0.1.0` tag and historical reference products are preserved.
New changes stay in `v7/`. The legacy Tycho, v0.4.3, v0.5.0 and v0.6.0 runtimes
and launchers remain preserved; the [v4](docs/v4-runtime.json),
[v5](docs/v5-runtime.json) and [v6](docs/v6-runtime.json) hash manifests record
those checkpoints.
