# Test Report: Trust-based PR Escalation (Issue #149)

## Test Summary

| Metric | Value |
|--------|-------|
| New tests added | 61 |
| Total tests after | 1639 + 61 = 1700 |
| Regressions | 0 |
| Coverage (modified files) | 97% |

## Test File

`tests/unit/test_trust_escalation.py` -- 61 tests in 10 test classes

## Coverage by Module

| Module | Coverage | Missing |
|--------|----------|---------|
| `unified_db.py` | 97% | Migration paths, import helpers |
| `n2_investigate.py` | 96% | Exception path in n2_investigate node |
| `graph.py` | 97% | build_pipeline_graph, run_pipeline |
| `pr_tracker.py` | 96% | _check_maintainer_fixed internals |

## Test Classes

### Trust State Machine (unified_db.py)
- `TestGetRepoTrust` (3 tests) -- get trust for unknown/known repos, all fields
- `TestUpdateRepoTrust` (6 tests) -- create, update, auto-create repo, partial
  update, blacklisted flag, all trust levels
- `TestCheckTier2Eligibility` (8 tests) -- no record, new, pending, no merge date,
  under/over/exactly 14 days, already eligible
- `TestGetTier1ProvenRepos` (3 tests) -- empty, only proven, multiple

### Tier Tagging (n2_investigate.py)
- `TestClassifyTier` (11 tests) -- all tier 1 methods verified, unverified downgrades,
  tier 2 methods, unknown methods
- `TestInvestigateDeadLinkTierTagging` (2 tests) -- tier annotation in candidates,
  unverified tier 1 becomes tier 2

### Fix Filtering (graph.py)
- `TestFilterFixesByTrust` (7 tests) -- tier 2 excluded for new/pending, not excluded
  for proven/eligible, tier 1 always passes, empty fixes, mixed tiers
- `TestGetRepoTrustLevel` (4 tests) -- local target, missing owner, from DB, DB error
- `TestPrPreviewGateTrustFiltering` (3 tests) -- filters for new repo, all excluded,
  no filtering for proven repo

### Trust Tracking (pr_tracker.py)
- `TestUpdateTrustOnMerge` (5 tests) -- creates for unknown, transitions new and
  tier1_pending to proven, increments for proven/eligible
- `TestUpgradeTier1ProvenRepos` (5 tests) -- upgrades eligible, skips under 14 days,
  skips non-proven, empty DB, multiple repos
- `TestRefreshPrOutcomesTrustIntegration` (2 tests) -- merge creates trust record,
  refresh upgrades eligible repos

### ReplacementCandidate TypedDict
- `TestReplacementCandidateTier` (3 tests) -- tier field present, optional, tier 2

## Regression Check

Full unit test suite: 1639 passed, 1 skipped, 0 failures.
