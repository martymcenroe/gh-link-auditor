# 10244 Implementation Report

**Issue:** #244
**Branch:** `244-non-destructive-stage3`

## What changed

| File | Change |
|---|---|
| `unified_db.py` | Schema bumped v6 → v7. Three new columns on `bulk_scan_findings`: `investigation_state` (default `'pending'`), `investigation_completed_at`, `investigation_attempts`. New `bulk_scan_locks` table. New `_migrate_v6_to_v7` migration (adds columns, marks existing non-pending method rows as `'derived_candidate'`, creates lock table). |
| `bulk_scan/process_lock.py` (new) | `acquire(db, run_id)` and `release(db, run_id)` using the `bulk_scan_locks` table. Stale locks (PID not alive per `psutil.pid_exists`) are automatically reclaimed. Raises `LockBusyError` if another live process holds the lock. |
| `bulk_scan/runner.py` | New `_mark_finding(db, finding_id, new_state)` helper for non-destructive state transitions. `run_investigation` rewritten: no DELETEs of `bulk_scan_findings` rows. Each finding's state transition + derived-candidate insert happens in a single `with db._conn:` transaction. Pending-row query now filters on `investigation_state='pending'` so resumes are idempotent. `run_full` wraps execution in `acquire`/`release` via try/finally. |
| `cli/bulk_scan_cmd.py` | `_cmd_start` catches `LockBusyError` and exits 2 with a clear error message. |
| `pyproject.toml` | Added `psutil` for cross-platform PID-alive checks. |

## State machine

`bulk_scan_findings.investigation_state` values:

| State | Set by | Meaning |
|---|---|---|
| `pending` | Stage 1 (default) | Not yet processed by Stage 3 |
| `skipped_language` | Stage 3 | Repo's `detected_language` not in `INCLUDE_LANGUAGES` |
| `skipped_alive` | Stage 3 | URL came back 2xx in cache; no investigation needed |
| `investigated_no_candidate` | Stage 3 | Investigated, but no tier-1 candidate met threshold |
| `investigated_with_candidate` | Stage 3 | Investigated, derived-candidate row(s) inserted |
| `derived_candidate` | Stage 3 (on the INSERTed candidate) | Real Stage 3 output; surfaced by Stage 4 |

Scoring still reads `WHERE method != 'pending'` — that filters to `derived_candidate` rows, which is what we want in the final report. No change to scoring.

## Why this fixes the 2026-05-22 incidents

### Incident A: wrong status reset → empty `liveness_results` → "everything is alive" deletes

**Before:** every finding got `is_dead_result({}) → False` → DELETE → no replacement → all 109,692 placeholder rows gone. Recovery required `tools/regenerate_findings.py` + raw CDN re-fetches.

**After:** every finding gets `investigation_state='skipped_alive'` (a row update, not a delete). On resume with corrected `liveness_results`, the runner sees those rows as already-processed and moves on. To "redo" them with proper liveness data, an operator would explicitly reset them: `UPDATE bulk_scan_findings SET investigation_state='pending' WHERE ...`. No data loss.

### Incident B: two `bulk-scan start` invocations against the same run-id

**Before:** both processes called `run_investigation`, both saw the same pending rows, both tried to DELETE the same IDs, neither produced replacements, pending count was frozen but findings vanished anyway.

**After:** the second process raises `LockBusyError` and exits with code 2. Only one bulk-scan can run per (run-id, host).

### Incident C: crash mid-investigation

**Before:** if the process died between `DELETE FROM bulk_scan_findings WHERE id=?` and `INSERT INTO bulk_scan_findings ... (candidate)`, the placeholder was gone with no replacement.

**After:** UPDATE + INSERT happen inside a single `with db._conn:` transaction. Crash → rollback → finding stays `pending` → next run picks it up.

## Operational steps for `bulk-20260514T042627`

After merge:
1. `git pull --ff-only` (gets v7 migration)
2. `poetry install` (gets psutil)
3. Reset status: `UPDATE bulk_scan_runs SET status='checking', completed_at=NULL WHERE run_id='bulk-20260514T042627'` (one-time, since #229 isn't done yet)
4. `poetry run python -m gh_link_auditor.cli.main bulk-scan start --run-id bulk-20260514T042627`
   - Migration runs on first open → 109,692 findings get `investigation_state='pending'`
   - Lock acquired
   - Stage 2 cache-rehydrates `liveness_results`
   - Stage 3 marks states for each finding (skipped_alive / skipped_language / investigated_*)
   - Stage 4 surfaces candidates; report written
   - Lock released

## Verification

- 25 new + updated tests pass (15 in runner, 8 in process_lock, 2 in storage)
- Full repo suite ran clean
- `ruff check` + `ruff format` clean
- Schema migration tested explicitly (v5→v7 chain on an existing v5 DB)
- Crash-safety: the `with db._conn:` transaction wrapping guarantees atomicity per finding

## Out of scope

- Operator CLI to reset findings to `pending` state (would let manual re-investigation of `skipped_alive` rows that were mis-classified) — future ergonomics work
- Splitting `bulk_scan_findings` into two tables (`findings` + `candidates`) for cleaner data model — current single-table design is sufficient; future refactor option
- Cross-host locks (shared DB on network filesystem) — single-operator tool today
