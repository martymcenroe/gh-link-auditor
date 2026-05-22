# 10231 Test Report

**Issue:** #231
**Branch:** `231-reject-unknown-runid`

## Test inventory

10 new tests, 6 + 4 split.

### `TestCmdStartRunIdGate` (6)

Covers all five rows of the flag-matrix plus the "Did you mean" surfacing:

- `test_unknown_run_id_rejects_without_new_run` — exit 2, error mentions `--new-run`
- `test_unknown_run_id_with_new_run_proceeds` — passes through to runner (mocked)
- `test_existing_run_id_resumes_without_new_run` — runner gets called, no error
- `test_existing_run_id_with_new_run_rejected` — exit 2, "already exists"
- `test_no_run_id_autogenerates` — auto-generated id starts with `bulk-`, runner gets called
- `test_suggestion_surfaces_close_match` — typo `bulk-20260514T042627` surfaces `bulk-20260514T042627Z` in error

### `TestSuggestRunIds` (4)

Unit tests for the prefix-matcher:

- `test_longest_prefix_first` — exact 2026-05-14 production typo case
- `test_no_overlap_returns_empty`
- `test_empty_db_returns_empty`
- `test_respects_max_suggest`

## Production-typo regression case

`test_suggestion_surfaces_close_match` codifies the exact 2026-05-14 incident:

```python
storage.create_run(db, "bulk-20260514T042627Z", 5, {})
storage.create_run(db, "bulk-20260514T030834Z", 5, {})
# operator typos:
rc = _cmd_start(args_with(run_id="bulk-20260514T042627"))
assert "bulk-20260514T042627Z" in stderr   # the Z-sibling is suggested
```

## Results

| Check | Result |
|---|---|
| Targeted (20 tests) | All pass |
| Ruff check | All checks passed |
| Ruff format | No changes |
