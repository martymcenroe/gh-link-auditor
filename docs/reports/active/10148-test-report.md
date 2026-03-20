# Test Report: #148 Snooze key in HITL + recheck queue + ghla recheck command

## Test Results

- **Total tests**: 1644 passed, 1 skipped
- **New tests added**: 35
- **No regressions**: All existing 1609 tests continue to pass

## Test Breakdown

### N4 Human Review Tests (`tests/unit/pipeline/test_n4.py`)
New tests added (7):
- `test_snooze_with_z` - 'z' input returns _SNOOZE sentinel
- `test_snooze_with_snooze` - 'snooze' input returns _SNOOZE sentinel
- `test_prompt_text_includes_snooze` - prompt text mentions snoo[z]e option
- `test_snooze_marks_not_approved` - snooze marks verdict approved=False
- `test_snooze_calls_snooze_to_db` - snooze calls _snooze_to_db with correct args
- `test_snooze_continues_to_next_verdict` - snooze one, approve next
- `test_snooze_does_not_set_review_aborted` - snooze does not abort review

### _snooze_to_db Tests (`tests/unit/pipeline/test_n4.py`)
New tests added (4):
- `test_writes_to_recheck_queue` - verifies DB entry written correctly
- `test_handles_missing_db_path` - no db_path logs warning, no crash
- `test_handles_db_error_gracefully` - DB errors caught gracefully
- `test_uses_target_when_no_repo_parts` - falls back to target for repo_full_name

### Schema and DB Method Tests (`tests/unit/test_snooze_recheck.py`)
New tests added (35 total in file):
- **TestSchemaV3** (8): version is 3, all new columns exist
- **TestMigrationV2ToV3** (2): migration adds columns to v2 table, idempotent on v3
- **TestSnoozeFinding** (11): returns ID, stores fields, default/custom snooze days, reason, initial count/status, multiple snoozes
- **TestGetDueRechecks** (6): empty queue, returns due entries, excludes future/resolved/confirmed_dead, ordered by snooze_until
- **TestCompleteRecheck** (3): marks resolved, marks confirmed_dead, updates last_checked_at
- **TestIncrementRecheck** (5): increments count, double increment, re-snoozes 7 days, resets status, custom snooze days
- **TestGetRecheckStats** (5): empty queue, counts snoozed as pending, counts resolved/confirmed_dead, mixed statuses

### CLI Recheck Command Tests (`tests/unit/cli/test_recheck_cmd.py`)
New tests added (12):
- **TestRecheckParser** (4): subcommand exists, db-path arg, dry-run flag, default no dry-run
- **TestCmdRecheck** (8): no due rechecks, dry-run does not modify, resolved when live, re-snoozed when still dead, confirmed dead after 3 checks, multiple entries, queue stats shown, None status code treated as dead, 301 treated as live

## Coverage

All new modules and methods are tested. The test-to-implementation ratio for new code is high:
- `unified_db.py` snooze methods: 30 tests for 5 methods
- `n4_human_review.py` snooze: 11 tests for prompt + node + helper
- `recheck_cmd.py`: 12 tests for parser + command logic
