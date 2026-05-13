# Implementation Report: #178 hostile maintainer comment detection

## Summary

When a maintainer responds to one of our PRs with hostile language, we had no automated signal. The blacklist subsystem accepted `source="hostile"` from #150, but the actual detection was deferred. This PR ships the detection: a conservative keyword classifier runs against PR comments from maintainers (filtered by `author_association`); a hit inserts a `source="hostile"` blacklist row.

See LLD-178.

## Changes

### `src/gh_link_auditor/hostile_classifier.py` (NEW, 41 LoC)
- `HOSTILE_PHRASES` — tight tuple of 14 phrases. Bias is false-negative; the list grows by observation, not by guessing.
- `MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})`.
- `is_hostile_text(body)` — case-insensitive substring match against `HOSTILE_PHRASES`.
- `is_maintainer_comment(author_association)` — normalizes to uppercase, checks membership.

### `src/gh_link_auditor/pr_tracker.py`
- New `_fetch_pr_comments(owner, repo, pr_number)` — mirrors `_fetch_pr_status` pattern; calls `gh api repos/{owner}/{repo}/issues/{pr_number}/comments`.
- New `_find_hostile_comments(owner, repo, pr_number)` — fetches comments, filters by maintainer + hostile-text, returns matches sorted oldest-first. Swallows API failures (returns `[]`) so the outer `refresh_pr_outcomes` loop never aborts on a single bad fetch.
- `refresh_pr_outcomes` now scans for hostile comments on every open PR (before the existing unresponsive timeout branch). First hit per repo inserts a blacklist row with `source="hostile"` and `reason` containing the offending comment URL. Idempotent — `udb.is_blacklisted(repo_url)` guard prevents duplicate inserts.

## Tests

### `tests/unit/test_hostile_classifier.py` (NEW, 10 tests)
- `is_hostile_text`: clean text, empty, None, case-insensitive, phrase-in-context, every phrase hits, partial-word does not hit, unicode.
- `is_maintainer_comment`: OWNER / MEMBER / COLLABORATOR hit; CONTRIBUTOR / FIRST_TIME_CONTRIBUTOR / NONE / null / "" miss; lowercase normalized.
- Constants: maintainer set shape, no empty phrases.

### `tests/unit/test_pr_tracker.py` (extended)
- `TestFetchPrComments` (4 tests): success, empty, API failure, gh-not-found.
- `TestFindHostileComments` (6 tests): no comments, non-maintainer hostile ignored, maintainer non-hostile ignored, maintainer hostile returned, multiple hostile oldest-first, API failure swallowed.
- `TestRefreshPrOutcomes` (2 new):
  - `test_blacklists_on_hostile_comment` — mocked still-open PR + hostile maintainer comment ⇒ blacklist row inserted, reason contains the comment URL.
  - `test_hostile_blacklist_is_idempotent` — two consecutive refreshes ⇒ exactly one blacklist row.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/hostile_classifier.py` | NEW — classifier helpers + constants |
| `src/gh_link_auditor/pr_tracker.py` | new `_fetch_pr_comments`, `_find_hostile_comments`, hook into `refresh_pr_outcomes` |
| `tests/unit/test_hostile_classifier.py` | NEW — 10 tests |
| `tests/unit/test_pr_tracker.py` | 12 new tests (4 + 6 + 2) |
| `docs/lld/active/LLD-178.md` | NEW — design |

## Test count baseline

`pytest --co -q` collects **1795 tests** post-change (was 1764 + 31 new = 1795).

## Manual override

False positives can be removed by ID:

```
ghla blacklist list                # find the hostile-row id
ghla blacklist remove <id>         # delete
```

`ghla blacklist stats` groups by `source` and will show any `hostile` count.

## Out of scope

- **NLP-based classification.** The phrase list is the first pass. Expansion is a follow-up issue if false-negative rates become measurable.
- **Comments on commits or reviews.** Only issue-level PR comments are scanned; inline review comments are a separate API endpoint and rarely the venue for hostility.
- **Historical backfill.** Existing closed PRs are not rescanned for past hostile comments. Detection runs on the open-PR poll loop.
