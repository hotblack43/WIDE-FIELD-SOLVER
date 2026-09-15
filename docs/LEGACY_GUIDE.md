# Detailed guide: legacy Tycho-2 solver

This page applies to `go.sh` and the preserved root commands. It does not describe
`go4.sh`. Start with the [shared user guide](../README.md) to choose a version.
Run the commands below from the repository root.

The legacy analyser retains its historical metadata-assisted atmospheric and
planet diagnostics. For blind planetary epoch inference, use `go4.sh` and read
its [feature status](../v4/docs/FEATURE_STATUS.md).

## Solve another image

```sh
./solve.sh /path/to/stars.jpg --output results/my-image --labels 40
```

An existing output directory is replaced by default so the command can be
rerun with the same name. Add `--no-overwrite` to preserve an existing output
and fail instead.

This queries SIMBAD for display names. Add `--offline` to retain catalogue
identifiers without network access, or also supply `--names-cache names.json`.
Supported input is a raster image readable by Pillow, converted to 8-bit RGB.
This first release is tuned and demonstrated on the included fisheye image;
success across arbitrary cameras and fields remains to be established.

If detection succeeds but the run ends with
`No blind catalogue bootstrap from the measured training dots`, see the
[blind-bootstrap failure diagnosis](BOOTSTRAP_FAILURES.md). It records a
confirmed working point-source control, the diagnosed Paranal failure, the
current tetra3 search limits, and the requirements for improving bootstrap
robustness without withholding sources or weakening the historical regression.

For the complete per-image analysis, use the standalone entrypoint:

```sh
./analyse.sh /path/to/stars.jpg --output results/my-image --offline
```

It starts from the image, performs the Barghini astrometric and lens fit, measures
RGB aperture photometry, fits empirical refraction, profiles the stellar
proper-motion epoch, fits
`green machine magnitude - catalogue magnitude = zero point + k * airmass`,
and matches ephemeris planets to unused measured point sources. One matched
bright source is retained as a lower-confidence planet candidate; two matches
can support the epoch and three or more can provide strong evidence.

For an OMRcam archive image, the analyser reads the camera-server time from the
adjacent `manifest.jsonl` and uses the ORM site. Supply an approximate UTC time
and site for another image:

```sh
./analyse.sh /path/to/stars.jpg --output results/my-image --offline \
  --observation-time 2026-09-13T22:00:00 \
  --latitude 28.7606 --longitude -17.8850 --elevation-m 2326
```

The time supplies the centre of a ±366-day planet search. The analyser classifies
the stored channels as RGB or effectively monochrome from their pixel values.
RGB images receive separate R, G and B photometry/extinction panels; effectively
monochrome images receive one panel. The report distinguishes a single candidate,
a supported result and a strong result, and records competing daily minima. `report_<camera>_<UTC>.pdf` has two A4 portrait pages. Page 1 contains two numbered figures,
Table 1 and short interpretation text. Page 2 contains the fixed lens and refraction
formulae without image-specific fitted values, for double-sided printing. A boundary-limited stellar epoch or an
unsupported refraction term is reported as unresolved.

For detection alone:

```sh
uv run --frozen python point_star_detection.py /path/to/stars.jpg --output results/dots
```

To change labels on an existing solution without refitting:

```sh
./solve.sh examples/milky_way/input.jpeg --annotations-from results/demo \
  --output results/relabelled --labels 20 --offline \
  --names-cache examples/milky_way/reference/display_names.json
```

Each complete run produces:

- `result.json`: fitted camera, convergence, residuals, processing history and checksums.
- `star_coordinates.csv`: measured and predicted pixels, catalogue coordinates and IDs.
- `blob_candidates.csv`: broad/saturated sources, including unmatched objects.
- `identified_40_stars.png`: the requested number of named stars (40 by default).
- `astrometry_overlay.png`: measured cyan crosses and predicted orange circles at their true positions; unmatched detections are pink crosses.
- `astrometry_residuals.png`: residual vectors magnified ×20 and centre-to-edge residual statistics.
- `radial_residuals.csv` / `.json`: counts, RMS, median, 90th percentile and signed radial offsets by image-centred annulus.
- `report_<camera>_<UTC>.pdf`: two-page scientific report; results on page 1 and formulae on page 2.
- `science_summary.json`: stellar epoch, refraction, photometry/extinction and planet results.
- `stellar_photometry.csv` and `extinction_fit.png`: aperture measurements and the fitted magnitude-difference relation; colour images receive separate R, G and B panels.
- `report_sky_overlay.png`: readable representative star labels and distinct matched-planet symbols.
- `stellar_epoch.json` and `stellar_epoch_profile.png`: proper-motion epoch profile and identifiability.
- `refraction_fit.json`: empirical tangent-series refraction fit and model-selection diagnostics.
- `planet_epoch.json`, `planet_matches.csv` and `planet_candidates.png`: measured-source planet matches and conditional epoch, when present.
- `dots/`, `bootstrap.json`, `display_names.json`, `labelled_stars.json`: measurement and naming audit.

## Does the fit deteriorate towards the edge?

The [two-symbol overlay](../examples/milky_way/diagnostics/astrometry_overlay.png)
plots both coordinates independently for all 3,653 fitted associations, without
magnifying their separation. Open the full-resolution image and zoom in.
The plotting code applies no astrometric correction or cosmetic shift. Any
future correction must come through the Barghini model and its exported
coordinates; remaining discrepancies stay visible in the overlay.

![Full-field residual vectors and centre-to-edge residual statistics](../examples/milky_way/diagnostics/astrometry_residuals.png)

The radial bands give:

| Distance from image centre | Fitted stars | RMS | 90th percentile |
|---|---:|---:|---:|
| 0–200 px | 405 | 0.536 px | 0.806 px |
| 200–400 px | 1,179 | 0.379 px | 0.562 px |
| 400–600 px | 1,548 | 0.343 px | 0.492 px |
| 600–800 px | 521 | 0.461 px | 0.711 px |

There is a modest outer-band rise, with no progressive edge blow-up in these
matched stars. Small systematic structure remains visible in the magnified
vectors; for example, the inner band has a mean outward radial offset of
0.329 px. The outermost matched source is at radius 734.75 px, so the last
populated band is only partially sampled. The hatched part of the plot has
no matched sources and is untested. All fitted pairs are included, with no
extra residual clipping. These remain fit residuals after catalogue matching;
unmatched detections have no evaluated star-pair residual.

A field identification and a good distortion correction are separate aspects
of astrometry. Astrometry.net fits
[polynomial distortion terms](https://astrometry.net/doc/readme.html);
an insufficient or poorly constrained distortion model can plausibly explain
good central alignment with increasing edge errors. Diagnosing an old solve
would require its WCS and measured positions. This image's comparison does
not establish that every astrometry.net configuration has such a problem.

Regenerate diagnostics from an existing solve, without refitting:

```sh
uv run --frozen python point_star_diagnostics.py examples/milky_way/input.jpeg \
  --solution results/demo --output results/diagnostic-check
```

## Method and scope

The detector measures intensity centroids with local background subtraction,
growing its window to accommodate large saturated blobs. tetra3 supplies an
initial blind star-pattern identification from a small patch. The global fit
uses the [Barghini et al. (2019)](https://doi.org/10.1051/0004-6361/201935580)
O/Z equations (5), (6), and (11), with progressive matching and a robust fit.
See [method notes](METHOD.md) and [catalogue provenance](../data/README.md).

The reported residuals describe fitted associations selected with a three-pixel
matching gate. They are not independent accuracy estimates or a completeness
measurement. The celestial reference direction Z does not establish a local zenith.
The complete analyser fits an empirical zenith/refraction model from the
astrometric residuals and uses a supplied or archived site/time for airmass and
planet ephemerides. Broad and saturated blobs remain measured candidates until
a stellar or planetary position matches them.

In our bounded [solve-field comparison](COMPARISON.md), direct full-image
attempts were unsolved. On a small crop, solve-field with our measured dots
and third-order SIP achieved comparable local precision. The demonstrated
benefit here is the full-field lens solution.

## Keeping this result safe

This project contains its own code, catalogue, example and dependency lock.
It has no runtime dependency on the trail-processing repository. The
**`v0.1.0` tag** preserves the first verified standalone release; that release remains recoverable:

```sh
git switch --detach v0.1.0
uv sync --frozen
./demo.sh --output results/baseline-replay
```

The checked-in `examples/milky_way/reference/` holds the original annotated
image and association tables. `baseline.json` records both exact observations
and explicit cross-platform acceptance bounds. CI runs the synthetic/unit
checks and a fresh pixel-to-sky demo on pushes and pull requests.
It also reloads the saved camera, reproduces the exported coordinates and
residuals, and checks catalogue identities against the reference table.

```sh
uv run --frozen python -m unittest discover -v
./demo.sh --output results/regression-1
```

The tests cover subpixel centroids, saturated blobs, streak rejection, forward
and inverse geometry, recovery of a synthetic distorted field, spatial label
selection, offline names and rejection of degraded regression results.

See the [performance profile](PERFORMANCE.md) for measured runtime
hotspots and the lossless PNG-encoding optimization.
