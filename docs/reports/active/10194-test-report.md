# Test Report: HITL UX bundle (#194 + #195 + #196)

## Local verification

`poetry run python -m pytest --timeout=120 -q` → **1820 passed, 1 skipped**.

Pre-change baseline: 1807. Net +13 (4 in `TestGenerateGoogleSearches`, 3 in `TestBuildGithubSourceUrl`, 2 in `TestFormatVerdictWithGithubUrl`, 4 new entries in the existing `TestPromptUserApproval`).

## RED → GREEN

Tests added first failed with ``ImportError: cannot import name '_LIVE' / 'build_github_source_url' / 'generate_google_searches'``. After landing the helpers and the prompt-loop rewrite, all 66 tests in `test_n4.py` pass in 0.36s.

## Lint + format

`ruff check . && ruff format --check .` clean after one auto-reformat.

## Coverage

- `generate_google_searches`: 4 tests cover the multi-search return, site-scoped query, literal-URL triangulation, and bare-domain edge case.
- `build_github_source_url`: 3 tests cover the happy path and both missing-input paths.
- `format_verdict_for_review` with `github_source_url`: 2 tests cover present and absent cases.
- `prompt_user_approval`: `[l]` short and long form, `[g]` re-prompt + final answer, prompt text content. 4 new entries on top of the existing 11.

≥95% on changed lines.

## Behavior preserved

All pre-existing N4 tests (approve/reject/skip/exit/snooze/Ctrl+C/auto-approve/dry-run) pass unchanged.

## Out of scope

Real-operator integration test deferred to the next live audit run (Phase 4 retry).
