# Implementation Report: #200 anti-AI phrase classifier

## Summary

Pallets/flask PR #6019 was closed by maintainer davidism (MEMBER) with:

> "Happy to update this, but please do not use genAI to generate or submit a PR."

This is a polite-but-firm anti-AI policy stated in a PR comment. The existing `hostile_classifier` (#178) matches only openly hostile language (`fuck off`, `spammer`, `stop opening prs`). The polite phrasing here didn't match anything — auto-detection missed it. The operator had to manually blacklist with `source="policy"` after reading the comment.

This PR adds a parallel `anti_ai` classifier so future cases get caught automatically. Distinct from `hostile` because the text class is different (rejection-with-civility vs. abuse), and `source="anti_ai"` lets the metrics dashboard distinguish.

## Changes

### `src/gh_link_auditor/hostile_classifier.py`

- New `ANTI_AI_PHRASES` tuple (20 entries). Seed from real maintainer language: `do not use genai`, `please don't use ai`, `no ai-generated`, `no llm`, `no automated pr`, `don't automate`, etc. Bias: false negatives over false positives (same as hostile).
- New `is_anti_ai_text(body) -> bool`. Mirrors `is_hostile_text`. Case-insensitive substring match.
- Module docstring updated to mention #200.

### `src/gh_link_auditor/pr_tracker.py`

- New `_find_anti_ai_comments(owner, repo, pr_number) -> list[dict]`. Mirrors `_find_hostile_comments`: maintainer-filter, oldest-first sort, swallow-API-failure.
- `refresh_pr_outcomes` updated: after the hostile-check, if no hostile hits, also try anti-AI. On match, blacklist with `source="anti_ai"` and a reason linking to the offending comment URL.

The else-branch ensures we don't double-blacklist when a comment is both hostile AND anti-AI (rare, but possible). Hostile wins (more severe signal).

### Tests

- `tests/unit/test_hostile_classifier.py` — new `TestIsAntiAiText` class (8 tests) + 1 new constant-shape test. Covers clean text, empty, None, the real pallets/flask comment, case-insensitivity, every phrase hits, and orthogonality with `is_hostile_text`.
- `tests/unit/test_pr_tracker.py` — new `TestFindAntiAiComments` class (4 tests) + `test_blacklists_on_anti_ai_comment` integration test using the actual pallets/flask wording.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/hostile_classifier.py` | `ANTI_AI_PHRASES` + `is_anti_ai_text` |
| `src/gh_link_auditor/pr_tracker.py` | `_find_anti_ai_comments` + integration in `refresh_pr_outcomes` |
| `tests/unit/test_hostile_classifier.py` | new TestIsAntiAiText (8 tests) + constant-shape |
| `tests/unit/test_pr_tracker.py` | new TestFindAntiAiComments (4 tests) + integration (1 test) |
| `docs/lld/active/LLD-200.md` | NEW design (concise) |

## Test count

`pytest --co -q` collects **1842 tests** post-change (was 1828, +14 net).

## Operator impact

Future audits where the maintainer responds with anti-AI language will auto-blacklist the repo without operator action. The `ghla blacklist stats` output now distinguishes between `hostile` (rude rejection) and `anti_ai` (polite policy rejection) sources, giving the operator clearer triage signal.

## Companion to #178 and the closed-PR-scan gap (#201)

#178 catches rude rejection. #200 catches polite rejection. Both still only fire on **open** PRs today — closed PRs aren't rescanned. That gap is tracked separately as #201 and would have caught the pallets/flask case in real time.
