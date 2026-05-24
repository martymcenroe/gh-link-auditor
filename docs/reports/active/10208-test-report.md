# 10208 - Test Report

**Issue:** #208
**Branch:** `208-fix-stealer-diff`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2424 passed, 1 skipped |
| After this PR | 2431 passed, 1 skipped |
| Net | +7 new tests |

## New tests

`tests/unit/test_pr_tracker.py`:

### `TestExtractPrUrlChange` (4 tests)

- `test_extracts_clean_single_url_swap` — `-` line + `+` line each containing a URL → returns the tuple
- `test_returns_none_on_multi_url_diff` — 2 removals + 2 additions → returns None (out of scope)
- `test_returns_none_on_no_urls` — text-only diff → returns None
- `test_returns_none_on_gh_failure` — `gh pr diff` exits non-zero → returns None

### `TestCheckFixStealDiff` (3 tests)

- `test_detects_byte_equivalent_steal` — PR has clean URL swap; subsequent commit contains the same swap → `(True, sha)` with the stealing commit SHA
- `test_returns_false_when_no_pr_diff` — gh pr diff fails → `(False, None)` early-exit
- `test_returns_false_when_no_matching_commit` — PR has clean URL swap but no commit on default branch contains it → `(False, None)`

## Dependency injection (no MagicMock)

Both new functions accept `gh_run` and `gh_get` callable kwargs for offline testing. Production defaults call `subprocess.run("gh ...")` and parse JSON. Tests inject lambdas returning `_mock_completed(...)` (the same helper the existing `TestCheckMaintainerFixed` tests use). No MagicMock added.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | clean (1 file auto-reformatted) |
| `poetry run ruff check .` | clean |

## Coverage

`_extract_pr_url_change`: 4 paths (clean / multi-URL / no-URLs / gh failure) covered.
`check_fix_steal_diff`: 3 paths (positive / no-diff / no-matching-commit) covered.
Auto-blacklist wiring in `refresh_pr_outcomes`: not directly tested in this PR (integration test would require setting up the full outcome refresh path with N6 stubs). The function-level confidence is sufficient; the integration is straightforward.

## No regressions

`poetry run pytest -q`: **2431 passed, 1 skipped**.
