# 1278 - Test Report

**Issue:** #278 — chore(scrub): remove A++/contribution-graph/harvest language from public surface
**Branch:** `278-scrub-public-surface`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2235 passed |
| After this PR | 2237 passed, 1 skipped |
| Net | +2 new tests |

## New tests

`tests/unit/tools/test_derive_replacement_prs.py::TestMain`:

1. **`test_main_refuses_without_campaign_allowed`** — calls `mod.main(["--db", db_path, "--dry-run"])` (no `--campaign-allowed`) and asserts return code `2` plus presence of `"--campaign-allowed flag is required"` and `"#278"` in stderr.
2. **`test_main_pause_message_mentions_flag_and_issue`** — checks the `_CAMPAIGN_PAUSED_MESSAGE` constant contains the flag name, the issue number, and the word "scrub", so future edits to the message preserve the operator's pointer back to #278.

## Modified existing tests

`tests/unit/tools/test_derive_replacement_prs.py`:

1. **`TestBuildParser::test_defaults`** — added `assert args.campaign_allowed is False`
2. **`TestBuildParser::test_explicit_flags`** — added `"--campaign-allowed"` to the parsed arg list; added `assert args.campaign_allowed is True`
3. **`TestMain::test_main_dry_run_exit_zero`** — added `"--campaign-allowed"` to the args (test would now exit 2 without it; the original intent was to exercise the dry-run path, which still needs the campaign flag to reach `derive_and_submit`)
4. **`TestMain::test_main_no_candidates`** — same: added `"--campaign-allowed"` to args

These edits restore the original test intent (exercise the dry-run / no-candidates path) under the new gate.

## Coverage on new production code

| Symbol | Lines added | Tests covering it |
|---|---:|---|
| `tools/derive_replacement_prs._build_parser` `--campaign-allowed` arg | 8 (one `p.add_argument(...)` block) | `TestBuildParser::test_defaults`, `TestBuildParser::test_explicit_flags` |
| `tools/derive_replacement_prs._CAMPAIGN_PAUSED_MESSAGE` constant | 7 (string content) | `test_main_pause_message_mentions_flag_and_issue`, `test_main_refuses_without_campaign_allowed` |
| `tools/derive_replacement_prs.main` gate (`if not args.campaign_allowed: ...`) | 3 (the `if`, `print`, `return`) | `test_main_refuses_without_campaign_allowed` (negative path); `test_main_dry_run_exit_zero` + `test_main_no_candidates` (positive path) |

All 18 new lines exercised by tests. Project hard rule ≥95% met.

## No regressions

`poetry run pytest -q` reports **2237 passed, 1 skipped** (was 2235 before). The single skipped test pre-dates this PR (live/integration marker). No tests were silenced, deleted, or `xfail`'d to hide a failure.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | 234 files already formatted |
| `poetry run ruff check .` | All checks passed |

## Mechanical scrub verification

`git grep -i -E '(A\+\+|PRs filed|contribution graph|green square|naked ambition)'` returns **zero hits** in tracked files. The plan's Phase A acceptance criterion is met.

## Out-of-scope test concerns (follow-up)

- Live integration test of the AndreaVidali smoke-test PR path (Phase B's preflight scope, not this PR)
- repo_scout "harvest" surface text needs separate test coverage if/when scrubbed (operator decision deferred)
