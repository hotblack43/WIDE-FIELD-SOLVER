# V23 performance and database notes, 7 November 2026

## Runtime changes

- MMTO image solving now uses four independent single-threaded v23 workers by
  default. `--solver-workers N` changes the bound; `--solver-workers 1`
  restores the former serial resource profile.
- Routine batch solves invoke the pinned v23 interpreter directly and use the
  bundled display-name cache offline. This removes repeated launcher startup
  and display-only SIMBAD waits without changing the fitted science products.
- Planet R, G, and B plotting now runs in one Python process. A source FITS is
  checksum-verified and decoded once for all three channel uncertainty
  calculations, and the distance ephemeris lookup is shared.

On the same accumulated v23 run, the planet R/G/B stage fell from about
24 minutes to about 12 minutes. The plotted populations were unchanged:

| Channel | Corrected points | Open distance-only points |
| --- | ---: | ---: |
| R | 757 | 176 |
| G | 602 | 145 |
| B | 843 | 184 |

The comparison output is below
`results/photometry-runs/v23-20261107T075105Z/planet-photometry/` on the results
volume.

## Results database contents

The 37 GB append-only SQLite database did not contain FITS files, rendered
images, or PDFs. Its size came primarily from deduplicated JSON measurement
and text-product payloads plus their run references:

| Population before cleanup | Count |
| --- | ---: |
| Runs | 2,812 |
| Product-content rows | 62,496 |
| Product references | 97,419 |
| Measurement-content rows | 10,841,635 |
| Measurement references | 18,581,210 |

The stored product payload was 17,078,480,704 bytes and the measurement JSON
payload was 10,284,232,312 bytes. Individual source images remained on the
filesystem; database receipts reference their paths and checksums.

At Peter's request, receipts and payloads reachable only from solver versions
`0.16`, `0.19`, `0.20`, `0.21`, and versionless failed runs were removed. The
cleanup deleted 2,206 runs, 12,073,727 measurement references, 61,102 product
references, 6,250,420 unreferenced measurement-content rows, and 36,807
unreferenced product-content rows. Original FITS files and analysis directories
were not removed.

After `VACUUM`, the database is 15,365,881,856 bytes (14.31 GiB), about
22.1 GiB smaller. It contains only solver `0.23.0`: 606 successful runs for
606 distinct source hashes, 4,591,215 measurement-content rows, 6,507,483
measurement references, 25,689 product-content rows, and 36,317 product
references. SQLite integrity and foreign-key checks passed, and the freelist is
empty. The 606 runs are one receipt per distinct v23-processed source image,
not 606 invocations of the top-level pipeline.

## Verification state

The focused v23 plotting, launcher, pipeline, and runtime-boundary suite passes
78 tests. The repository-wide discovery command was also run, but the current
checkout is not globally green: it reports 8,173 frozen-v12 boundary errors for
missing manifest-listed `__pycache__` files and one results-symlink path
expectation failure in the nightly-extinction test. These failures are outside
the active v23 changes and are recorded here rather than hidden by weakening
their assertions.
