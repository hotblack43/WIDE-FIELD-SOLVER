# v6 Planetary Search Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent v0.6.0 runtime whose exact blind planetary search is at least twice as fast as warm-cache v5 while preserving v5 and its scientific outcomes.

**Architecture:** Copy the latest frozen v5 package into v6, ship its validated daily ephemeris as v6 data, and route planet calculations through a provider that distinguishes cubic proposal interpolation from exact Astropy evaluation. Refine independent per-planet visit groups with deterministic process workers and batched exact bounded minimization, then retain the existing exact joint assignment, evidence and reporting logic. Record timing/call telemetry without allowing it to influence scientific results.

**Tech Stack:** Python 3.12, NumPy 2.4.4, SciPy 1.17.1, Astropy 7.2.0/PyERFA 2.0.1.5, `concurrent.futures`, Bash launchers, `unittest`, uv.

**Spec:** `docs/superpowers/specs/2026-09-16-v6-planet-search-performance.md`

## Global Constraints

- Base v6 on commit `1e22756`; do not edit any file under `v5/`, `go5.sh`, or `go_v0.5.0.sh`.
- Keep the daily 1850--2036 TDB interval, causal present-time ceiling, blind metadata boundary, image-derived horizon and all alternative dates.
- Exact Astropy builtin directions decide every saved position, altitude, gate, residual and epoch; interpolation proposes work only.
- Keep all measured detections eligible under the existing catalogue-competition, visibility and saturation rules.
- Keep actual measured and predicted plotting positions faithful; performance work must not alter the fitted camera or astrometric exports.
- Do not weaken existing regressions or historical demo thresholds.
- Default to at most four deterministic process workers; `WFS_PLANET_WORKERS=1` is the serial reference path.
- Require at least a twofold median warm-cache planetary-stage speedup over v5 on the same machine and Espenak input before release.

---

### Task 1: Freeze v5 and scaffold the independent v6 package

**Files:**
- Create: `docs/v5-runtime.json`
- Create: `v6/**` as a mechanical copy of tracked `v5/**`
- Create: `go6.sh`
- Create: `go_v0.6.0.sh`
- Create: `test_v6_launchers.py`
- Modify: `test_preserved_versions.py`
- Modify: `v6/pyproject.toml`
- Modify: `v6/uv.lock`
- Modify: `v6/point_star_barghini.py`
- Modify: `v6/run.sh`
- Modify: `v6/README.md`

**Interfaces:**
- Produces: `go6.sh IMAGE` and `go_v0.6.0.sh IMAGE`, both dispatching only to `v6/run.sh` version `0.6.0`.
- Produces: `docs/v5-runtime.json` with `preserved_commit`, `version`, and SHA-256 entries for `v5/SOURCE_MANIFEST.json`, every path covered by that manifest, `go5.sh`, and `go_v0.5.0.sh`.
- Preserves: byte-for-byte v5 runtime and launcher content verified by the root test suite.

- [ ] **Step 1: Write failing launcher and preservation tests**

Create `test_v6_launchers.py` by adapting the v5 launcher fixture to these constants and assertions:

```python
ROOT = Path(__file__).resolve().parent
LAUNCHERS = ('go6.sh', 'go_v0.6.0.sh')
PACKAGE = 'v6'
VERSION = '0.6.0'

def test_v5_launchers_are_unchanged(self):
    record = json.loads((ROOT/'docs/v5-runtime.json').read_text())
    for name, expected in record['sha256'].items():
        self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected)
```

Extend `test_preserved_versions.py` with a v5 boundary check and a v6 inventory check that requires every top-level v6 `.py`/`.sh` runtime file to appear in `v6/SOURCE_MANIFEST.json`.

- [ ] **Step 2: Run the new tests and verify the expected failure**

Run:

```bash
uv run --frozen python -m unittest -v test_v6_launchers test_preserved_versions
```

Expected: FAIL because `go6.sh`, `v6/`, and `docs/v5-runtime.json` do not exist.

- [ ] **Step 3: Generate the frozen v5 record and copy tracked v5 content**

Generate hashes from `v5/SOURCE_MANIFEST.json` plus the v5 launchers, then write `docs/v5-runtime.json` with sorted keys. Copy only tracked v5 content—never `.venv`, generated results, or ignored caches—using the Git index as the source inventory. Change these copied version values to `0.6.0`:

```python
# v6/point_star_barghini.py
SOLVER_VERSION = '0.6.0'
```

```toml
# v6/pyproject.toml
[project]
name = "wide-field-solver"
version = "0.6.0"
```

Run `uv lock --project v6`, and set `expected_version='0.6.0'` plus `solver="$repo/v6"` in `v6/run.sh`. Create thin root launchers that execute `v6/run.sh` without resolving anything through `.worktrees`.

- [ ] **Step 4: Run launcher and preservation tests**

Run:

```bash
uv run --frozen python -m unittest -v test_v6_launchers test_preserved_versions
uv run --project v6 --frozen python -m unittest discover -s v6 -v
```

Expected: all tests pass; v6 reports 0.6.0 and the copied v5 scientific suite remains green.

- [ ] **Step 5: Commit the version boundary**

```bash
git add docs/v5-runtime.json v6 go6.sh go_v0.6.0.sh test_v6_launchers.py test_preserved_versions.py
git commit -m "feat: establish independent v6 runtime"
```

---

### Task 2: Ship and validate the exact reference ephemeris

**Files:**
- Create: `v6/scripts/build_planet_ephemeris_cache.py`
- Create: `v6/data/planet-reference-1850-2036.npz`
- Modify: `v6/point_star_planet_ephemeris.py`
- Modify: `v6/test_point_star_planet_ephemeris.py`

**Interfaces:**
- Produces: `load_ephemeris(start_jyear=1850., end_jyear=2036., cache_dir=DEFAULT_CACHE_DIR, bundled_path=BUNDLED_REFERENCE) -> tuple[np.ndarray, dict[str, np.ndarray], dict]`.
- Produces: provenance keys `cache_source`, `cache_path`, `cache_bytes`, `cache_load_seconds`, and `cache_build_seconds`.
- Produces: `EphemerisProvider(jd, vectors, exact_function=planet_vectors)` with `interpolated(name, dates)`, `exact(name, dates)`, and `counts()`.

- [ ] **Step 1: Add failing bundled-cache and provider tests**

Add tests that require a default full-range load to succeed while `planet_vectors` is patched to raise, reject a corrupted explicit bundled artifact, rebuild only into a supplied writable cache when the bundle is absent, and report the correct source/timings. Add the wished-for provider contract:

```python
provider = EphemerisProvider(jd, vectors, exact_function=exact)
estimated = provider.interpolated('mercury', jd[10:20] + 0.37)
authoritative = provider.exact('mercury', jd[10:20] + 0.37)
self.assertEqual(estimated.shape, (10, 3))
self.assertEqual(authoritative.shape, (10, 3))
self.assertEqual(provider.counts(), {
    'interpolated_calls': 1, 'interpolated_dates': 10,
    'exact_calls': 1, 'exact_dates': 10,
})
```

- [ ] **Step 2: Run the cache tests and verify RED**

Run:

```bash
cd v6 && uv run --frozen python -m unittest -v test_point_star_planet_ephemeris
```

Expected: FAIL because the bundle, provider, cache-source provenance and build command are absent.

- [ ] **Step 3: Implement strict bundle selection and provider interpolation**

Define:

```python
ROOT = Path(__file__).resolve().parent
BUNDLED_REFERENCE = ROOT/'data/planet-reference-1850-2036.npz'
INTERPOLATION_GUARD_ARCSEC = 5.0

class EphemerisProvider:
    def __init__(self, jd, vectors, exact_function=planet_vectors):
        self.jd = np.asarray(jd, dtype=np.float64)
        self.vectors = {name: np.asarray(value, dtype=np.float64)
                        for name, value in vectors.items()}
        self.exact_function = exact_function
        self._counts = dict(interpolated_calls=0, interpolated_dates=0,
                            exact_calls=0, exact_dates=0)

    def interpolated(self, name: str, jd_tdb) -> np.ndarray:
        dates = np.atleast_1d(np.asarray(jd_tdb, dtype=np.float64))
        indices = np.searchsorted(self.jd, dates, side='right') - 1
        if np.any(indices < 1) or np.any(indices + 2 >= len(self.jd)):
            raise ValueError('Interpolated dates require four reference samples')
        u = ((dates-self.jd[indices]) /
             (self.jd[indices+1]-self.jd[indices]))[:, None]
        track = self.vectors[name]
        p0, p1, p2, p3 = (track[indices-1], track[indices],
                          track[indices+1], track[indices+2])
        value = .5*((2*p1) + (-p0+p2)*u +
                    (2*p0-5*p1+4*p2-p3)*u*u +
                    (-p0+3*p1-3*p2+p3)*u*u*u)
        self._counts['interpolated_calls'] += 1
        self._counts['interpolated_dates'] += len(dates)
        return value/np.linalg.norm(value, axis=1)[:, None]

    def exact(self, name: str, jd_tdb) -> np.ndarray:
        dates = np.atleast_1d(np.asarray(jd_tdb, dtype=np.float64))
        self._counts['exact_calls'] += 1
        self._counts['exact_dates'] += len(dates)
        return self.exact_function(name, dates)

    def counts(self) -> dict[str, int]:
        return dict(self._counts)
```

Use four adjacent exact daily vectors and normalized Catmull--Rom evaluation. Reject nonfinite/out-of-range dates and use exact grid values at endpoints. Validate a bundled artifact strictly; a corrupt artifact passed explicitly raises `ValueError`. When the default artifact is genuinely absent, build atomically in the writable ignored cache and record the fallback.

- [ ] **Step 4: Add the reproducible builder and generate the artifact**

The builder accepts `--output PATH` and `--verify PATH`; generation calls the existing chunked exact routine and verification rereads all arrays and the content digest. Generate the full artifact with the locked v6 environment:

```bash
v6/.venv/bin/python v6/scripts/build_planet_ephemeris_cache.py \
  --output v6/data/planet-reference-1850-2036.npz
v6/.venv/bin/python v6/scripts/build_planet_ephemeris_cache.py \
  --verify v6/data/planet-reference-1850-2036.npz
```

Expected digest: `ebf09fdcde047cc8f0b1a0030e212590bcb2db1555ab824e060d46e27c00adac`.

- [ ] **Step 5: Verify interpolation accuracy and cache reuse**

Add a deterministic stratified exact comparison spanning every decade and all planets. Assert unit norms and maximum angular error below the documented 5 arcsecond guard. Run the ephemeris tests twice; the second run must not build or modify the bundle.

- [ ] **Step 6: Commit the exact data layer**

```bash
git add v6/data/planet-reference-1850-2036.npz \
  v6/scripts/build_planet_ephemeris_cache.py v6/point_star_planet_ephemeris.py \
  v6/test_point_star_planet_ephemeris.py
git commit -m "feat(v6): ship validated planet ephemeris"
```

---

### Task 3: Batch exact visit refinement behind interpolated proposals

**Files:**
- Create: `v6/point_star_planet_refinement.py`
- Create: `v6/test_point_star_planet_refinement.py`
- Modify: `v6/point_star_planets.py`
- Modify: `v6/test_point_star_planets.py`

**Interfaces:**
- Produces: immutable `Visit(name, source, start, stop, visit_start, visit_stop)` and `Passage(date, name, source, cost, interval)` records.
- Produces: `batched_exact_minima(provider, name, visits, objective, xatol=1e-7) -> tuple[np.ndarray, np.ndarray]`.
- Produces: `refine_planet_visits(name, visits, context, provider) -> PlanetRefinementResult` containing ordered passages, provider counters and stage timings.
- Consumes: the same exact daily grid, fixed camera, detections, source gates and image-derived zenith already used by `search_planet_epochs`.

- [ ] **Step 1: Write failing batched-minimizer tests**

Compare batched minima with independent SciPy bounded scalar minima on curved, flat, boundary and multiple-window objectives. Require each exact minimum to remain in its original bracket and agree within `1e-7` day for isolated minima. Add a provider spy proving exact evaluations receive arrays containing every active visit rather than one scalar call per visit.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd v6 && uv run --frozen python -m unittest -v test_point_star_planet_refinement
```

Expected: FAIL because the refinement module and interfaces do not exist.

- [ ] **Step 3: Implement vectorized bounded exact minimization**

Use an array form of golden-section bounded minimization. Each iteration sends all active dates for one planet through one `provider.exact()` call, projects the returned vectors through the fixed camera, and updates each visit independently. Stop individual visits when their bracket is no wider than `1e-7` day; preserve their endpoints as explicit options just as v5 does.

Use `provider.interpolated()` to propose the local minimum and horizon/gate neighbourhood. Widen proposal decisions by `INTERPOLATION_GUARD_ARCSEC`, but retain and exactly search the full original bracket. Exact vectors determine the returned date, cost, altitude and detector gate.

- [ ] **Step 4: Route v6 individual visits through the new module**

Keep the KD-tree segment discovery in `search_planet_epochs`. Convert its windows to `Visit` records, call `refine_planet_visits` by planet, merge canonical `(date, name, source)` results, and leave v5 joint Hungarian assignment semantics intact. Pass `provider.exact` to negative-evidence and display prediction functions.

- [ ] **Step 5: Prove exact authority and v5 semantic equivalence**

Add regressions where interpolation deliberately puts a candidate just inside a gate while exact vectors put it outside, and vice versa. Assert only the exact result survives. Run the existing planet suite plus new comparisons of candidate identity/status/date/residual against the v5 scalar search fixtures.

- [ ] **Step 6: Commit batched refinement**

```bash
git add v6/point_star_planet_refinement.py v6/test_point_star_planet_refinement.py \
  v6/point_star_planets.py v6/test_point_star_planets.py
git commit -m "perf(v6): batch exact planet refinement"
```

---

### Task 4: Add deterministic per-planet process workers

**Files:**
- Modify: `v6/point_star_planet_refinement.py`
- Modify: `v6/point_star_planets.py`
- Modify: `v6/test_point_star_planet_refinement.py`
- Modify: `v6/test_point_star_planets.py`

**Interfaces:**
- Produces: `planet_worker_count(environ=os.environ, nonempty_groups: int = 0) -> int`.
- Produces: `refine_all_planets(grouped_visits, context, reference, workers) -> list[PlanetRefinementResult]`.
- Consumes: `WFS_PLANET_WORKERS`; positive integers are valid, `1` is serial, absent means `min(4, nonempty_groups, os.cpu_count() or 1)`.

- [ ] **Step 1: Write failing worker-selection and determinism tests**

Test absent, `1`, oversized, zero, negative and nonnumeric environment values. Run a synthetic two-planet search through workers 1 and 2 and compare candidates after removing only the `planet_search_performance` object. Require stable ordering and identical JSON-serializable numbers.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd v6 && uv run --frozen python -m unittest -v \
  test_point_star_planet_refinement test_point_star_planets
```

Expected: FAIL because worker selection and parallel refinement are absent.

- [ ] **Step 3: Implement module-level worker execution**

Use `ProcessPoolExecutor(max_workers=workers)` only for `workers > 1`. Submit one job per nonempty planet group. Worker payloads contain the planet track, visits, serialized fixed camera inputs, measured coordinates, source gates and zenith; workers read no files and write no output. Each worker builds its local provider and returns plain dataclasses/dicts.

The parent sorts results by the canonical `PLANETS` order and sorts passages by `(date, name, source)` before assignment. Exceptions include the planet name and propagate; do not silently retry through a scientifically different path.

- [ ] **Step 4: Verify serial/parallel equivalence repeatedly**

Run the focused suite with `WFS_PLANET_WORKERS=1`, `2`, and `4`, including a subprocess test so process spawning uses real imports. Confirm candidate products remain identical and no child creates files.

- [ ] **Step 5: Commit deterministic parallel execution**

```bash
git add v6/point_star_planet_refinement.py v6/point_star_planets.py \
  v6/test_point_star_planet_refinement.py v6/test_point_star_planets.py
git commit -m "perf(v6): parallelize planet visit groups"
```

---

### Task 5: Record stage timings and exact/interpolated work counters

**Files:**
- Create: `v6/point_star_planet_performance.py`
- Create: `v6/test_point_star_planet_performance.py`
- Modify: `v6/point_star_planets.py`
- Modify: `v6/point_star_planet_nondetections.py`
- Modify: `v6/test_planet_nondetections.py`

**Interfaces:**
- Produces: `PlanetSearchPerformance` with `start(stage)`, `finish(stage)`, `merge_worker(result)`, and `serialise()`.
- Produces: `planet_search_performance` inside `planet_epoch.json` and identical standalone `planet_search_performance.json`.
- Produces telemetry schema version 1 with cache, worker, stage, provider-call and candidate-count fields named in the approved spec.

- [ ] **Step 1: Write failing telemetry tests**

Use a fake monotonic clock with known increments and assert exact serialized values:

```python
self.assertEqual(saved['schema_version'], 1)
self.assertEqual(saved['workers']['requested'], 4)
self.assertEqual(saved['providers']['exact_dates'], 27)
self.assertEqual(saved['counts']['refined_visits'], 3)
self.assertAlmostEqual(saved['seconds']['total_planet_stage'], 1.25)
```

Assert `planet_epoch.json['planet_search_performance']` equals the standalone file. Assert changing the fake timing sequence cannot change candidate JSON after that object is removed.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd v6 && uv run --frozen python -m unittest -v \
  test_point_star_planet_performance test_point_star_planets test_planet_nondetections
```

Expected: FAIL because structured telemetry and standalone output do not exist.

- [ ] **Step 3: Instrument named stages without changing control flow**

Measure `cache_load`, `coarse_scan`, `interpolated_refinement`, `exact_refinement`, `joint_assignment`, `negative_evidence`, and `total_planet_stage` with `time.perf_counter()`. Merge worker call/date counts by addition. Store cache source/digest/bytes/build seconds, requested/used workers, and visit/source/joint counts.

Print one line in this form after the output is fixed:

```text
Planet performance: total 12.34 s; cache 0.08 s (bundled); coarse 0.42 s; refine 9.71 s; exact 245 calls/31,204 dates; workers 4.
```

- [ ] **Step 4: Run telemetry and complete v6 unit suites**

Run:

```bash
cd v6 && uv run --frozen python -m unittest discover -v
```

Expected: all v6 tests pass with no timing-based assertions.

- [ ] **Step 5: Commit telemetry**

```bash
git add v6/point_star_planet_performance.py v6/test_point_star_planet_performance.py \
  v6/point_star_planets.py v6/point_star_planet_nondetections.py \
  v6/test_planet_nondetections.py
git commit -m "feat(v6): report planet search performance"
```

---

### Task 6: Add reproducible v5/v6 comparison and release documentation

**Files:**
- Create: `v6/scripts/benchmark_planet_search.py`
- Create: `v6/test_planet_search_benchmark.py`
- Create: `v6/docs/PLANET_SEARCH_PERFORMANCE.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/CONSOLIDATION.md`
- Modify: `v6/README.md`
- Modify: `v6/docs/FEATURE_STATUS.md`
- Modify: `v6/docs/PERFORMANCE.md`
- Modify: `v6/SOURCE_MANIFEST.json`
- Modify: `test_preserved_versions.py`

**Interfaces:**
- Produces: `benchmark_planet_search.py --v5-analysis DIR --v6-analysis DIR --image PATH --repetitions 3 --json OUTPUT`.
- Produces: comparison JSON with raw repetitions, medians, ratio, cache states, worker count and scientific-difference summary.
- Preserves: v5 hashes in `docs/v5-runtime.json`; v6 manifest covers the binary ephemeris and all v6 runtime/test/docs files.

- [ ] **Step 1: Write failing benchmark-comparison tests**

Test median/ratio calculation with fixed fixture timings and scientific comparison with reordered JSON keys. Performance fields are the only excluded keys. A changed candidate identity, status, match, epoch beyond tolerance or exact residual beyond tolerance must fail the comparison.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd v6 && uv run --frozen python -m unittest -v test_planet_search_benchmark
```

Expected: FAIL because the benchmark module is absent.

- [ ] **Step 3: Implement the subprocess benchmark harness**

Use `sys.executable`-independent explicit v5/v6 interpreter paths, unique temporary output copies and `time.perf_counter()`. Never delete supplied analysis directories. Emit machine/platform, CPU count, commands, repetition values, medians and `v5_median_seconds / v6_median_seconds` as `speedup_ratio`.

- [ ] **Step 4: Run controlled planetary and full-launcher benchmarks**

Use the Espenak image and unique output directories. Run the isolated planetary stage three warm times for each version, then one complete launcher run each:

```bash
/usr/bin/time -v ./go5.sh /home/pth/Skrivebord/StarTrails/FishEye18-1021w_Espenak.jpg
/usr/bin/time -v ./go6.sh /home/pth/Skrivebord/StarTrails/FishEye18-1021w_Espenak.jpg
```

Set `WFS_PLANET_WORKERS=4` for the v6 benchmark and record a separate serial v6 stage run. Require median planetary speedup `>= 2.0`. Compare exact scientific products and record every bounded numerical difference.

- [ ] **Step 5: Update preservation, user and scientific documentation**

Document v6 selection/install/output, bundled-cache behaviour, worker override, telemetry fields, benchmark machine/results, exact-final authority and unchanged limitations. Update `AGENTS.md` so legacy, v4 and v5 are frozen and upgrades occur in v6. Update `docs/CONSOLIDATION.md` with the v5 manifest boundary.

- [ ] **Step 6: Regenerate and verify the v6 source manifest**

Set manifest version `0.6.0`, base commit `1e22756`, list numerical/performance changes, and hash every owned source, test, document, catalogue, lockfile and ephemeris artifact. Run `test_preserved_versions` to confirm inventory completeness and v5 immutability.

- [ ] **Step 7: Commit benchmark evidence and release documentation**

```bash
git add README.md AGENTS.md docs/CONSOLIDATION.md test_preserved_versions.py \
  v6/scripts/benchmark_planet_search.py v6/test_planet_search_benchmark.py \
  v6/docs v6/README.md v6/SOURCE_MANIFEST.json
git commit -m "docs(v6): record planet search speedup"
```

---

### Task 7: Verify all preserved and new runtimes

**Files:**
- Verify only; modify files only in response to a reproduced failing regression.

**Interfaces:**
- Confirms: legacy, v4, v5 and v6 work from the repository without `.worktrees` in runtime paths.
- Confirms: v5 hashes, v6 manifest, exact candidate semantics and performance acceptance.

- [ ] **Step 1: Run all root/version unit suites**

```bash
uv run --frozen python -m unittest discover -v
cd v4 && uv run --frozen python -m unittest discover -v
cd ../v5 && uv run --frozen python -m unittest discover -v
cd ../v6 && uv run --frozen python -m unittest discover -v
```

Expected: all tests pass; only documented optional consumer tests may skip.

- [ ] **Step 2: Run all four demos with unique outputs**

From the repository root:

```bash
./demo.sh --output results/check-v6-legacy
./v4/demo.sh --output results/check-v6-v4
./v5/demo.sh --output results/check-v6-v5
./v6/demo.sh --output results/check-v6-v6
```

Expected: all historical thresholds pass without changes to reference products.

- [ ] **Step 3: Re-run exact-data, serial/parallel and benchmark checks**

Verify the bundled ephemeris digest, compare worker counts 1 and 4, rerun the three-repeat planetary benchmark, and confirm `speedup_ratio >= 2.0` with identical scientific status and identities.

- [ ] **Step 4: Inspect the final diff and runtime isolation**

Run:

```bash
git diff origin/main --check
git diff origin/main --stat
git status --short
git diff --exit-code origin/main -- v5 go5.sh go_v0.5.0.sh
```

Expected: no whitespace errors, no unintended files, and an empty v5/launcher diff.

- [ ] **Step 5: Commit any verification-only manifest refresh**

If the final v6 hash manifest changed solely because an already-reviewed v6 file changed during verification, regenerate it, rerun its test, and commit:

```bash
git add v6/SOURCE_MANIFEST.json
git commit -m "chore(v6): finalize source manifest"
```

If no manifest refresh is necessary, do not create an empty commit.
