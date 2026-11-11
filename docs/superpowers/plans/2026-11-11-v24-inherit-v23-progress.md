# V24 Inherit V23 Acquisition Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first v24 MMTO invocation continue the established v23 acquisition queue instead of replaying images already completed by v23.

**Architecture:** V24 remains a distinct solver version, but acquisition completion spans the adjacent v23 and v24 runtimes. When no v24 state exists, the queue imports the validated v23 cursor and recent-night marker; explicit v24 state remains authoritative thereafter.

**Tech Stack:** Python 3.12, SQLite, `unittest`, existing MMTO acquisition pipeline.

**Spec:** `docs/superpowers/specs/2026-11-11-v24-visible-sky-mask-design.md`

## Global Constraints

- Do not modify frozen v23 runtime files or launchers.
- Preserve append-only databases and existing archive files.
- Keep new solves and receipts versioned as v24.
- Preserve the current-night check, weather gate, one-night-at-a-time listing, and image cap.
- Preserve unrelated working-tree changes.

## Review Focus

- A missing v24 state file with a valid v23 state must resume the v23 cursor exactly.
- V23 receipts must suppress duplicate v24 acquisition work, while older unrelated receipts must not.
- Existing v24 state must override v23 state after the first successful v24 run.
- A missing v23 state must retain the safe current-night initialization used by a genuinely new installation.
- Malformed or wrong-archive predecessor state must fail rather than silently reset progress.

---

### Task 1: Preserve predecessor queue progress

**Files:**
- Create: `test_run_mmto_photometry_pipeline_v24.py`
- Modify: `scripts/run_mmto_photometry_pipeline_v24.py`
- Modify: `docs/superpowers/specs/2026-11-11-v24-visible-sky-mask-design.md`
- Modify: `v24/README.md`
- Modify: `v24/HANDOFF.md`

**Interfaces:**
- `load_backfill_state(state_path, archive, default_night) -> BackfillState`
  imports the sibling v23 state only when the ordinary default-named v24 state
  is absent.
- `_processed_source_digests(results_database) -> set[str]` recognizes solver versions `0.23.0` and `0.24.0` as completed acquisition work.

- [ ] **Step 1: Write failing tests**

Test literal v23/v24 SQLite receipts and state JSON files. Assert that v23 receipts are complete, unrelated versions remain incomplete, v23 state is imported only when v24 state is absent, and explicit v24 state wins.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v24.py`

Expected: FAIL because v23 receipts and the predecessor state are ignored.

- [ ] **Step 3: Implement the minimal inheritance behavior**

Add the predecessor state fallback and exact adjacent-version receipt filter. Wire the default predecessor path to `RESULTS_DIR/mmto-v23-backfill-state.json` without changing explicit `--state-file` behavior.

- [ ] **Step 4: Run focused and inherited acquisition tests**

Run: `uv run --frozen python -m unittest -v test_run_mmto_photometry_pipeline_v24.py test_run_mmto_photometry_pipeline_v23.py`

Expected: PASS.

- [ ] **Step 5: Correct operator documentation**

Document that v24 inherits v23 acquisition progress and that v23 receipts suppress replay; v24 receipts remain distinct scientific records for images newly solved by v24.

- [ ] **Step 6: Run repository-required verification**

Run: `uv run --frozen python -m unittest discover -v`

Run: `./demo.sh --output results/check-unique-name`

Expected: both commands exit 0.
