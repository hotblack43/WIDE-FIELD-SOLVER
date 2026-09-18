# Raw All-Sky Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate a safe, cadence-first downloader that preserves and inspects small samples of publicly accessible high-dynamic-range colour all-sky observations.

**Architecture:** A thin top-level CLI delegates to independent source adapters through one normalized candidate model. Lightweight listings are converted to UTC candidates, deterministically cadence-selected, and capped before a shared HTTP layer can transfer any raw body; SQLite records checksums and inspection provenance. FITS, HDF5, and camera-RAW inspection is separate from transfer so originals remain unchanged and inaccessible sources can be reported honestly without fake adapters.

**Tech Stack:** Python 3.12, standard-library `argparse`/`urllib`/`sqlite3`/`fcntl`, NumPy 2.4.4, Astropy 7.2.0, h5py 3.16.0, rawpy 0.27.1, `unittest`, local HTTP test servers, `uv` lockfile.

**Spec:** `docs/superpowers/specs/2026-09-18-raw-allsky-acquisition-design.md`

## Global Constraints

- Do not modify `go.sh`, `go4.sh` through `go8.sh`, `go8a.sh`, `go_v0.*.sh`, or any file under the frozen `v4/` through `v8a/` packages.
- Do not overwrite or stage the user's existing changes in `goBIG`, `v9/SOURCE_MANIFEST.json`, `v9/docs/FEATURE_STATUS.md`, `v9/point_star_report.py`, `v9/test_point_star_report.py`, or `reports/planet_database_extract_20260918/`.
- Keep the existing `scripts/mmt_archive/` downloader unchanged.
- `--date` is one site-local civil day; `--start` is inclusive and `--end` is exclusive, with each camera's IANA timezone applied independently.
- Cadence defaults to `10m`; slot selection chooses the first observation in each half-open slot, breaks ties by normalized URL, and never borrows from a later slot.
- `--max-files` defaults to 20 and caps the whole invocation before any raw transfer.
- `--dry-run` may read listings and metadata but must not request a raw object's body.
- Originals are byte-preserved; derived previews never replace or share paths with originals.
- A source is `SUCCESS` only after an original file has been downloaded, decoded, numerically inspected, verified as colour/Bayer with genuine greater-than-8-bit information, and assessed for approximately point-like stars.
- Do not bypass authentication, guess private endpoints, or treat documentation and search snippets as downloaded-data evidence.
- Keep `uv.lock` committed and do not relax any existing regression threshold.
- Before every commit run `uv run --frozen python -m unittest discover -v` and `./demo.sh --output` with a new, nonexistent result directory.

---

### Task 1: Candidate model, local date ranges, and deterministic cadence

**Files:**
- Create: `allsky_download/__init__.py`
- Create: `allsky_download/model.py`
- Create: `allsky_download/cadence.py`
- Create: `tests/test_allsky_cadence.py`

**Interfaces:**
- Produces: `Site(source_id: str, camera_id: str, name: str, timezone: str, latitude_deg: float | None, longitude_deg: float | None, elevation_m: float | None)`.
- Produces: `Candidate(source_id: str, camera_id: str, observed_at: datetime, observed_raw: str, url: str, filename: str, size_bytes: int | None, metadata: Mapping[str, str])`.
- Produces: `DateRange(start_utc: datetime, end_utc: datetime)`.
- Produces: `Selection(candidates: tuple[Candidate, ...], eligible_count: int, truncated: bool, known_bytes: int, unknown_size_count: int)`.
- Produces: `parse_duration(text: str) -> timedelta`, `site_date_range(site: Site, *, date_value: date | None, start: date | None, end: date | None) -> DateRange`, and `select_candidates(candidates: Iterable[Candidate], ranges: Mapping[tuple[str, str], DateRange], cadence: timedelta, max_files: int) -> Selection`.

- [ ] **Step 1: Write failing duration, timezone, cadence, tie, and cap tests**

```python
# tests/test_allsky_cadence.py
from datetime import date, datetime, timedelta, timezone
import unittest

from allsky_download.cadence import parse_duration, select_candidates, site_date_range
from allsky_download.model import Candidate, DateRange, Site


UTC = timezone.utc


def candidate(camera, stamp, url):
    return Candidate("trex_rgb", camera, datetime.fromisoformat(stamp).replace(tzinfo=UTC),
                     stamp, url, url.rsplit("/", 1)[-1], None, {})


class CadenceTests(unittest.TestCase):
    def test_duration_units_and_invalid_values(self):
        self.assertEqual(parse_duration("30s"), timedelta(seconds=30))
        self.assertEqual(parse_duration("2.5m"), timedelta(seconds=150))
        self.assertEqual(parse_duration("1h"), timedelta(hours=1))
        for value in ("", "0m", "-1m", "nanm", "10", "1d"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_site_local_date_range_honours_dst(self):
        site = Site("trex", "gill_rgb-04", "Gillam", "America/Winnipeg", None, None, None)
        result = site_date_range(site, date_value=date(2026, 3, 8), start=None, end=None)
        self.assertEqual(result.start_utc.isoformat(), "2026-03-08T06:00:00+00:00")
        self.assertEqual(result.end_utc.isoformat(), "2026-03-09T05:00:00+00:00")

    def test_first_candidate_per_slot_tie_order_and_absolute_cap(self):
        items = [
            candidate("a", "2026-01-01T00:10:02", "https://x/z.h5"),
            candidate("a", "2026-01-01T00:00:03", "https://x/b.h5"),
            candidate("a", "2026-01-01T00:00:03", "https://x/a.h5"),
            candidate("b", "2026-01-01T00:00:01", "https://x/c.h5"),
        ]
        window = DateRange(datetime(2026, 1, 1, tzinfo=UTC),
                           datetime(2026, 1, 1, 0, 30, tzinfo=UTC))
        result = select_candidates(items, {("trex_rgb", "a"): window,
                                           ("trex_rgb", "b"): window},
                                   timedelta(minutes=10), max_files=2)
        self.assertEqual([c.url for c in result.candidates], ["https://x/c.h5", "https://x/a.h5"])
        self.assertEqual(result.eligible_count, 3)
        self.assertTrue(result.truncated)
```

- [ ] **Step 2: Run the tests and confirm the missing package is the failure**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_cadence`

Expected: `ModuleNotFoundError: No module named 'allsky_download'`.

- [ ] **Step 3: Implement immutable records and cadence selection**

```python
# allsky_download/model.py
@dataclass(frozen=True, slots=True)
class Candidate:
    source_id: str
    camera_id: str
    observed_at: datetime
    observed_raw: str
    url: str
    filename: str
    size_bytes: int | None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must be nonnegative")
```

Implement the other records with the exact signatures above. In
`select_candidates`, group by `(source_id, camera_id)`, reject candidates outside
that camera's range, compute `slot = floor((observed_at - start) / cadence)`, and
keep the minimum `(observed_at, url)` for each `(source, camera, slot)`. Sort the
winners by `(observed_at, source_id, camera_id, url)`, record their pre-cap count,
then slice to `max_files`.

- [ ] **Step 4: Run focused tests and the whole suite**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_cadence`

Expected: all cadence tests pass.

Run: `uv run --frozen python -m unittest discover -v`

Expected: all existing and new tests pass.

- [ ] **Step 5: Run the preserved demo and commit**

Run: `test ! -e results/check-raw-allsky-task-01-20260918 && ./demo.sh --output results/check-raw-allsky-task-01-20260918`

Expected: baseline PASS with 3,653 associations and RMS at or below the preserved threshold.

```bash
git add allsky_download/__init__.py allsky_download/model.py allsky_download/cadence.py tests/test_allsky_cadence.py
git commit -m "feat: add deterministic all-sky cadence selection"
```

### Task 2: Bounded HTTP transfers and transactional duplicate ledger

**Files:**
- Create: `allsky_download/http.py`
- Create: `allsky_download/manifest.py`
- Create: `tests/test_allsky_http.py`
- Create: `tests/test_allsky_manifest.py`

**Interfaces:**
- Consumes: `Candidate` from Task 1.
- Produces: `HttpClient(timeout: float = 45, retries: int = 3, delay: float = 0.5, user_agent: str = "WIDE-FIELD-SOLVER-raw-allsky/0.1")` with `get_text(url: str) -> str` and `download_atomic(candidate: Candidate, destination: Path) -> DownloadedFile`.
- Produces: `DownloadedFile(path: Path, size_bytes: int, sha256: str)`.
- Produces: `Manifest(path: Path)` context manager with `record_attempt`, `record_success`, `record_failure`, `verified_download`, and `set_inspection_id` methods.
- Produces: `output_lock(output_root: Path)` context manager using `fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)`.

- [ ] **Step 1: Write a failing real-HTTP integration test**

Use `ThreadingHTTPServer` with `/listing` returning text, `/raw.fit` returning 503
once and then fixed bytes, and counters for each route. Assert that `get_text`
returns the listing, `download_atomic` retries once, the final bytes and SHA-256
match literals, and no `.part-*` file remains. Add a second test where a 404 is
attempted exactly once and raises `PermanentHttpError`.

- [ ] **Step 2: Run the HTTP tests and confirm imports fail**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_http`

Expected: import failure for `allsky_download.http`.

- [ ] **Step 3: Implement the HTTP client with standard-library urllib**

Retry only timeouts, `URLError`, and HTTP 408/425/429/500/502/503/504. Use delays
`delay * 2**attempt`, capped at 16 seconds. Stream in 1 MiB chunks to a
`tempfile.NamedTemporaryFile(delete=False, dir=destination.parent,
prefix=destination.name + ".part-")`, update SHA-256 while writing, validate
`Candidate.size_bytes` when present, flush and `os.fsync`, then `os.replace`.
Remove the temporary path on every exception.

- [ ] **Step 4: Run the HTTP tests and confirm they pass**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_http`

Expected: retry, permanent-error, atomicity, checksum, and cleanup tests pass.

- [ ] **Step 5: Write failing manifest reuse and lock tests**

Create a temporary SQLite manifest, record a successful fixed file, and assert
`verified_download(candidate, root)` returns its `DownloadedFile`. Corrupt one
byte without changing the length and assert verification returns `None` and the
row changes to `corrupt_local`. Open `output_lock` twice in the same process and
assert the second attempt raises `OutputLockedError`.

- [ ] **Step 6: Run the manifest tests and confirm the missing implementation fails**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_manifest`

Expected: import or attribute failure for the manifest interfaces.

- [ ] **Step 7: Implement the SQLite schema, checksum reuse, and process lock**

Create one `downloads` table with these columns and constraints:

```sql
CREATE TABLE downloads (
  remote_url TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  observed_utc TEXT NOT NULL,
  observed_raw TEXT NOT NULL,
  remote_filename TEXT NOT NULL,
  local_path TEXT,
  advertised_bytes INTEGER,
  observed_bytes INTEGER,
  sha256 TEXT,
  download_status TEXT NOT NULL,
  validation_status TEXT NOT NULL,
  attempted_utc TEXT NOT NULL,
  error TEXT,
  inspector_kind TEXT,
  inspection_id TEXT
);
```

Use explicit transactions and store local paths relative to the output root.
`verified_download` must recalculate SHA-256, not trust size alone. The lock file
is `<output_root>/.download.lock` and contains PID plus acquisition UTC for
diagnostics.

- [ ] **Step 8: Run focused and full verification, then commit**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_http tests.test_allsky_manifest`

Run: `uv run --frozen python -m unittest discover -v`

Run: `test ! -e results/check-raw-allsky-task-02-20260918 && ./demo.sh --output results/check-raw-allsky-task-02-20260918`

Expected: all tests pass and the preserved demo passes.

```bash
git add allsky_download/http.py allsky_download/manifest.py tests/test_allsky_http.py tests/test_allsky_manifest.py
git commit -m "feat: add verified all-sky transfers and manifest"
```

### Task 3: Source registry plus MMTO and TREx listing adapters

**Files:**
- Create: `allsky_download/registry.py`
- Create: `allsky_download/sources/__init__.py`
- Create: `allsky_download/sources/common.py`
- Create: `allsky_download/sources/mmto.py`
- Create: `allsky_download/sources/trex_rgb.py`
- Create: `sources.json`
- Create: `tests/fixtures/mmto_listing.html`
- Create: `tests/fixtures/trex_day_listing.html`
- Create: `tests/fixtures/trex_hour_listing.html`
- Create: `tests/test_allsky_sources.py`

**Interfaces:**
- Consumes: `Site`, `Candidate`, `DateRange`, and `HttpClient.get_text`.
- Produces: `SourceAdapter` protocol with `sites(camera_id: str | None) -> tuple[Site, ...]` and `list_candidates(client: HttpClient, site: Site, date_range: DateRange) -> tuple[Candidate, ...]`.
- Produces: `SourceRegistry.from_json(path: Path)`, `resolve_source_id(name_or_alias: str)`, `get_adapter(source_id: str)`, and `listed_sources()`.
- Produces: `MmtoAdapter` and `TrexRgbAdapter`.

- [ ] **Step 1: Save narrow, factual listing fixtures**

Use the public MMTO archive HTML for one dated directory and the Calgary pages
for `stream0/2026/01/15/` and
`stream0/2026/01/15/gill_rgb-04/ut06/`. Retain only the listing header and enough
unaltered rows to cover trailing-slash MMTO links, advertised sizes, two cameras,
two hours, and several minute HDF5 files. Add a source URL comment above each
fixture; do not store cookies or response headers containing identifiers.

- [ ] **Step 2: Write failing parser and adapter tests**

```python
class SourceAdapterTests(unittest.TestCase):
    def test_mmto_uses_verified_local_clock_and_noon_bucket(self):
        items = MmtoAdapter("https://skycam.mmto.arizona.edu/skycam/archive/").parse_listing(
            MMTO_HTML, archive_date=date(2026, 3, 15))
        self.assertEqual(items[0].filename, "2026_03_15__12_00_16.fits.bz2")
        self.assertEqual(items[0].observed_at.isoformat(), "2026-03-15T19:00:16+00:00")

    def test_trex_minute_bundle_names_are_utc_candidates_with_sizes(self):
        items = TrexRgbAdapter(
            "https://data.phys.ucalgary.ca/sort_by_project/TREx/RGB/stream0/"
        ).parse_hour_listing(TREX_HOUR_HTML, "gill_rgb-04")
        self.assertEqual(items[0].observed_at.isoformat(), "2026-01-15T06:00:00+00:00")
        self.assertEqual(items[0].size_bytes, 7891561)
        self.assertTrue(items[0].url.endswith("20260115_0600_gill_rgb-04_full.h5"))
```

Also test that links escaping the current directory, queries, wrong extensions,
and mismatched site IDs are ignored. Test that the registry refuses a camera not
listed for its source and refuses downloads for a source whose `adapter` is
`null`.

- [ ] **Step 3: Run the source tests and confirm missing adapters fail**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_sources`

Expected: import failure for `allsky_download.registry` or source modules.

- [ ] **Step 4: Implement a strict same-directory index parser**

`common.py` subclasses `HTMLParser`, resolves relative links with `urljoin`, and
accepts only a direct child whose normalized parent equals the listing URL. It
parses Apache/lighttpd byte counts as exact integers when present and never
follows `../`, query, fragment, or cross-origin links.

- [ ] **Step 5: Implement the MMTO adapter**

Register camera `mmto-skycam` with `America/Phoenix`, latitude
31.6866666667, longitude -110.8841666667, elevation 2616 m. Map requested UTC
ranges to every intersecting local noon-to-noon archive bucket. Accept only
`.fits.bz2`, `.fit.bz2`, and `.fts.bz2`. Parse the verified filename clock as
local Arizona time and retain `timestamp_convention=filename local
America/Phoenix; FITS DATE-OBS verified separately` in candidate metadata.

- [ ] **Step 6: Implement the TREx-RGB adapter**

Use public root
`https://data.phys.ucalgary.ca/sort_by_project/TREx/RGB/stream0/`. Traverse only
the necessary UTC `YYYY/MM/DD/<camera>/utHH/` pages intersecting the requested
range. Accept `YYYYMMDD_HHMM_<camera>_full.h5` exactly; parse `YYYYMMDD_HHMM` as
UTC; use the listing's exact byte count. Discover camera IDs only from the
selected day page and intersect them with configured `sources.json` cameras.

- [ ] **Step 7: Add the six source families to `sources.json`**

Use schema version 1 and fields `id`, `aliases`, `name`, `status`, `adapter`,
`archive_roots`, `documentation`, `licensing`, and `cameras`. The canonical IDs
match the required output directories: `mmto`, `trex_rgb`, `presente`, `rubin`,
`oasi`, and `indi_allsky`; configure `trex` as an alias for `trex_rgb` and
`indi` as an alias for `indi_allsky`. Configure the verified MMTO camera
and the official TREx site IDs/coordinates/timezones obtained from the Calgary
observatory API. Set research-pending families to `UNKNOWN` with `adapter: null`;
this is an explicit intermediate state to be replaced in Task 6, not a success
claim.

- [ ] **Step 8: Run focused and full verification, then commit**

Run: `python -m json.tool sources.json >/dev/null`

Run: `uv run --frozen python -m unittest -v tests.test_allsky_sources`

Run: `uv run --frozen python -m unittest discover -v`

Run: `test ! -e results/check-raw-allsky-task-03-20260918 && ./demo.sh --output results/check-raw-allsky-task-03-20260918`

Expected: JSON parses, tests pass, and the preserved demo passes.

```bash
git add allsky_download/registry.py allsky_download/sources sources.json tests/fixtures tests/test_allsky_sources.py
git commit -m "feat: list MMTO and TREx raw observations"
```

### Task 4: Safe end-to-end downloader CLI

**Files:**
- Create: `allsky_download/cli.py`
- Create: `download_samples.py`
- Create: `tests/test_allsky_cli.py`
- Create: `raw_allsky_samples/mmto/.gitkeep`
- Create: `raw_allsky_samples/trex_rgb/.gitkeep`
- Create: `raw_allsky_samples/presente/.gitkeep`
- Create: `raw_allsky_samples/rubin/.gitkeep`
- Create: `raw_allsky_samples/oasi/.gitkeep`
- Create: `raw_allsky_samples/indi_allsky/.gitkeep`

**Interfaces:**
- Consumes: Tasks 1 through 3.
- Produces: `build_parser() -> argparse.ArgumentParser`, `run(args: Namespace, *, registry: SourceRegistry | None = None, client: HttpClient | None = None) -> int`, and `main(argv: Sequence[str] | None = None) -> int`.
- Produces: top-level `download_samples.py` calling `raise SystemExit(main())`.

- [ ] **Step 1: Write failing parser and dry-run tests**

Test the public CLI rather than implementation text:

```python
def test_defaults_are_safe(self):
    args = build_parser().parse_args(["--site", "mmto", "--date", "2026-03-15", "--dry-run"])
    self.assertEqual(args.cadence, "10m")
    self.assertEqual(args.max_files, 20)

def test_date_and_range_are_mutually_exclusive(self):
    with self.assertRaises(SystemExit):
        build_parser().parse_args(["--site", "mmto", "--date", "2026-03-15",
                                   "--start", "2026-03-01", "--end", "2026-04-01"])
```

For behavior, serve one listing and two raw routes from a local HTTP server.
Inject a fixture adapter pointed at it. Run `--dry-run`; assert the printed UTC,
URL, count, known bytes, and unknown-size warning, and assert both raw route
counters remain zero. Run without `--dry-run --max-files 1`; assert exactly one
raw route is requested and the other remains zero.

- [ ] **Step 2: Run CLI tests and confirm missing CLI failure**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_cli`

Expected: import failure for `allsky_download.cli`.

- [ ] **Step 3: Implement argument validation and selection reporting**

Support exactly:

```text
--site SOURCE                  required
--camera CAMERA               repeatable; all configured cameras when omitted
--date YYYY-MM-DD             mutually exclusive with --start/--end
--start YYYY-MM-DD            requires --end
--end YYYY-MM-DD              exclusive; requires --start
--cadence DURATION            default 10m
--max-files N                 default 20, positive
--output PATH                 default raw_allsky_samples
--dry-run
--timeout SECONDS             default 45, positive
--retries N                   default 3, nonnegative
--log-level LEVEL             DEBUG/INFO/WARNING/ERROR, default INFO
```

Resolve all candidate lists before calling `select_candidates`. Print one
machine-stable tab-separated `SELECT` line per result and a final `SUMMARY`
line. Dry run returns 0 after this report without creating the manifest or lock.

- [ ] **Step 4: Implement verified download orchestration**

Within `output_lock`, open the manifest, reuse only checksum-verified rows, and
download remaining candidates to
`<output>/<source_id>/<camera_id>/<remote_filename>`. Reject basenames that are
empty, dot paths, absolute, or contain `/` or `\\`. Record each attempt and keep
independent downloads going after one operational failure. Return 0 only if all
selected candidates verify; return 2 when listing, transfer, or validation is
incomplete; convert `KeyboardInterrupt` to 130.

- [ ] **Step 5: Run CLI tests, help, and whole suite**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_cli`

Run: `uv run --frozen python download_samples.py --help`

Run: `uv run --frozen python -m unittest discover -v`

Expected: tests pass; help lists every implemented option; no network is needed.

- [ ] **Step 6: Run the preserved demo and commit**

Run: `test ! -e results/check-raw-allsky-task-04-20260918 && ./demo.sh --output results/check-raw-allsky-task-04-20260918`

```bash
git add allsky_download/cli.py download_samples.py tests/test_allsky_cli.py raw_allsky_samples
git commit -m "feat: add safe all-sky sample downloader CLI"
```

### Task 5: Reproducible FITS, HDF5, and camera-RAW inspection

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `allsky_download/inspect.py`
- Create: `allsky_download/inspect_cli.py`
- Create: `inspect_allsky_samples.py`
- Create: `tests/test_allsky_inspect.py`

**Interfaces:**
- Consumes: downloaded originals and `Manifest.set_inspection_id`.
- Produces: `array_statistics(array: np.ndarray, saturation_level: int | float | None) -> dict[str, object]`.
- Produces: `inspect_fits(path: Path)`, `inspect_hdf5(path: Path)`, and `inspect_camera_raw(path: Path, decoder_factory=rawpy.imread)` returning JSON-serializable dictionaries.
- Produces: `inspect_path(path: Path)` format dispatch, `write_preview(record, preview_path: Path) -> Path`, and `write_inspection(paths, output_path, manifest_path, preview_dir: Path | None = None) -> int`.

- [ ] **Step 1: Add pinned decoder dependencies and refresh the lock**

Add `h5py==3.16.0` and `rawpy==0.27.1` to the root dependencies, then run:

`uv lock && uv sync --frozen`

Expected: only `pyproject.toml`, `uv.lock`, and environment state change; all
preserved subproject lockfiles remain untouched.

- [ ] **Step 2: Write failing array, all-HDU FITS, recursive HDF5, and RAW-interface tests**

Build a FITS fixture with a primary `uint16` image and an image extension, and
an HDF5 fixture containing `/images/raw` plus nested scalar metadata attributes.
Use literal arrays whose hand-computed minimum, maximum, median, p99, occupied
bits, and saturation fractions are known. Assert every FITS HDU and HDF5 dataset
appears.

For camera RAW, inject a decoder context manager exposing:

```python
from types import SimpleNamespace

raw_image_visible = np.array([[64, 1000], [2048, 4095]], dtype=np.uint16)
raw_pattern = np.array([[0, 1], [1, 2]], dtype=np.uint8)
color_desc = b"RGBG"
black_level_per_channel = [64, 64, 64, 64]
white_level = 4095
other = SimpleNamespace(iso_speed=800, shutter_speed=30.0, aperture=2.8,
                        focal_length=8.0, timestamp=1768431600, shot_order=0,
                        artist=None)
sizes.raw_width = 2
sizes.raw_height = 2
sizes.width = 2
sizes.height = 2
```

Assert the inspector reports the sensor array, `RGGB`, width/height, range, black
levels, and white level without calling `postprocess`.

Add one preview test using a 4x4 RGGB array: assert the generated PNG is 2x2 RGB,
the source array is unchanged, and repeated generation yields identical bytes.

- [ ] **Step 3: Run inspection tests and confirm missing code fails**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_inspect`

Expected: import failure for `allsky_download.inspect`.

- [ ] **Step 4: Implement deterministic numerical statistics**

Report dtype, shape, finite count, min, max, median, p1/p5/p95/p99/p99.9,
`occupied_bits = ceil(log2(max-min+1))`, and saturation fraction. For integer
spans at most 1,000,000 use `np.unique` on the full finite array. Otherwise take
indices `np.linspace(0, size - 1, min(size, 1_000_000), dtype=np.int64)`, count
sample distinct values, and label `distinct_values_exact: false`.

- [ ] **Step 5: Implement format inspectors and atomic JSON output**

FITS uses `fits.open(path, do_not_scale_image_data=True, memmap=True)` for stored
dtype/BITPIX plus a second scaled read only when BSCALE/BZERO require it. HDF5
uses `visititems` and serializes group/dataset attributes without dropping byte
values. Camera RAW reads only `raw_image_visible`, `raw_pattern`, levels,
`sizes`, and the `other` metadata tuple; it never calls `extract_thumb` or
`postprocess`. Extract exposure,
timestamp, Bayer, camera, site, gain, black, white, and saturation keywords or
attributes into separate `metadata` fields while retaining all relevant raw
header/attribute values.

Write sorted, indented JSON to a sibling temporary file, `fsync`, and replace
`raw_allsky_samples/inspection.json`. The inspection ID is SHA-256 of the
canonical JSON record for that original.

When `preview_dir` is supplied, generate a display-only PNG beside no original.
For planar/interleaved RGB, map the verified channel axis directly. For Bayer,
reduce each complete 2x2 cell to one RGB pixel using the declared pattern (the
two green samples are averaged), subtract documented black levels, scale each
channel from its p1 to p99.9, clip, apply display gamma 0.45, and encode 8-bit
PNG with fixed Pillow options. For multi-frame files use the first frame and
record its index. If layout or Bayer order is unresolved, create a monochrome
preview and label the preview record `colour_mapping: unresolved`; never guess.

- [ ] **Step 6: Run focused/full verification and commit**

Run: `uv run --frozen python -m unittest -v tests.test_allsky_inspect`

Run: `uv run --frozen python -m unittest discover -v`

Run: `test ! -e results/check-raw-allsky-task-05-20260918 && ./demo.sh --output results/check-raw-allsky-task-05-20260918`

```bash
git add pyproject.toml uv.lock allsky_download/inspect.py allsky_download/inspect_cli.py inspect_allsky_samples.py tests/test_allsky_inspect.py
git commit -m "feat: inspect scientific all-sky originals"
```

### Task 6: Complete the six-source public-access audit

**Files:**
- Modify: `sources.json`
- Create: `SOURCES.md`
- Create: `allsky_download/sources/presente.py` only if a public HDF5 listing is verified
- Create: `allsky_download/sources/rubin.py` only if an unauthenticated public CR2 listing is verified
- Create: `allsky_download/sources/oasi.py` only if a public original-FITS listing is verified
- Create: `allsky_download/sources/indi_allsky.py` only for verified public raw exports
- Modify: `tests/test_allsky_sources.py` for every newly operational adapter
- Add: narrow listing fixtures under `tests/fixtures/` for every newly operational adapter

**Interfaces:**
- Consumes: source schema and adapter contract from Task 3.
- Produces: final evidence-backed `status` for all six requested families, direct documentation/archive/contact links, checked-at date, archive coverage, licensing statement, and operational adapter registration only where public raw listings are verified.

- [ ] **Step 1: Audit MMTO continuation and format changes**

Inspect the archive root, the most recent visible date, adjacent movie dates, and
several dated raw listings. Record the latest raw directory actually observed,
gaps separately from cessation, and whether suffixes/layout changed. Do not infer
raw continuation solely from the movie archive.

- [ ] **Step 2: Audit and decode the official TREx route at metadata depth**

Confirm `TREX_RGB_RAW_NOMINAL`, `stream0`, camera IDs, UTC filename convention,
minute-file sizes, official PyAuroraX decoding guidance, DOI/citation, and site
coordinates from University of Calgary pages/APIs. Record that each HDF5 minute
file may contain multiple nominal-cadence frames; cadence selection remains at
file observation timestamp and does not download minute files merely to select
inside them. Record a 60-second remote-object granularity for this layout: a
requested cadence below one minute cannot select individual 3-second frames
without retrieving their containing minute file, and the downloader never
selects the same HDF5 object twice.

- [ ] **Step 3: Audit PRESENTE / GOA-SCAN**

Use the University of Valladolid/GOA-SCAN publications, project pages,
repositories, DOI/data supplements, and institutional repository. Distinguish
documented 14-bit Bayer-in-16-bit HDF5 acquisition from public HDF5 access. If
access is request-only, record the named data contact and institutional address;
do not create an operational adapter.

- [ ] **Step 4: Audit Rubin public CR2 access**

Start from SMTN-005 and its GitHub analysis repository, then check public Rubin
data portals, public object stores, Cerro Pachón weather/all-sky pages, engineering
archives, and historical public directories. Treat
`s3dflogin-mfa.slac.stanford.edu:/sdf/group/rubin/datasets/all-sky` as restricted,
not public. Only an unauthenticated CR2 URL can enable `RubinAdapter`.

- [ ] **Step 5: Audit OASI originals**

Trace OASI's all-sky page, its linked current/archive pages, newsletters, public
server directories, and linked source repositories. Record ASI178MC/INDI FITS
documentation separately from surviving public originals. JPEG galleries and
Wayback-rendered pages do not establish raw availability.

- [ ] **Step 6: Audit public INDI-AllSky installations**

Use the official GitHub code/configuration to document optional
`IMAGE_SAVE_FITS`, raw/FITS export folder templates, SyncAPI media types, and
retention defaults. Search public indexed installations and their legitimate
viewer/download links. For each candidate, verify direct unauthenticated `.fit`,
`.fits`, compressed FITS, DNG, or other original access before configuring it.
Do not derive or probe administration routes. Aim for three independent cameras,
but report `RAW NOT FOUND` or `UNKNOWN` when public pages expose only rendered
images or evidence is insufficient.

- [ ] **Step 7: Test and implement every newly verified adapter**

For each source that yields a legitimate public listing, first save a narrow
listing fixture and write a failing test asserting exact timestamp, camera ID,
raw extension, size, and rejection of unsafe links. Run the single test to verify
RED, implement the minimal adapter through `common.py`, then run it GREEN. Do not
add a module for a restricted or raw-not-found source.

- [ ] **Step 8: Write the factual pre-download results report**

Create `SOURCES.md` with the requested table and a section per source. Before a
sample is inspected, even an operational source remains `UNKNOWN (download
verification pending)` rather than `SUCCESS`. Cite direct official pages and
state access dates. In `sources.json`, replace every intermediate research status
with its evidence-backed status; successful candidates awaiting Task 7 use
`UNKNOWN` plus `download_verification_pending: true`.

- [ ] **Step 9: Validate structured data, tests, preserved demo, and commit**

Run: `python -m json.tool sources.json >/dev/null`

Run: `uv run --frozen python -m unittest -v tests.test_allsky_sources`

Run: `uv run --frozen python -m unittest discover -v`

Run: `test ! -e results/check-raw-allsky-task-06-20260918 && ./demo.sh --output results/check-raw-allsky-task-06-20260918`

```bash
git add sources.json SOURCES.md allsky_download/sources tests/fixtures tests/test_allsky_sources.py
git commit -m "docs: audit public raw all-sky archives"
```

### Task 7: Controlled live downloads and numerical verification

**Files:**
- Add: original files beneath `raw_allsky_samples/<source>/<camera>/`
- Create or modify: `raw_allsky_samples/manifest.sqlite`
- Create: `raw_allsky_samples/inspection.json`
- Create: derived previews beneath `raw_allsky_samples/derived/`
- Modify: `sources.json`
- Modify: `SOURCES.md`

**Interfaces:**
- Consumes: downloader CLI, manifest, adapters, and inspectors.
- Produces: unchanged originals with checksums plus one canonical inspection record per original.

- [ ] **Step 1: Dry-run MMTO before transfer**

Run:

```bash
uv run --frozen python download_samples.py \
  --site mmto --camera mmto-skycam --date 2026-03-15 \
  --cadence 1h --max-files 2 --dry-run
```

Confirm the output lists no more than two `.fits.bz2` originals, prints UTC and
known/unknown volume, and creates no manifest or sample file.

- [ ] **Step 2: Download the exact inspected MMTO selection and prove reuse**

Repeat the command without `--dry-run`, inspect the manifest rows and SHA-256,
then repeat it once more with HTTP debug logging. Confirm the second run performs
no raw-body transfer and recalculates local checksums.

- [ ] **Step 3: Dry-run and download two TREx-RGB cameras independently**

Use the two cameras `gill_rgb-04` and `luck_rgb-03`, both present on
2026-01-15. For each, run `--site trex --camera CAMERA --date 2026-01-15
--cadence 1h --max-files 1 --dry-run`, inspect the URL/size, then remove only
`--dry-run`. This yields at most two minute HDF5 originals, not every 3-second
exposure or every minute file.

- [ ] **Step 4: Download one sample per additional verified public camera**

For every operational adapter established in Task 6, choose a documented dark
night/date, run a one-file dry run, inspect the result, and only then repeat
without `--dry-run`. Preserve CR2/DNG/FITS/HDF5 originals without conversion.

- [ ] **Step 5: Generate numerical inspection records**

Run:

```bash
uv run --frozen python inspect_allsky_samples.py \
  --root raw_allsky_samples \
  --manifest raw_allsky_samples/manifest.sqlite \
  --output raw_allsky_samples/inspection.json \
  --preview-dir raw_allsky_samples/derived
```

Inspect every FITS HDU, HDF5 group/dataset, and genuine camera-RAW sensor array.
Compare observation timestamps in file metadata with selected timestamps and
record discrepancies rather than rewriting either value.

- [ ] **Step 6: Assess point-star usability from labelled derived previews**

Open each derived preview, confirm whether ordinary stars are present and
approximately point-like, and record `yes`, `no`, or `uncertain` with a concise
reason in `SOURCES.md` and `sources.json`. A preview is a deterministic display
stretch only and is never cited as high-dynamic-range evidence.

- [ ] **Step 7: Apply final status classifications**

Promote only sources satisfying every success predicate. For each successful
sample record exact URL, local relative path, size, SHA-256, format, dimensions,
stored dtype/BITPIX, channel/Bayer layout, documented ADC depth, empirical range,
exposure, timestamp, saturation fraction, and star assessment. Leave restricted,
processed-only, unsuitable, and unresolved sources under their exact status.

- [ ] **Step 8: Verify originals against the manifest and commit evidence**

Run the same download commands again and confirm `already verified` for every
original. Regenerate `inspection.json` and compare it byte-for-byte with the
previous generated version.

Run: `uv run --frozen python -m unittest discover -v`

Run: `test ! -e results/check-raw-allsky-task-07-20260918 && ./demo.sh --output results/check-raw-allsky-task-07-20260918`

```bash
git add raw_allsky_samples sources.json SOURCES.md
git commit -m "data: add verified raw all-sky samples"
```

### Task 8: User documentation, cron guidance, and final audit

**Files:**
- Modify: `README.md`
- Modify: `SOURCES.md`
- Modify: `sources.json`
- Modify: any downloader test or implementation file only to fix a newly reproduced defect through a RED/GREEN cycle

**Interfaces:**
- Produces: documented CLI usage and final evidence table matching executable behavior.

- [ ] **Step 1: Add concise README usage examples**

Document setup with `uv sync --frozen`; source/camera discovery through
`sources.json`; a MMTO dry run;
the matching real run; TREx camera selection; one local date; a half-open date
range; `30s`, `5m`, `30m`, and `1h` cadence examples; `--max-files`; output and
manifest layout; exit codes 0/2/130; log redirection suitable for cron; and the
fact that no cron entry is installed.

State explicitly that `--moon-down` and `--sun-below` are reserved future work
and are not silently applied. Explain the first-after-boundary slot rule and the
default 10-minute/20-file safety behavior.

- [ ] **Step 2: Cross-check documentation against executable help and evidence**

Run `uv run --frozen python download_samples.py --help` and execute every README
dry-run example with `--max-files 1`. Check every `SUCCESS` table row against
`inspection.json`, `manifest.sqlite`, and the on-disk SHA-256. Downgrade any row
whose evidence is incomplete.

- [ ] **Step 3: Run formatting and structured-data checks**

Run:

```bash
python -m json.tool sources.json >/dev/null
python -m json.tool raw_allsky_samples/inspection.json >/dev/null
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Run focused and complete verification**

Run:

```bash
uv run --frozen python -m unittest -v \
  tests.test_allsky_cadence tests.test_allsky_http tests.test_allsky_manifest \
  tests.test_allsky_sources tests.test_allsky_cli tests.test_allsky_inspect
uv run --frozen python -m unittest discover -v
test ! -e results/check-raw-allsky-final-20260918 && \
  ./demo.sh --output results/check-raw-allsky-final-20260918
```

Expected: all focused and repository tests pass; demo reports 3,653 associations
and a passing preserved RMS.

- [ ] **Step 5: Audit scope and commit the documentation**

Run `git status --short` and `git diff --stat HEAD`; confirm frozen versions and
the user's pre-existing modified/untracked paths are absent from this task's
diff. Confirm every source has one final status and every success has a local
checksum-backed original plus numerical inspection.

```bash
git add README.md SOURCES.md sources.json
git commit -m "docs: document raw all-sky acquisition"
```

- [ ] **Step 6: Request code review before integration**

Invoke `superpowers:requesting-code-review` over the complete commit range. Fix
each verified issue with a failing regression test first, rerun the focused and
full verification above, and report remaining evidence limitations without
weakening classifications.
