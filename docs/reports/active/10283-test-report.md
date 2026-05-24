# 10283 - Test Report

**Issues:** #283, #285, #286, #287
**Branch:** `283-preflight-infra-bundle`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2247 passed, 1 skipped |
| After this PR | 2315 passed, 1 skipped |
| Net | +68 new tests |

## New tests

### `tests/unit/tools/test_preflight_check.py` (13 tests, #283)

- `TestBuildParser` (3): required `--repo`, default flags, explicit flags
- `TestMakeRunId` (1): generated `preflight-<ts>-<6hex>` format
- `TestRunPreflightScaffold` (4): returns PreflightReport, custom threshold, explicit run_id, candidate-dict copy
- `TestMain` (6): exit 0 on pass, --strict on pass, --score-only int output, --report writes both files, DEFAULT_REPORT_DIR path checks

### `tests/unit/preflight/test_subagent.py` (22 tests, #287)

- `TestParseVerdictToken` (10): every valid token + uppercase + whitespace + empty + unknown → UNCERTAIN + first-line-only
- `TestAntiAiKeywordFallback` (5): clean / hit → UNCERTAIN / empty / None / case-insensitive
- `TestRealSubagent` (6): missing claude, timeout, non-zero exit, parsed verdict (asserts `CLAUDECODE=""` in env), unreadable prompt, `is_available()` reflects shutil.which
- `TestFakeSubagent` (4): default verdict, per-prompt overrides, records every call, copies context dict (mutation safety)

### `tests/unit/preflight/test_report.py` (12 tests, #286)

- `TestPreflightVerdict` (1): enum values
- `TestPreflightReportDataclass` (2): timestamps auto-populate; explicit timestamps preserved
- `TestRenderMarkdown` (6): pass minimal, operator-review banner, skip-preflight banner, gate rows, score rows with total, operator links
- `TestRenderJson` (2): valid JSON; includes gates + scores
- `TestSaveReport` (3): writes both files, creates parent dir, content matches renderers

### `tests/unit/test_unified_db.py::TestPreflightCaches` (12 tests, #285)

- `test_all_preflight_tables_exist`
- PR stats: write/read roundtrip, miss, expired (`ttl_days=0`), replace on recompute
- Repo meta: write/read roundtrip, archived/disabled/license null, miss, expired (`ttl_hours=0`)
- AI scan: write/read roundtrip, miss on different SHA, miss on different file, replace for same key

### `tests/unit/test_unified_db.py::TestMigrationV8ToV9` (2 tests, #285)

- `test_migrate_creates_preflight_tables` — manually downgrade schema_version to 8, drop new tables, re-open, verify migration creates them
- `test_migrate_is_idempotent_on_re_open` — two consecutive opens both leave version at current SCHEMA_VERSION

## Modified existing tests

`tests/unit/bulk_scan/test_storage.py`:
- `TestSchemaV7::test_schema_version` — `assert SCHEMA_VERSION == 8` → `assert SCHEMA_VERSION == 9`

## No MagicMock added

- `RealSubagent` tests use `mock.patch` to stub `subprocess.run` / `shutil.which` — these are external boundaries, not collaborators, so `mock.patch` is acceptable per the codebase pattern (same approach as `tests/unit/test_network.py`)
- `FakeSubagent` is a typed dataclass with `.calls` recording (NO MagicMock; follows the `tests/fakes/http.py:FakeHTTPResponse` pattern)

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | 242 files already formatted |
| `poetry run ruff check .` | All checks passed |

## Coverage on new production code

| Module | Tests covering it |
|---|---|
| `gh_link_auditor.preflight.subagent` | `TestParseVerdictToken` (10) + `TestAntiAiKeywordFallback` (5) + `TestRealSubagent` (6) + `TestFakeSubagent` (4) = 25 tests |
| `gh_link_auditor.preflight.report` | `TestPreflightVerdict` + `TestPreflightReportDataclass` (2) + `TestRenderMarkdown` (6) + `TestRenderJson` (2) + `TestSaveReport` (3) = 14 tests |
| `tools.preflight_check` | `TestBuildParser` (3) + `TestMakeRunId` + `TestRunPreflightScaffold` (4) + `TestMain` (6) = 14 tests |
| `unified_db` preflight caches | `TestPreflightCaches` (12) + `TestMigrationV8ToV9` (2) = 14 tests |

All new lines exercised by at least one test. Project hard rule ≥95% met.

## No regressions

`poetry run pytest -q` reports **2315 passed, 1 skipped**. The previously-flaky `TestMigrationV2ToV3::test_migration_adds_columns_to_v2_table` was tripping on the longer v2→v9 migration chain when `_migrate_v8_to_v9` re-called `_create_all_tables` (Windows tempdir / sqlite lock race). Switched to narrow CREATE-TABLE-only migration; test now passes.
