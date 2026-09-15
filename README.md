# WIDE-FIELD SOLVER

by Peter Thejll and Chris Flynn

Find stars in a wide-field image, identify them against a catalogue, fit the
Barghini fish-eye lens model, and produce an annotated scientific report.
This guide covers **both `go.sh` and `go4.sh`**.

## 1. Choose a version

| | `go.sh` — legacy | `go4.sh` — upgraded |
|---|---|---|
| Use it for | Reproducing the established Tycho workflow | New analyses with the Gaia solver and later improvements |
| Stellar catalogue | Tycho-2/Hipparcos | Gaia DR3 with a bright-star supplement |
| Planet analysis | Historical metadata-assisted diagnostics | Blind search for a common date and planet identifications |
| Recent improvements | Preserved historical behaviour | Proper-motion/epoch fitting, photometric zenith, planet visibility checks, bootstrap recovery and revised reports |
| Repeated runs | Replace the same image's previous output | Create a separate folder for every run |

Both versions are included. You do not need to switch branches or edit code to
choose between them. Both accept monochrome and RGB images.

## 2. Install

You need Git, Bash and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Linux is the tested platform. `uv` manages Python 3.12 and the pinned dependencies.

The default `main` branch contains both commands:

```sh
git clone https://github.com/hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
uv sync --frozen
uv sync --project v4 --frozen
```

The first setup needs internet access to download dependencies. The stellar
catalogues are included. During analysis, ordinary star names may be looked up
online after fitting; those names never seed the astrometric solution.

If you already have this checkout with both commands, run the two `uv sync`
commands from its root directory.

## 3. Run your image

Run **one** of these commands from the repository root. Quote paths containing spaces.

**Legacy Tycho-2:**

```sh
./go.sh "/full/path/to/image.jpg"
```

**Upgraded Gaia:**

```sh
./go4.sh "/full/path/to/image.jpg"
```

Each command prints the PDF report location when finished. The Gaia launcher
also prints its run folder and log location at startup. A complete run can take
several minutes, especially when bootstrap or planetary searches need more work.

### Where are the results?

| Command | Output folder | What happens on the next run? |
|---|---|---|
| `go.sh` | `results/IMAGE_STEM/` | The folder is replaced |
| `go4.sh` | `results/runs/IMAGE-v0.4.3-TIMESTAMP-UNIQUE/analysis/` | A new folder is created; the run log is alongside `analysis/` |

`IMAGE_STEM` means the input filename without its extension.
For `go4.sh`, open **`report.pdf`** in the printed output folder; its parent run
folder identifies the input image. Legacy `go.sh` retains its `report_*.pdf` name.

Other useful products include:

- `result.json`: fitted camera, residuals and provenance.
- `star_coordinates.csv`: measured positions, model predictions and catalogue identities.
- `stellar_photometry.csv`: instrumental fluxes, magnitudes and quality flags.
- In `go4.sh` results, `planet_epoch.json` and `planet_candidates.csv`: the best planetary fit and retained alternatives.

## 4. Read the result

A successful plate solution does not guarantee that the observation date or
physical zenith has been determined. Read the reported status and uncertainty.
For `go4.sh`, thick hollow stars label the planets in the number-one candidate
fit. Thinner hollow stars labelled “predicted” show the other planets expected
in view at that same candidate epoch; they are not measured identifications.
Other date/identity alternatives remain in the numerical records.

`go4.sh` fits from the image and reference catalogues. Observing time and site
are reserved for a separately requested comparison after the blind fits.
The legacy analyser's metadata-assisted diagnostics retain their historical
behaviour. Instrumental image photometry is not automatically calibrated
astronomical photometry.

See [v4 capabilities and limitations](v4/docs/FEATURE_STATUS.md) for the current
scientific status.

## Try the included example

```sh
./demo.sh --output results/example-check
```

This checks the preserved Tycho baseline from fresh image pixels. It produces
**3,653 catalogue associations at 0.398-pixel RMS**, with 40 named stars.
Use a new output folder if you want to retain an earlier example run.

To run the same historical regression through the upgraded implementation:

```sh
./v4/demo.sh --output results/example-check-v4
```

Both demo commands deliberately use the historical Tycho catalogue for comparison;
use `go4.sh` for the normal Gaia analysis.

![Preserved Milky Way example with 40 named stars](examples/milky_way/reference/identified_40_stars.png)

## More options and help

The one-command launchers above select the intended catalogue for you. Advanced
options belong to the corresponding analyser:

```sh
./analyse.sh --help       # legacy Tycho workflow
./v4/analyse.sh --help    # upgraded workflow
```

For an advanced Gaia run, select its catalogue explicitly:

```sh
./v4/analyse.sh "/full/path/to/image.jpg" \
  --catalog v4/data/stars_gaia_dr3_g75.csv \
  --epoch-mode fit --output results/custom-gaia-run --offline
```

`--offline` disables online display-name queries. It does not change the
astrometric catalogue. The direct v4 analyser defaults to Tycho when `--catalog`
is omitted; the `go4.sh` launcher always supplies Gaia.

- [Legacy commands, report details and residual diagnostics](docs/LEGACY_GUIDE.md)
- [Bootstrap failure diagnosis and recovery in v4](v4/docs/BOOTSTRAP_FAILURES.md)
- [Scientific goals](GOAL.md) and [v4 feature status](v4/docs/FEATURE_STATUS.md)
- [Historical solve-field comparison](docs/COMPARISON.md)
- [Tycho catalogue provenance](data/README.md) and [Gaia catalogue provenance](v4/data/README.md)
- [Preservation and developer instructions](docs/CONSOLIDATION.md)
- [Attribution and redistribution notice](NOTICE.md)

The original `v0.1.0` tag and historical reference products are preserved.
Changes to the Gaia implementation are kept separate from the legacy Tycho code.
