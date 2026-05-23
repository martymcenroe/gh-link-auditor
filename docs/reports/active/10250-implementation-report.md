# 10250 — Implementation Report

**Issue:** #250 — fix(inventory): follow repo-rename 301 redirects on GitHub trees API
**Branch:** `250-follow-rename-301`
**LLD:** `docs/lld/active/LLD-250.md`

## Changes

### `src/gh_link_auditor/bulk_scan/inventory.py`

* New exception `RepoRenamed(new_full_name)` — carries the new ``full_name`` so callers can update state and retry.
* New helper `_resolve_renamed_repo(client, redirect_location)` — extracts `{repo_id}` from a `/repositories/{id}/...` Location header and looks up the current `full_name` via `/repositories/{id}`. Permissive: any failure returns `None` so the normal `raise_for_status` error path takes over.
* `_list_doc_files` now checks `r.status_code == 301` before `raise_for_status`. On a 301 with a resolvable Location, raises `RepoRenamed(new_full_name)`. Unresolvable 301s and all other non-2xx statuses propagate via `raise_for_status` unchanged.
* `inventory_repo` catches `RepoRenamed`, performs exactly one retry under the new name, and returns two new keys: `renamed_from` (the original argument or `None`) and `current_full_name` (the name under which inventory actually succeeded). Multi-rename chains (very rare) propagate the second `RepoRenamed` rather than looping.

### `src/gh_link_auditor/bulk_scan/storage.py`

* New helper `apply_repo_rename(db, run_id, old, new) -> bool`. Atomic transaction:
  1. Check for `(run_id, new)` PK collision; on collision, return `False` and log a warning.
  2. `UPDATE bulk_scan_repos SET repo_full_name = new, previous_full_name = old WHERE PK matches old`.
  3. `UPDATE bulk_scan_findings SET repo_full_name = new WHERE PK matches old` — keeps finding rows linked to the renamed repo.

### `src/gh_link_auditor/unified_db.py`

* `SCHEMA_VERSION` bumped 7 → 8.
* `previous_full_name TEXT` added to the bootstrap `CREATE TABLE bulk_scan_repos`.
* New `_migrate_v7_to_v8` performs an additive `ALTER TABLE … ADD COLUMN previous_full_name TEXT` and updates the version. Existing v6 → v7 migration's final `UPDATE schema_version` now sets v7 explicitly (instead of `SCHEMA_VERSION`) so the chain is correct.

### `src/gh_link_auditor/bulk_scan/runner.py`

* `run_inventory` now consumes the new keys: if `result["renamed_from"]` is set, calls `storage.apply_repo_rename`; on success, the local `full_name` is rebound so subsequent `update_repo_inventory` + `add_finding` calls land under the new name. On PK-collision (apply returns `False`), the loop falls back to the old name — better to inventory under the wrong name than lose the row.

### Tests

* `tests/unit/bulk_scan/test_inventory_rename.py` (new) — 14 tests:
  * 2 for `RepoRenamed` (carries new_full_name, repr is informative)
  * 5 for `_resolve_renamed_repo` (success, no-id-in-location, lookup 404, no full_name in response, network error)
  * 4 for `_list_doc_files` 301 detection (raise on resolvable 301, fall through on unresolvable, 404 unchanged, 200 unchanged)
  * 3 for `inventory_repo` retry behavior (rename + success, no rename, double rename propagates)
* `tests/unit/bulk_scan/test_storage_rename.py` (new) — 8 tests:
  * 3 for schema v8 (fresh DB has column, version constant, v7 → v8 migration adds column)
  * 4 for `apply_repo_rename` (success path with previous_full_name, propagation to findings, PK collision returns False, same-name no-op)
  * 1 for runner integration (end-to-end `run_inventory` flips the row + writes findings under the new name)
* `tests/unit/bulk_scan/test_storage.py` — assertion bumped from `SCHEMA_VERSION == 7` to `== 8`.
* `tests/unit/bulk_scan/test_inventory_sanitize.py` (from #251) — `_FakeTreeResp` gained `status_code` and `headers` fields so the new 301 check works without breaking existing tests.

## Behavior change summary

| Input | Before | After |
|---|---|---|
| Repo not renamed (common) | Normal flow | Normal flow — `renamed_from=None`, zero new code touched |
| Repo renamed once on GitHub | `HTTPStatusError("301 Moved Permanently")` → repo errored | `RepoRenamed` raised → caught → re-fetch by new name → DB row + findings re-keyed → inventoried |
| Repo renamed twice during selection window | Same — errored | Second `RepoRenamed` propagates → errored. Acceptable. |
| 301 with garbled Location header | Errored | `_resolve_renamed_repo` returns None → `raise_for_status` fires normally → errored |
| 301 → `/repositories/{id}` 404 | (Wouldn't have made the second call) | `_resolve_renamed_repo` returns None → normal error path |
| PK collision (new name already in run) | n/a | `apply_repo_rename` returns False → caller continues under old name |

## Net effect on tonight's failure mode

`ElliottYan/LUFFY` and `tukuaiai/tradecat` will now be picked up cleanly when Stage 1 is re-run against `bulk-20260514T042627Z`. Their DB rows will have:
- `repo_full_name` = the new owner/name returned by `/repositories/{id}`
- `previous_full_name` = the old name (forensic record)
- `status` = `'inventoried'`

Any future runs that select the new name directly will hit it without a rename detour.

## Out of scope (per LLD)

* Updating `tools/finish_stage1.py` (not in test suite; future re-runs will benefit via the package fix once we update it as part of the audit pass).
* Multi-rename chains (rare; second `RepoRenamed` propagates).
* Reverse lookup index (`previous_full_name → current_full_name`).
* Resetting status of previously-errored repos in old DBs (operator-driven).
