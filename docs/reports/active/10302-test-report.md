# 10302 - Test Report

**Issues:** #302, #305, #306, #307, #308, #309
**Branch:** `302-preflight-scores-batch2`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2378 passed, 1 skipped |
| After this PR | 2407 passed, 1 skipped |
| Net | +29 new tests |

## New tests

`tests/unit/preflight/test_scores.py`:

- `TestScoreC5` (4): full 15 on clean; partial 8 on partial; zero on unrelated; zero on no candidate URL
- `TestScoreR1Stars` (6 parametrized): each tier boundary verified
- `TestScoreR2Recency` (3): ≤7d → 5pt; >365d → 0pt; missing pushed_at → 0pt
- `TestScoreR3OutsiderMergeRate` (4): full 5 at 30%+; zero when no outsider PRs; zero on empty pulls; cache hit on second call
- `TestScoreR4MaintainerStructure` (4): full for org-owned; full for ≥2 contributors; full when CODEOWNERS exists; partial 2 for solo
- `TestScoreR5License` (8 parametrized): each license tier (permissive=5, non-permissive=2, none=0)

`TestCorrectnessScoresRegistry::test_registry_has_twelve_scores_after_pr_theta`: asserts the full 12-callable registry

## Dependency injection (no MagicMock)

- C5 uses `FakeSubagent.configure(default=SubagentVerdict.<verdict>)` (same pattern as gate #1 / #7)
- R3 / R4 accept `gh_get` callable for offline testing
- R1 / R2 / R5 use `monkeypatch.setattr("...scores.fetch_repo_metadata", ...)` (now that `fetch_repo_metadata` is hoisted to module-level)

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | clean |
| `poetry run ruff check .` | clean (1 auto-fix for line length) |

## Coverage

Every new score function has at least 2 tests; tiered scores have parametrized coverage of each boundary. ≥95% line coverage on new code, per project hard rule.

## No regressions

`poetry run pytest -q`: **2407 passed, 1 skipped**.
