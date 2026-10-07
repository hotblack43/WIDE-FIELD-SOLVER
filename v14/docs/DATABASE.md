# Automatic run database

Run `./go11.sh /full/path/to/image.jpg` as usual. The launcher automatically passes
`--database RESULTS_DIRECTORY/stars.sqlite` to the analysis process. Select the
results directory with `--results-dir PATH`, `WFS_RESULTS_DIR`, or the per-host
setting documented in `../README.md`; without a setting it is
`REPOSITORY/results`. The database
is created on the first analysis. The versioned launcher uses the same storage.
There is no database enable/disable step in the launcher.

Every invocation that enters analysis appends a fresh UUID run record. Identical
image hashes, identical measurements, and repeated imports are all retained.
There is no logical de-duplication, photometric quality cut, or unique constraint on star
IDs or image hashes. Duplicate elimination and repeated-star extraction are left
for subsequent analysis. Catalogue identifiers are text, preserving full Gaia
integer IDs and their catalogue prefix; display aliases never identify a star.

Storage happens after scientific processing, including on ordinary exceptions
and Python keyboard interruption. Failed analyses store their available outputs
with `exit_code=1` and the error; they are not silently discarded. Argument errors
before analysis and hard process termination (SIGKILL, power loss) cannot be
recorded by this finalization step. Database errors fail the command visibly and
the original run files remain available. Each database append is transactional;
concurrent writers wait up to 60 seconds for the writer lock.

## Contents

- `runs`: UUID, recording time (not observation time), image path and SHA-256,
  analysis directory, process status/error, solver and catalogue provenance,
  complete saved `result.json`, recorder hash and source manifest.
- `products`: exact bytes and SHA-256 for every saved JSON, CSV and TXT product,
  including camera parameters, photometric zenith, extinction, stellar/planetary
  epochs, competing planet candidates, quality flags and explicit metadata
  comparisons when present. Original files remain authoritative.
- `measurements`: every row of every CSV product as JSON, indexed by run,
  product, catalogue star ID and detection ID. Includes unmatched detections,
  rejected detections, broad/saturated blobs and all available colour channels.
- `star_measurements`: SQL view joining saved stellar associations to photometry
  and detections within each run, preserving associations without photometry.

CSV values deliberately remain strings in the row JSON: blank fields, `nan`,
booleans and large identifiers keep their original representation. The original
CSV bytes also preserve column order and precision. Numeric SQL queries should
check missing/nonfinite values before casting; SQL casts alone can turn `nan`
into an apparent zero. Run JSON preserves uncertainty and unresolved statuses.

Binary FITS, PNG, PDF and NPZ products stay in the analysis directory; they are
not duplicated into SQLite. Keep the `results/runs/` tree alongside the database
to retain those files. No newly calibrated magnitudes or dates are inferred by
database storage. Planetary reassignment hypotheses remain separate candidate
evidence; the original stellar association is not silently rewritten.

The database never supplies inputs to a blind solve. Photometric magnitudes are
instrumental and camera/passband dependent; storing multiple cameras together
does not calibrate them. Image hashes support later duplicate checks but impose
no filtering now.

The lower-level `v11/analyse.sh` accepts `--database PATH` for explicit callers.
Keep the database outside the analysis directory so an output overwrite cannot
remove it. The ordinary demo remains a regression run without database writes.

No numerical solver changes or dependency additions accompany this feature.
Tests cover duplicate retention, partial failures, missing and unusable
photometry, native green channels, exact evidence preservation, concurrent
writers, transaction rollback, schema protection, and launcher routing.

## V11 lossless physical deduplication

New v11 databases store each exact JSON/CSV/TXT payload only once, indexed by
SHA-256. Every run/path still has its own product reference. Parsed CSV bodies
are stored once per content hash and row number; every logical measurement
retains its run, path, row, star ID and detection ID. Insignificant JSON spacing
is removed from parsed rows; strings, precision and original CSV bytes survive.
This does not combine observations or eliminate repeat measurements.

`products` and `measurements` are now compatibility views. Ordinary SQLite
queries, `json_extract`, existing plotting scripts and fixed-arity inserts from
preserved solvers continue to work without decompression extensions. `runs` and
`star_measurements` retain their public columns. Application ID and user version
remain unchanged; `storage_format` separately identifies the physical layout.
Public views support inserts, not edits/deletions: this remains an append-only
evidence store.

The first v11 append to a supported legacy database migrates it in the same
transaction. A failed append rolls back the migration too. Unknown layouts or
custom schema extensions are refused. Reclaimed pages can service later inserts;
to shrink an existing database file immediately, run from the repository root:

```sh
uv run --project v11 --frozen python v11/point_star_storage.py --database /full/path/to/stars.sqlite
```

This uses SQLite transactions and VACUUM, not replacement of a copied live
database. Other writers may wait for the lock; allow temporary free space for
SQLite's rewrite. It prints before/after byte counts. Frozen runtimes are not
modified; their future appends into a migrated database also share payloads.

## Intermediate snapshots

After a successful v11 analysis, database recording finishes first. For an
adopted joint solution, `joint_candidate_solution/` and `stellar_only_products/`
are losslessly compressed into `intermediate_products.zip`. Each member retains
its original relative path and exact bytes, including binary diagnostics.
Every member is verified before loose originals are removed. Final root JSON,
CSV, FITS, PNG and `report.pdf`, plus original observations, remain untouched and
directly accessible. Unadopted/failed staging stays loose for investigation.

The v11 recorder reads archived text products under their original paths, so
later imports retain the same logical database evidence. An interrupted cleanup
can resume if remaining loose bytes match the archive; conflicts are refused.
Storage cleanup failures warn without changing the scientific run's success.
Open the ZIP normally to inspect/extract earlier snapshots. Never overwrite an
authoritative final product with an intermediate snapshot.

For an existing completed adopted run:

```sh
uv run --project v11 --frozen python v11/point_star_storage.py --analysis /full/path/to/run/analysis
```

Use this only after the run has finished. The helper never selects or cleans a
whole results tree. This is lossless storage maintenance, not a new fit or a
change to the scientific result. Raw product bytes and queryable parsed CSVs
remain two representations by design; exact repeated copies of each are shared.
