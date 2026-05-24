# 10298 - Test Report

**Issues:** #298, #299, #300, #301, #303, #304
**Branch:** `298-preflight-scores-batch1`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2360 passed, 1 skipped |
| After this PR | 2378 passed, 1 skipped |
| Net | +18 new tests |

## New tests

`tests/unit/preflight/test_scores.py` (18 tests):

- `TestScoreC1` (2): full points when URL present; zero when absent
- `TestScoreC2` (3): full for single occurrence; partial for multi (with `multi_occurrence=True` evidence); zero when absent
- `TestScoreC3` (4): zero on no-op fix (dead == candidate); full on 4xx; partial on 5xx; partial on None
- `TestScoreC4` (3): full on 200; partial on redirect→final_url-shift; zero on 404
- `TestScoreC6` (2): full when brackets balanced; zero when replacement creates unbalanced parens
- `TestScoreC7` (3): full when only URL changes; full on multi-occurrence (length-delta math works for both); zero when dead_url missing
- `TestCorrectnessScoresRegistry` (1): registry has exactly 6 named callables

## Modified existing tests

`tests/unit/tools/test_derive_replacement_prs.py`:

- `TestDeriveAndSubmit._bypass_hard_gates` autouse fixture extended to also empty `CORRECTNESS_SCORES` (both `gh_link_auditor.preflight.scores` and `tools.derive_replacement_prs` bindings). Same rationale as PR-δ: tests of `derive_and_submit` should not invoke real scoring collaborators
- `TestMain._bypass_hard_gates` autouse fixture extended the same way
- `TestPreflightIntegration._make_fake_run_preflight` stub: accepts `**kwargs` to be forward-compatible with the new `score_components=` parameter that tool A now passes

## Dependency injection (no MagicMock)

Each score accepts `content_fetch` and/or `http_check` collaborator kwargs. Tests inject `lambda r, p: "...content..."` and `lambda url: {"status_code": ...}`. Production uses `_default_http_check` (`network.check_url`) and `_fetch_source_content` (`GitHubContentsClient`).

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | clean |
| `poetry run ruff check .` | clean (1 auto-fix: removed unused `difflib` import after C7 simplification) |

## Coverage

`src/gh_link_auditor/preflight/scores.py`: every score function has at least one full-points and one zero/partial-points test. The `_default_http_check` and `_fetch_source_content` helpers are covered by the bypass-fixture tests + the gate tests from PR-δ that exercise the same patterns. ≥95% line coverage met.

## No regressions

`poetry run pytest -q`: **2378 passed, 1 skipped**.
