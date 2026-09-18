# Results and outputs

Each v0.9.0 invocation creates a unique directory beneath `results/runs/`, or
beneath the directory selected with `--results-dir`. A failed analysis retains
the partial products and log that were available when it stopped.

## Investigator-facing products

| Product | Purpose |
|---|---|
| `analysis/report.pdf` | Illustrated summary of detections, astrometry, photometry and status |
| `run.log` | Complete console record for diagnosis and provenance |
| `analysis/result.json` | Fitted camera, residual statistics, status and provenance |
| `analysis/star_coordinates.csv` | Measured centroids, model predictions and catalogue identities |
| `analysis/stellar_photometry.csv` | Identified-star instrumental measurements and quality flags |
| `analysis/source_photometry.csv` | Measurements for every detected source |
| `analysis/identified_source_photometry.csv` | Combined identified stars and planetary candidates |
| `analysis/planet_candidates.csv` | Retained planetary alternatives and positional evidence |
| `stars.sqlite` | Append-only record of all runs under the results root |

Additional JSON, CSV, FITS and PNG products preserve intermediate evidence and
plot inputs. Their exact availability depends on which scientific stages could
be run for the image.

## Reading residuals

V0.9.0 leads with great-circle residuals in arcminutes because a pixel covers
very different angles in different cameras. Pixel residuals remain valuable
when comparing reductions of the same detector.

For the representative MMTO image:

| Statistic | Pixels | Arcminutes |
|---|---:|---:|
| RMS | 0.3267 | 2.502 |
| Median | 0.2350 | 1.738 |
| 90th percentile | 0.4964 | 3.933 |

The sample contains 1,380 fitted catalogue associations and no withheld-star
set. Do not describe these numbers as independent prediction error.

## Status is part of the result

The report may distinguish, among other states:

- a converged astrometric fit;
- a conditional, provisional or non-identifiable stellar epoch;
- a provisional or non-identifiable physical zenith;
- metadata-conditioned planetary timing;
- an ambiguous single-planet positional alias; and
- unavailable FITS WCS export when the fitted whole-detector radial mapping is
  not invertible over the required domain.

These qualifications are scientific output, not merely warning messages.
