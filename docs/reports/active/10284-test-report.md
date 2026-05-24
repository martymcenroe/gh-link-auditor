# 10284 - Test Report

**Issue:** #284
**Branch:** `284-preflight-toola-integration`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2315 passed, 1 skipped |
| After this PR | 2320 passed, 1 skipped |
| Net | +5 new tests |

## New tests

### `tests/unit/tools/test_derive_replacement_prs.py::TestPreflightIntegration` (5 tests)

Each test patches `tools.derive_replacement_prs.run_preflight` to inject a controlled verdict / score, then asserts the integration's skip reason / submission behavior.

1. `test_hard_gate_failed_skips_with_gate_name` — `HARD_GATE_FAILED` verdict with `gate_failure_name="anti_ai"` → `skipped` contains `("o/r", "preflight_gate_anti_ai")`; no submission
2. `test_needs_operator_review_skips` — `NEEDS_OPERATOR_REVIEW` → `skipped` contains `("o/r", "preflight_needs_review")`
3. `test_score_too_low_skips_with_score` — `PASS` verdict with `score=42` (< threshold 90) → `skipped` contains `("o/r", "preflight_score_42")`
4. `test_preflight_report_only_skips_all_without_filing` — even with `PASS` + high score, `--preflight-report-only` skips all with `preflight_report_only`; reports ARE written
5. `test_skip_preflight_bypasses_gate` — `HARD_GATE_FAILED` would normally skip, but `--skip-preflight=True` lets the PR through

## Modified existing tests

`tests/unit/tools/test_derive_replacement_prs.py`:
- `_make_args` helper — added `campaign_allowed=True`, `preflight_threshold=90`, `preflight_log_dir=<tempdir>`, `preflight_report_only=False`, `skip_preflight=False` defaults so existing TestDeriveAndSubmit tests continue to call `derive_and_submit` with a complete args namespace
- `TestBuildParser::test_defaults` — asserts the 4 new flag defaults (`preflight_threshold == 90`, `preflight_report_only is False`, `skip_preflight is False`, `preflight_log_dir is not None`)
- `TestBuildParser::test_explicit_flags` — added `--preflight-threshold 85 --preflight-log-dir /tmp/reports --preflight-report-only --skip-preflight` and asserts each (`Path` comparison normalizes per platform)

`tests/unit/tools/test_preflight_check.py`:
- `test_returns_preflight_report` — `assert report.score == DEFAULT_THRESHOLD` (was 0)
- `test_custom_threshold_passed_through` — also asserts `report.score == 85`
- `test_score_only_prints_int` — `assert out == str(DEFAULT_THRESHOLD)` (was `"0"`)

## Mocking

`unittest.mock.patch` is used to inject `run_preflight` stubs at the integration's import site (`tools.derive_replacement_prs.run_preflight`). This matches the existing test pattern in this file (e.g. `mock.patch("gh_link_auditor.pipeline.nodes.n1_scan.network_check_url", ...)`) and is acceptable per the codebase convention for patching internal-API call sites in tool tests. No MagicMock added to the codebase; `FakeSubagent` (from #287) is the typed-fake pattern preferred for new collaborators.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | 242 files already formatted |
| `poetry run ruff check .` | All checks passed |

## No regressions

Full suite (`poetry run pytest -q`): **2320 passed, 1 skipped**. The earlier-flaky `TestMigrationV2ToV3::test_migration_adds_columns_to_v2_table` (fixed in PR-β) remains stable.
