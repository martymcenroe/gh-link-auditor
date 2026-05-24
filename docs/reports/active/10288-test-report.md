# 10288 - Test Report

**Issues:** #288, #290, #294
**Branch:** `288-preflight-gates-batch2`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2347 passed, 1 skipped |
| After this PR | 2360 passed, 1 skipped |
| Net | +13 new tests |

## New tests

`tests/unit/preflight/test_gates.py`:

- `TestGateAntiAi` (4): no policy files → PASS; subagent clean → PASS; subagent hostile → FAIL; subagent uncertain → `needs_operator_review` reason
- `TestGateBlacklist` (4): not blacklisted; repo blacklisted; maintainer blacklisted (covers the previously-unused plumbing — #208's missing call site); defensive PASS when db is None
- `TestGateRedirectTargetRelated` (4): no redirect; subagent clean; subagent unrelated; defensive PASS on no candidate_url
- `TestRunPreflightNeedsReviewDispatch` (1): `reason="needs_operator_review"` routes to NEEDS_OPERATOR_REVIEW verdict (not HARD_GATE_FAILED)

## Modified existing tests

`TestHardGatesRegistry::test_registry_contains_all_seven_pr_delta_gates` → renamed `test_registry_contains_all_ten_gates_after_pr_epsilon`; asserts 10-callable registry with the full gate-name set.

## FakeSubagent (no MagicMock)

`tests/fakes/subagent.py:FakeSubagent` (from #287) is used for every subagent injection. Production uses `RealSubagent` (the `claude --print` wrapper); tests inject `FakeSubagent.configure(default=SubagentVerdict.<verdict>)` to assert each verdict path deterministically. No MagicMock added.

## Coverage on new code

- `gate_anti_ai`: all 4 paths (no-files / clean / hostile / uncertain) + fallback path covered
- `gate_blacklist`: both axes (repo, maintainer) + defensive None-db path
- `gate_redirect_target_related`: no-redirect / clean / unrelated / defensive paths
- `run_preflight` verdict routing: NEEDS_OPERATOR_REVIEW path covered by the dispatch test

≥95% line coverage on new code, per project hard rule.

## No regressions

`poetry run pytest -q`: **2360 passed, 1 skipped**.
