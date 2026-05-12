# Implementation Report: Trust-based PR Escalation (Issue #149)

## Summary

Implemented a trust-based PR escalation system with tier 1/tier 2 fix levels.
Repos progress through trust levels (new -> tier1_pending -> tier1_proven ->
tier2_eligible) based on PR merge outcomes. Risky (tier 2) fixes are excluded
for untrusted repos.

## Changes

### 1. Trust State Machine (`unified_db.py`)
- `get_repo_trust(repo_full_name)` -- returns trust dict or None
- `update_repo_trust(repo_full_name, trust_level, **kwargs)` -- upsert trust record
- `check_tier2_eligibility(repo_full_name)` -- True if merged PR + 14 days passed
- `get_tier1_proven_repos()` -- returns all tier1_proven repos for upgrade scanning

Uses existing `repo_trust` table (schema v2 placeholder from #125).

### 2. Tier Tagging (`pipeline/nodes/n2_investigate.py`)
- `classify_tier(method, verified_live)` -- classifies methods into tier 1 or tier 2
- Tier 1 (safe): redirect_chain, url_mutation, strip_index, wikipedia_suggest,
  github_api_redirect -- only when verified live
- Tier 2 (risky): sitemap_search, url_heuristic, or any unverified candidate
- Added `tier` key to `ReplacementCandidate` TypedDict

### 3. Fix Filtering (`pipeline/graph.py`)
- `_get_repo_trust_level(state)` -- looks up trust level from database
- `_filter_fixes_by_trust(fixes, verdicts, candidates, trust_level)` -- filters
  tier 2 fixes for "new" and "tier1_pending" repos
- Modified `_pr_preview_gate()` to apply trust-based filtering before display
- Shows excluded fix count in PR preview

### 4. Trust Tracking (`pr_tracker.py`)
- `_update_trust_on_merge(udb, repo_full_name, merged_at)` -- transitions
  trust level on PR merge
- `upgrade_tier1_proven_repos(udb)` -- scans tier1_proven repos and upgrades
  to tier2_eligible if 14 days have passed
- Hooked into `refresh_pr_outcomes()` for automatic trust transitions

### 5. State Changes (`pipeline/state.py`)
- `ReplacementCandidate` changed to `total=False` to support optional `tier` field
- Added `tier2_fixes_excluded` and `repo_trust_level` fields to `PipelineState`

## Files Modified

| File | Type |
|------|------|
| `src/gh_link_auditor/unified_db.py` | Trust state machine methods |
| `src/gh_link_auditor/pipeline/nodes/n2_investigate.py` | Tier tagging |
| `src/gh_link_auditor/pipeline/graph.py` | Fix filtering in PR preview |
| `src/gh_link_auditor/pipeline/state.py` | ReplacementCandidate tier field |
| `src/gh_link_auditor/pr_tracker.py` | Trust tracking on merge |
| `tests/unit/test_trust_escalation.py` | 61 new tests |

## Trust Level Transitions

```
new -> tier1_pending (first PR submitted -- future work)
new/tier1_pending -> tier1_proven (first PR merged)
tier1_proven -> tier2_eligible (14 days after first merge)
```

## Backward Compatibility

- `ReplacementCandidate` uses `total=False`, so existing code that doesn't
  set `tier` continues to work
- Trust lookups return "new" as default when no record exists
- All existing tests continue to pass (1639 total)
