# Test Report: #200 anti-AI phrase classifier

## Local verification

`poetry run python -m pytest --timeout=120 -q` → **1842 passed, 1 skipped**.

Pre-change baseline: 1828. Net +14 (8 in `TestIsAntiAiText`, 4 in `TestFindAntiAiComments`, 1 integration test in `TestRefreshPrOutcomes`, 1 new constant-shape test).

## RED → GREEN

The new tests failed with `ImportError: cannot import name 'is_anti_ai_text' / 'ANTI_AI_PHRASES'` before the classifier was added. After landing the phrase list + helper + `_find_anti_ai_comments` + `refresh_pr_outcomes` integration, all 75 tests in `test_hostile_classifier.py` + `test_pr_tracker.py` pass in 5.5s.

## Real-world coverage

The integration test (`test_blacklists_on_anti_ai_comment`) uses davidism's exact wording from pallets/flask #6019 — "Happy to update this, but please do not use genAI to generate or submit a PR." — and asserts the resulting blacklist row has `source="anti_ai"`. If we'd had this classifier yesterday, the operator wouldn't have needed to blacklist manually.

## Lint + format

`ruff check . && ruff format .` clean.

## Coverage

- `is_anti_ai_text`: every phrase hits, clean-text/None/empty paths, case-insensitivity, orthogonality with `is_hostile_text` (both directions). 8 tests.
- `_find_anti_ai_comments`: empty / non-maintainer / hit / API-failure swallow. 4 tests.
- `refresh_pr_outcomes` integration: 1 test confirming the full flow inserts the right blacklist row with the right source.

≥95% on changed lines.

## Out of scope

- Closed-PR scanning (tracked as #201) — anti-AI detection still only fires on open PRs. The pallets/flask comment came after PR close.
- Surfacing `anti_ai` in `ghla metrics campaign` dashboard with a friendly label.
