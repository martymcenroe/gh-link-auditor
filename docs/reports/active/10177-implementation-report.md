# Implementation Report: #177 write tier1_pending after first PR submit

## Summary

The trust state machine in `unified_db.py` defined a `new → tier1_pending` transition (per #149) but production code never wrote it. Only tests did. A repo with an in-flight PR stayed indistinguishable from one we'd never touched. This PR closes that gap by wiring `n6_submit_pr` to update trust state immediately after a successful PR creation.

See LLD-177 for the design.

## Changes

### `src/gh_link_auditor/pr_tracker.py`
- Added public function `update_trust_on_submit(udb, repo_full_name)`. Mirrors the existing private `_update_trust_on_merge` pattern but for the submit event. Public (no underscore) because the caller lives in a different module.
- Behavior:
  - No trust record → insert as `tier1_pending`, `total_prs=1`.
  - `new` → transition to `tier1_pending`, increment `total_prs`.
  - `tier1_pending` / `tier1_proven` / `tier2_eligible` → keep level, increment `total_prs` (idempotent; never downgrades).

### `src/gh_link_auditor/pipeline/nodes/n6_submit_pr.py`
- After `pr_url` is captured and stored in state, opens `UnifiedDatabase(state["db_path"])` and calls `update_trust_on_submit`. Lazy imports inside the function avoid pulling unified_db at module-import time.
- Wrapped in `try/except`: trust update is best-effort metadata; a failed DB write never aborts a successful PR (only logs a warning).
- Guarded by `if db_path:` so unit tests that bypass `create_initial_state` (and thus have no `db_path` in state) still pass without modification.

## Tests

### `tests/unit/test_trust_escalation.py` — new `TestUpdateTrustOnSubmit` class
- `test_creates_trust_for_unknown_repo_as_tier1_pending` — no prior record → `tier1_pending`.
- `test_transitions_new_to_tier1_pending` — explicit `new` → `tier1_pending`.
- `test_idempotent_for_tier1_pending` — already `tier1_pending` → stays, `total_prs` increments.
- `test_does_not_downgrade_tier1_proven` — at `tier1_proven` → stays, `total_prs` increments, `total_merges` unchanged.
- `test_does_not_downgrade_tier2_eligible` — at `tier2_eligible` → stays, `total_prs` increments.

### `tests/unit/pipeline/test_n6.py` — two new tests in `TestN6SubmitPr`
- `test_writes_tier1_pending_trust_on_success` — happy-path mock + real `UnifiedDatabase` at `tmp_path`. After `n6_submit_pr` returns, opens the DB and asserts the repo is at `tier1_pending`.
- `test_trust_update_failure_does_not_abort_pr` — `update_trust_on_submit` is patched to throw; the PR URL is still returned in state and no error surfaces from n6.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/pr_tracker.py` | NEW `update_trust_on_submit` |
| `src/gh_link_auditor/pipeline/nodes/n6_submit_pr.py` | call `update_trust_on_submit` after PR creation |
| `tests/unit/test_trust_escalation.py` | NEW `TestUpdateTrustOnSubmit` (5 tests) |
| `tests/unit/pipeline/test_n6.py` | 2 new tests for the n6 hook |
| `docs/lld/active/LLD-177.md` | NEW — design |

## Test count baseline

`pytest --co -q` collects **1764 tests** post-change (was 1758 + 6 new from this PR + 0 removed = 1764).
