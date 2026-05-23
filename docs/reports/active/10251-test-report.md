# 10251 — Test Report

**Issue:** #251
**Branch:** `251-sanitize-doc-paths`

## Test results

```
poetry run pytest tests/unit/bulk_scan/test_inventory.py tests/unit/bulk_scan/test_inventory_sanitize.py -v
============================= 26 passed in 0.07s =============================
```

```
poetry run pytest tests/unit/bulk_scan/ -v
============================= 146 passed in 8.90s =============================
```

All 12 new tests pass GREEN. All 134 pre-existing `bulk_scan` tests still pass — no regressions.

## New tests added (12)

`tests/unit/bulk_scan/test_inventory_sanitize.py`:

| Class | Test | Asserts |
|---|---|---|
| `TestListDocFilesSanitizesPaths` | `test_drops_path_with_newline` | `\n` in path → entry dropped |
| | `test_drops_path_with_carriage_return` | `\r` in path → entry dropped |
| | `test_drops_path_with_tab` | `\t` in path → entry dropped |
| | `test_drops_path_with_null_byte` | `\x00` in path → entry dropped |
| | `test_keeps_normal_doc_paths` | Plain `.md`/`.rst`/`.txt`/`.adoc` all kept; non-docs filtered by extension |
| | `test_empty_tree_returns_empty_list` | Empty tree → empty result |
| `TestFetchRawURLEncodesPath` | `test_encodes_space_in_path` | Space → `%20` |
| | `test_encodes_hash_in_path` | `#` → `%23` |
| | `test_encodes_question_mark_in_path` | `?` → `%3F` |
| | `test_keeps_directory_separators_literal` | `/` not encoded |
| | `test_normal_ascii_path_unchanged` | `README.md` URL unchanged from prior behavior |
| `TestInventoryRepoSurvivesPathologicalFilename` | `test_inventory_returns_normal_files_even_when_pathological_present` | End-to-end: mixed tree returns clean inventory, raw client sees only safe URLs |

## RED → GREEN evidence

Before implementation:

```
=========================== short test summary info ===========================
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestListDocFilesSanitizesPaths::test_drops_path_with_newline
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestListDocFilesSanitizesPaths::test_drops_path_with_carriage_return
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestListDocFilesSanitizesPaths::test_drops_path_with_tab
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestListDocFilesSanitizesPaths::test_drops_path_with_null_byte
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestFetchRawURLEncodesPath::test_encodes_space_in_path
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestFetchRawURLEncodesPath::test_encodes_hash_in_path
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestFetchRawURLEncodesPath::test_encodes_question_mark_in_path
FAILED tests/unit/bulk_scan/test_inventory_sanitize.py::TestInventoryRepoSurvivesPathologicalFilename::test_inventory_returns_normal_files_even_when_pathological_present
========================= 8 failed, 4 passed in 0.20s =========================
```

After implementation: all 12 pass.

## Coverage

`src/gh_link_auditor/bulk_scan/inventory.py`: 78% line coverage overall.

**New code added by this PR is 100% covered.** The 22% miss is in pre-existing functions this PR does not touch:

* `_clean_url_tail` edge case (line 50)
* `_fetch_raw` exception handler and non-200 branches (lines 131, 139-140)
* `inventory_repo` `MAX_URLS_PER_REPO` early-exit branches (lines 155-157, 206-214)
* `build_api_client` env-fallback (lines 178-188) — requires env var manipulation
* `build_raw_client` trivial httpx client constructor (line 218)

None of these lines were modified or affected by this PR.

## Lint / format

```
poetry run ruff format src/gh_link_auditor/bulk_scan/inventory.py tests/unit/bulk_scan/test_inventory_sanitize.py
2 files left unchanged

poetry run ruff check src/gh_link_auditor/bulk_scan/inventory.py tests/unit/bulk_scan/test_inventory_sanitize.py
(clean, no errors)
```

(Two initial ruff errors — unused `httpx` import and import-block ordering — auto-fixed via `ruff check --fix`.)

## Manual verification path (post-merge)

Operator can confirm the fix works against real data by re-running:

```
poetry run python tools/finish_stage1.py --run-id bulk-20260514T042627Z
```

`guestrin-lab/deepscholar` should land in `'inventoried'` status with its non-pathological doc files extracted, where previously it was stuck at `'error'` with the `InvalidURL` message.
