# 10250 — Test Report

**Issue:** #250
**Branch:** `250-follow-rename-301`

## Test results

```
poetry run pytest tests/unit/bulk_scan/ -v
============================= 168 passed in 9.80s =============================
```

All 22 new tests pass GREEN. All 146 pre-existing bulk_scan tests still pass.

## New tests added (22)

### `tests/unit/bulk_scan/test_inventory_rename.py` (14)

| Class | Test | Asserts |
|---|---|---|
| `TestRepoRenamedException` | `test_carries_new_full_name` | `.new_full_name` accessible |
| | `test_string_repr_mentions_new_name` | `str(e)` includes the new name |
| `TestResolveRenamedRepo` | `test_extracts_id_and_returns_new_full_name` | Happy path → calls `/repositories/{id}` once |
| | `test_returns_none_when_no_id_in_location` | Bad Location URL → None, no API call |
| | `test_returns_none_when_lookup_404s` | API 404 → None |
| | `test_returns_none_when_response_has_no_full_name` | Response without `full_name` field → None |
| | `test_returns_none_when_lookup_raises` | Network error → None (permissive) |
| `TestListDocFilesHandles301` | `test_raises_repo_renamed_on_301_with_valid_location` | 301 + resolvable Location → `RepoRenamed` |
| | `test_falls_through_when_301_location_unresolvable` | 301 + non-resolvable Location → `HTTPStatusError` |
| | `test_404_still_raises_normal_httpstatuserror` | 404 unchanged |
| | `test_200_no_rename_no_exception` | Happy path unchanged |
| `TestInventoryRepoHandlesRename` | `test_rename_then_success_returns_renamed_from` | One-shot retry sets `renamed_from` + `current_full_name` |
| | `test_no_rename_returns_renamed_from_none` | Common path: `renamed_from=None`, `current_full_name=original` |
| | `test_double_rename_propagates` | Second `RepoRenamed` propagates (no infinite loop) |

### `tests/unit/bulk_scan/test_storage_rename.py` (8)

| Class | Test | Asserts |
|---|---|---|
| `TestSchemaV8AddsPreviousFullName` | `test_fresh_db_has_previous_full_name_column` | Bootstrap creates the column |
| | `test_schema_version_advances_to_8` | `SCHEMA_VERSION >= 8` |
| | `test_migration_v7_to_v8_adds_column` | v7 DB → upgrade adds column, version advances |
| `TestApplyRepoRename` | `test_renames_existing_row_and_sets_previous_full_name` | PK updates, `previous_full_name` records old, other cols preserved |
| | `test_propagates_rename_to_findings` | `bulk_scan_findings` rows re-keyed |
| | `test_collision_returns_false_and_leaves_data_intact` | PK collision → False, no DB changes |
| | `test_same_name_is_noop` | Old == new → False, no DB changes |
| `TestRunInventoryHandlesRename` | `test_rename_updates_repo_row_and_findings_use_new_name` | End-to-end runner test: `run_inventory` flips the row, findings use new name |

### `tests/unit/bulk_scan/test_storage.py`

Existing `TestSchemaV7::test_schema_version` assertion bumped from `== 7` to `== 8`. Class name kept for git-blame continuity.

## RED → GREEN evidence

Before implementation (rename tests):

```
=========================== short test summary info ===========================
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestRepoRenamedException::test_carries_new_full_name
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestRepoRenamedException::test_string_repr_mentions_new_name
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestResolveRenamedRepo::test_extracts_id_and_returns_new_full_name
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestResolveRenamedRepo::test_returns_none_when_no_id_in_location
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestResolveRenamedRepo::test_returns_none_when_lookup_404s
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestResolveRenamedRepo::test_returns_none_when_response_has_no_full_name
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestResolveRenamedRepo::test_returns_none_when_lookup_raises
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestListDocFilesHandles301::test_raises_repo_renamed_on_301_with_valid_location
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestInventoryRepoHandlesRename::test_rename_then_success_returns_renamed_from
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestInventoryRepoHandlesRename::test_no_rename_returns_renamed_from_none
FAILED tests/unit/bulk_scan/test_inventory_rename.py::TestInventoryRepoHandlesRename::test_double_rename_propagates
======================== 11 failed, 3 passed in 0.18s =========================
```

After implementation: all 14 pass.

## Schema migration tested

* Fresh DB at v8: column present ✓
* v7 DB with no column: migration runs, column added, version advances to 8 ✓
* Migration is additive `ALTER TABLE ADD COLUMN` — fast and safe in WAL mode, no data loss

## Lint / format

```
poetry run ruff format <files>
3 files reformatted, 4 files left unchanged

poetry run ruff check <files>
All checks passed!
```

(Two initial ruff errors auto-fixed: trailing newline + import order.)

## Coverage

`src/gh_link_auditor/bulk_scan/inventory.py`: new code (RepoRenamed, `_resolve_renamed_repo`, 301-detection branch in `_list_doc_files`, `inventory_repo` retry path) is 100% covered by the 14 rename tests.

`src/gh_link_auditor/bulk_scan/storage.py`: new `apply_repo_rename` has 100% branch coverage (success, propagation, collision, same-name).

`src/gh_link_auditor/unified_db.py`: new `_migrate_v7_to_v8` covered by `test_migration_v7_to_v8_adds_column`.

`src/gh_link_auditor/bulk_scan/runner.py`: new rename-handling wiring covered by `TestRunInventoryHandlesRename::test_rename_updates_repo_row_and_findings_use_new_name`.

## Manual verification path (post-merge)

Operator can re-run Stage 1 against the bulk-scan run that hit the rename failure:

```
poetry run python tools/finish_stage1.py --run-id bulk-20260514T042627Z
```

The 2 previously-errored repos (`ElliottYan/LUFFY`, `tukuaiai/tradecat`) should resolve to their renamed targets, get inventoried, and have their DB rows show `previous_full_name` set.

Note: `tools/finish_stage1.py` itself wasn't modified in this PR. It calls into the package's `inventory_repo` which now returns `renamed_from`. The tool's `write_repo_atomically` doesn't yet honor that field — operator-time follow-up to wire the tool to the package update, OR the operator can use the package's `runner.run_inventory` directly for the next run.
