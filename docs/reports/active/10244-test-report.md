# 10244 Test Report

**Issue:** #244
**Branch:** `244-non-destructive-stage3`

## New tests

### `tests/unit/bulk_scan/test_process_lock.py` (8 tests)

`TestAcquireRelease` (4):
- `test_first_acquire_succeeds` — single acquire writes a row with our PID + host
- `test_release_clears` — release deletes the row
- `test_release_safe_when_not_held` — release with no lock is a no-op (no exception)
- `test_release_only_removes_own_lock` — DELETE includes PID match; other-PID release is no-op

`TestConflictAndReclamation` (3):
- `test_concurrent_acquire_by_live_pid_raises` — second acquire with same-host + live-PID raises `LockBusyError` with descriptive message
- `test_stale_lock_reclaimed` — pre-seed a lock with a dead PID; new acquire reclaims and writes our PID
- `test_different_run_ids_no_conflict` — locks are per-run-id

`TestSchema` (1):
- `test_v7_schema_has_lock_table` — fresh DB has `bulk_scan_locks` table with expected columns

### `tests/unit/bulk_scan/test_runner.py::TestNonDestructiveStage3` (5 tests)

- `test_alive_url_marks_skipped_not_deleted` — alive URL → row preserved with state `skipped_alive` (was: DELETE)
- `test_language_skip_marks_state` — non-English repo's finding → state `skipped_language` (was: DELETE)
- `test_investigation_with_no_candidate_keeps_placeholder` — investigated but no tier-1 → state `investigated_no_candidate`, original row preserved
- `test_investigation_with_candidate_inserts_derived_row` — investigation produces candidate → original row → `investigated_with_candidate` + new row inserted with `method=<real>` and `investigation_state='derived_candidate'`
- `test_resume_idempotent` — second invocation against the same run does zero work (the loop filters on `investigation_state='pending'`); `investigation_attempts` counter only bumps once

### `tests/unit/bulk_scan/test_storage.py::TestSchemaV7` (3 tests, renamed)

- `test_schema_version == 7`
- `test_fresh_db_has_detected_language_column` — still passes (v7 inherits v6's column)
- `test_migration_v5_to_v6_adds_column` — renamed; verifies the full v5 → v7 migration chain runs cleanly and lands at the right schema version

## Updated tests

`tests/unit/bulk_scan/test_runner.py::TestLanguageFilter::test_run_investigation_skips_non_english`

- Assertion changed from "row was deleted" → "row preserved with state=skipped_language"

## Results

| Check | Result |
|---|---|
| Targeted bulk_scan suite (129 tests) | All pass |
| New tests (16 added) | All pass |
| `ruff check` | All checks passed |
| `ruff format` | Clean |
| Full repo suite | Run separately — see PR CI |

## Acceptance criteria — coverage

From the LLD:

- [x] Schema migration adds 3 columns + `bulk_scan_locks` table (tested in `test_storage.py`)
- [x] `run_investigation` never DELETEs from `bulk_scan_findings` (verified in `TestNonDestructiveStage3`)
- [x] Resumes are idempotent (`test_resume_idempotent`)
- [x] Concurrent invocations blocked (`test_concurrent_acquire_by_live_pid_raises`)
- [x] Stale lock reclaimed (`test_stale_lock_reclaimed`)
- [x] Stage 1 outputs survive Stage 3 misbehavior (every skip path is a non-destructive UPDATE)
- [x] Crash mid-finding: each transition wrapped in `with db._conn:` so rollback is automatic

## Scenarios reproduced from 2026-05-22 (post-fix)

Both incidents from today would now be non-destructive:

| Scenario | Old behavior | New behavior |
|---|---|---|
| Wrong status reset (empty `liveness_results`) | Every finding deleted as "alive" | Every finding marked `skipped_alive` (recoverable by SQL state reset) |
| Two processes racing same run-id | Both delete-then-no-insert, findings vanish | Second exits cleanly with `error: another bulk-scan process is running ...` |
| Crash mid-investigation | Placeholder gone, no candidate | Transaction rolls back, finding stays `pending` for retry |
