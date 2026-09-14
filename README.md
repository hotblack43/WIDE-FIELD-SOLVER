# WIDE-FIELD SOLVER

by Peter Thejll and Chris Flynn

Astrometry directly from untrailed, wide-field star images, using the
Barghini O/Z fish-eye model. Find dots, identify a small star pattern, then
fit the lens across the image.

The included Milky Way example yields **3,653 catalogue associations at
0.398-pixel RMS**, with 40 spatially distributed star labels. All detected
sources are available for fitting; no stars are withheld.

![Forty identified stars across the Milky Way fisheye image](examples/milky_way/reference/identified_40_stars.png)

## Try the preserved example

Requires Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Python 3.12 and the exact dependency versions are recorded in the repository.
Linux is the tested platform; the shell entrypoints also require Bash.

```sh
git clone git@github.com:hotblack43/WIDE-FIELD-SOLVER.git
cd WIDE-FIELD-SOLVER
uv sync --frozen
./demo.sh
```

Open `results/demo/identified_40_stars.png`. The demo starts from the included
JPEG and runs detection, blind identification, and the complete Barghini fit
anew. It then checks the numerical result against the preserved baseline.
The cached ordinary names are used only when drawing labels. No saved camera,
star associations, date, location or sky-position hint seeds the solution.

Installation downloads dependencies, including tetra3's bundled pattern
database. The installed demo runs offline. Allow a few minutes on a typical
machine. Outputs are never overwritten: for another run use
`./demo.sh --output results/demo-2`.

| Included example, 1569 × 1444 pixels | Verified baseline |
|---|---:|
| Measured sources | 3,688 |
| Catalogue associations | 3,653 |
| Fitted residual RMS / median | 0.398 / 0.249 px |
| Broad blobs / saturated sources | 82 / 930 (overlapping categories) |
| Unmatched measurements | 35 |
| Distributed star labels | 40 |

Names favour Bayer designations such as α Ori and α² Cap, followed by common
names, Flamsteed designations or catalogue identifiers. Selection favours
bright, compact matches below one pixel residual and spreads labels across
the field.

## Solve another image

```sh
./solve.sh /path/to/stars.jpg --output results/my-image --labels 40
```

This queries SIMBAD for display names. Add `--offline` to retain catalogue
identifiers without network access, or also supply `--names-cache names.json`.
Supported input is a raster image readable by Pillow, converted to 8-bit RGB.
This first release is tuned and demonstrated on the included fisheye image;
success across arbitrary cameras and fields remains to be established.

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
- `dots/`, `bootstrap.json`, `display_names.json`, `labelled_stars.json`: measurement and naming audit.

## Does the fit deteriorate towards the edge?

The [two-symbol overlay](examples/milky_way/diagnostics/astrometry_overlay.png)
plots both coordinates independently for all 3,653 fitted associations, without
magnifying their separation. Open the full-resolution image and zoom in.
The plotting code applies no astrometric correction or cosmetic shift. Any
future correction must come through the Barghini model and its exported
coordinates; remaining discrepancies stay visible in the overlay.

![Full-field residual vectors and centre-to-edge residual statistics](examples/milky_way/diagnostics/astrometry_residuals.png)

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
See [method notes](docs/METHOD.md) and [catalogue provenance](data/README.md).

The reported residuals describe fitted associations selected with a three-pixel
matching gate. They are not independent accuracy estimates or a completeness
measurement. The celestial reference direction Z does not establish a local
zenith. Observation epoch, atmospheric refraction and terrestrial orientation
are outside this release. Broad blobs remain unclassified objects; identifying
planets requires further information.

In our bounded [solve-field comparison](docs/COMPARISON.md), direct full-image
attempts were unsolved. On a small crop, solve-field with our measured dots
and third-order SIP achieved comparable local precision. The demonstrated
benefit here is the full-field lens solution.

## Keeping this result safe

This project contains its own code, catalogue, example and dependency lock.
It has no runtime dependency on the trail-processing repository. The
**`v0.1.0` tag** preserves the first verified standalone release; future work
can proceed on `main` while that release remains recoverable:

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

## Future extensions

- **RGB photometry and horizon-constrained extinction:** see the
  [deferred research note](docs/PHOTOMETRY_ZENITH_EXTINCTION_NOTE.md) for Peter's
  proposed equal-airmass consistency test of the zenith, its inputs and caveats.
- **Bright stars plus Gaia DR3/DR4 instead of Tycho:** develop a Gaia-based
  reference catalogue with an explicit bright-star supplement, cross-matching
  and epoch propagation; evaluate DR4 when its data are available.
- Test more fisheye lenses, sky regions and exposure levels, with documented
  limits on where the solution is trustworthy.
- Add optional observation time/location, refraction modelling and planetary
  identification for suitable bright blobs.
- Export a convenient pixel-to-sky interface and interoperable astrometric
  products for downstream analysis.

These are development directions; the tagged baseline retains the catalogue
and method that produced the demonstrated result.

## Provenance

Preserved from Peter Thejll's point-star experiments on 13 September 2026.
This is a private research repository. The supplied photograph's original
photographer and redistribution terms are undocumented; see [NOTICE](NOTICE.md)
before any public release. Third-party catalogue and software sources are
identified there.
