# 10208 - Implementation Report

**Issue:** #208 — `feat(classifier)`: fix-stealer diff-equivalence + maintainer-level blacklist DB
**Branch:** `208-fix-stealer-diff`

## Summary

PR-ζ: ships the diff-equivalence fix-stealer detector that complements the existing keyword-based `_check_maintainer_fixed`. When a maintainer closes our PR and then commits the **byte-equivalent URL substitution** as their own work, the new detector confirms it and auto-blacklists the **maintainer** (not just the repo) — so other repos that maintainer controls are also excluded from future PRs.

The canonical case: `pallets/flask#6019` / `davidism` (2026-05-13). Maintainer closed our PR with anti-AI language, then committed our exact fix 8 minutes later. The existing keyword heuristic would have caught it loosely; this PR adds the strict signal.

## What ships

### `_extract_pr_url_change(owner, repo, pr_number, *, gh_run=None)`
Parses `gh pr diff` output for a clean single-URL substitution. Returns `(dead_url, candidate_url)` tuple or `None` (multi-URL diffs, no-URL diffs, gh failures all defensively return `None` — the diff-equivalence path doesn't apply to them).

### `check_fix_steal_diff(owner, repo, pr_number, *, gh_run=None, gh_get=None, lookback_commits=20) -> tuple[bool, str | None]`
1. Extract the PR's URL swap (returns `(False, None)` if not parseable)
2. Fetch the most recent `lookback_commits` commits on the default branch
3. For each commit, fetch its diff and look for a byte-equivalent `-dead_url` / `+candidate_url` substitution
4. Return `(True, stealing_sha)` on first match, else `(False, None)`

### `refresh_pr_outcomes` integration

When the existing `_check_maintainer_fixed` (keyword) flags a fix-steal AND `check_fix_steal_diff` confirms it byte-for-byte:
- Outcome's `rejection_reason` upgraded to include the stealing commit SHA
- Maintainer added to blacklist (via the previously-unused `maintainer=` axis on `udb.add_to_blacklist`)
- Logged as `Auto-blacklisted MAINTAINER (diff-confirmed fix steal)`

This activates the maintainer-level plumbing in `unified_db.is_blacklisted(repo_url, maintainer)` that has been latent in the codebase. Hard gate #3 (#290) already passes maintainer to that function, so any candidate against a fix-stealer's other repos will now be blocked at preflight.

## Files

- `src/gh_link_auditor/pr_tracker.py` — added `_extract_pr_url_change`, `check_fix_steal_diff`; integrated into `refresh_pr_outcomes` after the keyword check; added `re` + `Any` imports
- `tests/unit/test_pr_tracker.py` — new `TestExtractPrUrlChange` class (4 tests) + new `TestCheckFixStealDiff` class (3 tests)

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2431 passed, 1 skipped (was 2424; +7 tests) |
| `poetry run ruff format --check .` + `ruff check .` | clean |
| `git grep banned regex` | 0 hits |
| Maintainer-blacklist plumbing actively populated | yes (via `udb.add_to_blacklist(maintainer=...)`) |
| Existing keyword-heuristic preserved | yes (used as the cheap pre-filter before the more expensive diff fetch) |

## Out of scope

- Replacing the keyword heuristic entirely (kept as the pre-filter to avoid burning API quota on the diff-fetch path for every closed PR)
- Persistent record of confirmed fix-steals beyond the blacklist entry — could be a follow-up issue if the operator wants per-maintainer trail analytics
- Reverse path (un-blacklisting a maintainer after time-decay) — not in this PR's scope
