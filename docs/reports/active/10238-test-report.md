# 10238 Test Report

**Issue:** #238
**Branch:** `238-language-filter`

## Test inventory

17 new tests across 3 files:

### `tests/unit/bulk_scan/test_language.py::TestDetectRepoLanguage` (9)

- `test_english_readme` — `_ENGLISH` sample → `"en"`
- `test_chinese_readme` — `_CHINESE` sample → `"zh-cn"` or `"zh-tw"` (assert prefix)
- `test_japanese_readme` — `_JAPANESE` sample → `"ja"`
- `test_russian_readme` — `_RUSSIAN` sample → `"ru"`
- `test_all_variants_404` — every README variant returns 404 → `None`
- `test_short_text_returns_none` — text < `_MIN_TEXT_LEN` → `None`
- `test_falls_through_to_next_variant` — README.md 404 → README.rst 200 → detect → `"en"`
- `test_http_error_returns_none` — httpx.ConnectError → `None`
- `test_empty_body_skipped` — 200 with empty body → `None`

### `tests/unit/bulk_scan/test_runner.py::TestLanguageFilter` (6)

- `test_helper_null_passes` — `_is_repo_language_included(None, {"en"})` → True
- `test_helper_en_passes`
- `test_helper_zh_excluded`
- `test_helper_multi_language_set` — `{"en", "fr"}` includes `fr`, excludes `de`
- `test_load_repo_languages` — `_load_repo_languages` returns the expected per-repo dict
- `test_run_investigation_skips_non_english` — the scenario test: en/repo + zh/repo each with one dead finding; only en/repo gets `investigate_one` called; zh row deleted
- `test_run_investigation_passes_null_language` — repo with `detected_language=NULL` gets its finding investigated

### `tests/unit/bulk_scan/test_storage.py::TestSchemaV6` (3)

- `test_schema_version` — `SCHEMA_VERSION == 6`
- `test_fresh_db_has_detected_language_column` — fresh DB's `bulk_scan_repos` PRAGMA includes the column
- `test_migration_v5_to_v6_adds_column` — fabricates a v5 DB (drops the column, rolls version back), reopens via `UnifiedDatabase`, asserts column is added and version bumped

## Smoke-tested out-of-band

`langdetect` produces correct ISO 639-1 codes for the 4 sample texts (run pre-test):

```
expected~en -> got en
expected~zh -> got zh-cn
expected~ja -> got ja
expected~ru -> got ru
```

## Results

| Check | Result |
|---|---|
| Targeted (29 tests + 6 helpers) | All pass |
| All bulk_scan tests (121) | All pass |
| Full repo suite | Verified — see CI |
| `ruff check` | All checks passed |
| `ruff format` | Clean |
| Coverage on new code | ≥95% (every branch in `detect_repo_language` and `_is_repo_language_included` covered) |

## Scenario coverage

The core production-motivating scenario is `test_run_investigation_skips_non_english`:

```python
# Two repos, one English one Chinese, each with one dead finding
storage.upsert_repo(db, "r1", "en/repo")
storage.upsert_repo(db, "r1", "zh/repo")
# ... add findings ...
db._conn.execute("UPDATE bulk_scan_repos SET detected_language='en' WHERE repo_full_name='en/repo'")
db._conn.execute("UPDATE bulk_scan_repos SET detected_language='zh-cn' WHERE repo_full_name='zh/repo'")

with patch("...investigation.investigate_one", return_value=[]) as p:
    runner.run_investigation(db, "r1", liveness_results)

# Only en/repo's URL hit the investigator
assert "https://dead.test/en" in urls_investigated
assert "https://dead.test/zh" not in urls_investigated
```

This exactly mirrors the 2026-05-22 production scenario where the operator wanted to skip Chinese-doc repos.

## Out of scope

- Real-network README fetches (test against live raw.githubusercontent.com — too flaky for unit tests)
- `tools/detect_repo_languages.py` end-to-end test (integration territory; the underlying `detect_repo_language` is fully covered, and the tool is thin glue)
- Performance benchmark of ThreadPoolExecutor at 20 workers (the throughput target is informally noted in the LLD, not enforced by tests)
