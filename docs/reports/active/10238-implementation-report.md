# 10238 Implementation Report

**Issue:** #238
**Branch:** `238-language-filter`

## Changes

| File | Change |
|---|---|
| `src/gh_link_auditor/unified_db.py` | Schema bumped v5 → v6. Fresh `CREATE TABLE bulk_scan_repos` adds `detected_language TEXT`. New `_migrate_v5_to_v6()` does `ALTER TABLE ADD COLUMN` for existing DBs. Old `_migrate_v4_to_v5` fixed to set version=5, not SCHEMA_VERSION (which is now 6). |
| `src/gh_link_auditor/bulk_scan/language.py` (new) | `detect_repo_language(repo_full_name, client=None)`. Tries `README.md/rst/txt/`+plain via raw.githubusercontent.com (no GH API quota). Skips if text < 100 chars. Caps input at 5000 chars. Returns `None` on any failure. |
| `src/gh_link_auditor/bulk_scan/config.py` | `INCLUDE_LANGUAGES: frozenset[str] = frozenset({"en"})`. |
| `src/gh_link_auditor/bulk_scan/runner.py` | New `_load_repo_languages(db, run_id)` pre-loads the per-repo dict. New `_is_repo_language_included(detected, include)` helper (NULL → True). `run_investigation` filters each finding through this gate before investigating — non-English repos drop the finding row and increment a `skipped_non_english` counter logged at end-of-stage. |
| `tools/detect_repo_languages.py` (new) | One-shot enrichment tool. ThreadPoolExecutor; batches DB UPDATEs every 100 rows. Idempotent (only processes NULL rows). Prints language distribution at end. |
| `pyproject.toml` | Added `langdetect = "^1.0.9"` runtime dep. |
| `tests/unit/bulk_scan/test_language.py` (new) | 9 tests: en/zh/ja/ru detection, 404, short text, variant fall-through, HTTP error, empty body. |
| `tests/unit/bulk_scan/test_runner.py` | 6 new tests under `TestLanguageFilter`: helper truth table + `_load_repo_languages` + skip-non-english + null-passes. |
| `tests/unit/bulk_scan/test_storage.py` | Schema-version test bumped to 6; new tests for fresh-DB has-column and v5→v6 migration. |

## Behavior

- **`detect_repo_language("pallets/flask")`** → `"en"` (or whatever langdetect classifies the Flask README)
- **`detect_repo_language("yangxiaoge/tvbox_cust")`** → `"zh-cn"` (Chinese README)
- **Run with default `INCLUDE_LANGUAGES = {"en"}`:**
  - Repos with `detected_language = 'en'` → findings investigated normally
  - Repos with `detected_language = 'zh-cn'`, `'ja'`, `'ru'`, etc. → findings skipped, deleted from `bulk_scan_findings`
  - Repos with `detected_language = NULL` → findings investigated (safe default; never silently drop unclassified work)

## Operational sequence for the in-flight run

1. Land this PR (merge to main)
2. Operator pulls main in their working dir
3. Operator runs the enrichment tool (~3 min):
   ```bash
   poetry run python tools/detect_repo_languages.py --run-id bulk-20260514T042627
   ```
4. Operator resumes the run:
   ```bash
   poetry run python -m gh_link_auditor.cli.main bulk-scan start --run-id bulk-20260514T042627
   ```
   Stage 2 sees the existing cache + the run was operator-aborted; #229's `--resume-aborted` isn't implemented yet, so the operator may need to manually reset `bulk_scan_runs.status` from `aborted` back to `checking` (or `investigating`) first.

## Verification

- 121/121 bulk_scan tests pass (29 newly added)
- `ruff check` + `ruff format` clean
- Full suite verified (see test report)
- Smoke-test of langdetect against en/zh/ja/ru samples confirmed correct codes returned

## Out of scope

- `--include-languages` CLI flag (default `en` only; trivial follow-up)
- Stage 0 selection-time language filtering (future work — this PR is the retroactive Option C from #237)
- Automatic re-enrichment when detected_language is older than N days (future)
- Backporting detection to historical bulk-scan runs prior to v6 schema
