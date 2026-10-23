# V23 MMTO Weather Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fully unattended, fail-open MMTO summit-humidity gate that rejects fresh RH readings at or above 80% before candidates consume the v23 image cap.

**Architecture:** A new focused module fetches and matches the two public summit Vaisala histories, returning auditable tri-state decisions. The v23 planner queries once per observing-night range, applies decisions before adding candidates, continues scanning to fill the cap, and writes aggregate plus per-candidate audit output without exposing weather to the blind solver.

**Tech Stack:** Python 3.12 standard library HTTP/JSON, existing v23 pipeline dataclasses and `unittest` suite.

**Spec:** `docs/superpowers/specs/2026-10-23-v23-mmto-weather-gate-design.md`

## Global Constraints

- Develop only in v23 and its active launchers; do not modify frozen v22 or earlier runtimes.
- Weather may filter acquisition but must not enter or seed blind source detection, association, fitting, or saved astrometry.
- Fresh RH `< 80.0%` accepts; fresh RH `>= 80.0%` skips; missing, stale, malformed, or failed telemetry accepts by fail-open fallback.
- The nearest weather sample must be no more than 120 seconds from the candidate UTC timestamp; do not interpolate or carry values through gaps.
- Weather-skipped candidates do not consume `--max-images`.
- Preserve unrelated working-tree changes and historical evidence.

## Review Focus

- One Vaisala sensor fails while the other is fresh: use the available sensor rather than failing the request.
- Both sensors are fresh but disagree: use the larger RH value.
- A sample exactly 120 seconds away is fresh; a sample even slightly older is unknown/fail-open.
- An RH value exactly 80.0% skips, while 79.999% accepts.
- API timeout, HTTP error, malformed JSON, invalid value, or empty response cannot abort the pipeline and cannot reject an image.

---

### Task 1: Summit weather retrieval and tri-state decisions

**Files:**
- Create: `scripts/mmto_weather.py`
- Create: `test_mmto_weather.py`

**Interfaces:**
- Produces: `WeatherSample(sensor: str, observed_utc: datetime, humidity_percent: float)`
- Produces: `WeatherDecision(status: str, humidity_percent: float | None, sample_utc: datetime | None, age_seconds: float | None, sensor: str | None, reason: str)`
- Produces: `MmtoWeatherHistory.fetch(start_utc: datetime, end_utc: datetime) -> MmtoWeatherHistory`
- Produces: `MmtoWeatherHistory.decide(observed_utc: datetime, *, max_humidity_percent: float = 80.0, max_age_seconds: float = 120.0) -> WeatherDecision`

- [ ] **Step 1: Write failing unit tests for threshold and freshness boundaries**

Test 79.999% -> `accept`, 80.0% -> `skip`, exactly 120 seconds -> fresh, and more than 120 seconds -> `unknown`.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run --frozen python -m unittest -v test_mmto_weather.py`

Expected: FAIL because `scripts.mmto_weather` does not exist.

- [ ] **Step 3: Implement immutable sample, decision, and history types**

Validate timezone-aware UTC comparisons and finite RH values in the inclusive range 0–100. Match without interpolation and choose the larger fresh sensor value.

- [ ] **Step 4: Add failing retrieval tests**

Exercise two successful sensor responses, one failed sensor, both failed,
empty arrays, malformed JSON, non-finite/out-of-range values, and millisecond
epoch conversion using an injected opener.

- [ ] **Step 5: Implement bounded POST retrieval**

POST `table=measurements`, one sensor field, and integer UTC `start`/`end`
seconds to the public history endpoint. Convert every retrieval failure to an
empty sensor result plus an audit reason; never raise it into the planner.

- [ ] **Step 6: Run focused tests**

Run: `uv run --frozen python -m unittest -v test_mmto_weather.py`

Expected: PASS.

### Task 2: Apply weather before the bounded selection cap

**Files:**
- Modify: `scripts/run_mmto_photometry_pipeline_v23.py`
- Modify: `test_run_mmto_photometry_pipeline_v23.py`

**Interfaces:**
- Consumes: `MmtoWeatherHistory.fetch(...)` and `.decide(...)` from Task 1.
- Produces: `AcquisitionPlan.weather_decisions`, `weather_accepted`, `weather_skipped`, and `weather_unknown`.
- Produces CLI options `--max-humidity-percent` and `--weather-max-age-seconds`.

- [ ] **Step 1: Write failing planner tests**

Inject a fake weather provider and assert: RH 79.9 is selected; RH 80.0 is
skipped; unknown is selected; skipped candidates do not consume capacity; and
selection continues into the next night to fill the cap.

- [ ] **Step 2: Run the planner tests and verify they fail**

Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v23.py`

Expected: FAIL because the planner lacks weather inputs and counters.

- [ ] **Step 3: Add CLI validation and planner injection**

Add the two configured limits, default the runtime provider to the public MMTO
history client, and retain an injectable provider for deterministic tests.

- [ ] **Step 4: Gate each cadence winner before selection**

Fetch history once per listed observing-night range. Apply the decision before
adding an unfinished candidate, count every result, and continue scanning until
the requested qualifying-image cap is filled or the date range is exhausted.

- [ ] **Step 5: Run focused planner tests**

Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v23.py test_mmto_weather.py`

Expected: PASS.

### Task 3: Persist an unattended audit trail

**Files:**
- Modify: `scripts/run_mmto_photometry_pipeline_v23.py`
- Modify: `test_run_mmto_photometry_pipeline_v23.py`
- Modify: `docs/FEATURE_STATUS.md`

**Interfaces:**
- Consumes: acquisition-plan weather decisions from Task 2.
- Produces: `<run>/weather-decisions.jsonl` and `pipeline_summary.json` weather counts/configuration.

- [ ] **Step 1: Write failing audit-output tests**

Assert JSON-lines records contain candidate URL/time, status, RH, sensor,
sample UTC, age, and reason; assert summary counts and thresholds; assert no
record requests manual review.

- [ ] **Step 2: Run the audit tests and verify they fail**

Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v23.py`

Expected: FAIL because weather audit output is absent.

- [ ] **Step 3: Write deterministic weather audit output**

Sort records by candidate UTC then URL, write atomically where practical, and
include its path plus aggregate counts in `pipeline_summary.json` and the plan
line printed to stdout.

- [ ] **Step 4: Document operational behavior**

Record the exact 80% threshold, 120-second freshness window, fail-open policy,
external source, UTC matching rule, and absence of manual intervention in
`docs/FEATURE_STATUS.md`.

- [ ] **Step 5: Run focused tests**

Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v23.py test_mmto_weather.py`

Expected: PASS.

### Task 4: Regression and runtime verification

**Files:**
- Modify if required: `v23/SOURCE_MANIFEST.json`
- Modify if required: `v23/scripts/update_v23_manifest.py`

**Interfaces:**
- Consumes: completed weather gate and audit trail.
- Produces: verified active v23 runtime with preserved historical versions.

- [ ] **Step 1: Update the v23 source manifest deliberately**

Include every new active-runtime file and refresh only hashes owned by the v23
manifest workflow.

- [ ] **Step 2: Run syntax and focused verification**

Run: `uv run --frozen python -m py_compile scripts/mmto_weather.py scripts/run_mmto_photometry_pipeline_v23.py`

Run: `uv run --frozen python -m unittest -v test_mmto_weather.py test_run_mmto_photometry_pipeline_v23.py`

Expected: PASS.

- [ ] **Step 3: Run the required complete regression suite**

Run: `uv run --frozen python -m unittest discover -v`

Expected: PASS without weakened thresholds.

- [ ] **Step 4: Run the required demonstration**

Run: `./demo.sh --output results/check-unique-name`

Expected: exit 0 with a new, unique output directory and preserved historical
reference files.

- [ ] **Step 5: Perform a bounded live dry run**

Run: `./go_mmto_photometry_v23.sh --dry-run --max-images 5`

Expected: at most five selected images, printed weather counts, RH >=80%
candidates omitted, and missing weather represented as unknown/fail-open.
