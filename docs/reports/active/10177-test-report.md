# Test Report: #177 write tier1_pending after first PR submit

## Local verification

### Suite

`poetry run python -m pytest --timeout=120 -q`:

```
1764 passed, 1 skipped, 1 warning in 102.09s
```

Pre-change baseline (after #176 merge): 1758 tests. This PR adds 6 net (5 in `TestUpdateTrustOnSubmit`, 2 in `TestN6SubmitPr`; one of the test_n6 additions previously existed elsewhere as test_handles_fork_failure renamed-adjacent neighbor — net is +6).

### Targeted RED → GREEN

Before implementation, ran the new tests against unchanged source:

```
ImportError: cannot import name 'update_trust_on_submit' from 'gh_link_auditor.pr_tracker'
5 failed in 0.27s
```

After implementing the new function + n6 hook:

```
36 passed in 0.31s
```

(36 = 5 new + 31 existing n6/trust-escalation tests that now run together. Targeted subset.)

### Lint + format

```
poetry run ruff check .  -> All checks passed!
poetry run ruff format --check .  -> 187 files already formatted
```

## CI verification

This PR runs through the `Test` workflow gate landed by #174. Expected: all four checks (Lint, Test, auto-review, pr-sentinel/issue-reference) pass; `mergeable_state` flips to `clean`; Cerberus auto-approves.

## Coverage

`update_trust_on_submit` has direct tests for each branch of the state machine (none, new, tier1_pending, tier1_proven, tier2_eligible). The n6 hook has both happy-path (trust written) and failure-path (PR not aborted) tests. ≥95% coverage on changed lines.

## Out of scope

- `last_pr_at` timestamp field. Schema already has `total_prs` which we use; adding `last_pr_at` is a follow-up if needed.
- Reconciliation of existing on-disk DBs with repos stuck at "new" + open PRs. Most users have no on-disk DB because counts were broken before #176; a reconciliation tool would only matter for users who hand-curated state.
