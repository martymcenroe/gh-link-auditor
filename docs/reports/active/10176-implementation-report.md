# Implementation Report: #176 unify default DB paths

## Summary

Before this PR the codebase had three different default DB paths. Whichever path the pipeline wrote to was not the path metrics read from, so `ghla metrics campaign` always reported zero counts even after a real campaign run. This PR consolidates every default-path site onto a single canonical constant (`unified_db.DEFAULT_DB_PATH = ~/.ghla/ghla.db`).

See LLD-176 for the design.

## Changes

### `src/gh_link_auditor/pipeline/state.py`
- `create_initial_state(db_path=None)` no longer hardcodes `~/.ghla/state.db`. Imports `DEFAULT_DB_PATH` from `unified_db` (lazy, inside the function) and uses it.

### `src/gh_link_auditor/cli/metrics_cmd.py`
- Removed module-local `DEFAULT_DB_PATH = Path("data/metrics/metrics.db")`. Imports the constant from `unified_db` instead. All three `--db-path` arguments (`campaign`, `refresh`, `scan-history`) flow through the same canonical default.

### `src/gh_link_auditor/cli/blacklist_cmd.py`
- Replaced four duplicated argparse-`default=None` + inline `args.db_path or str(Path.home() / ".ghla" / "ghla.db")` resolution sites with `default=str(DEFAULT_DB_PATH)`.
- Simplified `_get_db()` to use `args.db_path` directly (no inline fallback).
- Dropped now-unused `from pathlib import Path`.

### `src/gh_link_auditor/cli/recheck_cmd.py`
- Same pattern: `--db-path default=None` → `default=str(DEFAULT_DB_PATH)`; removed the `args.db_path or str(...)` fallback in `cmd_recheck`.
- Dropped now-unused `from pathlib import Path`.

### `src/gh_link_auditor/state_db.py`
- `StateDatabase.__init__(db_path: str = "state.db")` → `db_path: str | Path = DEFAULT_DB_PATH`. The legacy `"state.db"` (relative, no homedir prefix) was a stub default that only worked when the user ran from the project root.

### `tests/unit/pipeline/test_state.py`
- Existing `test_default_db_path` checked for `"state.db" in state["db_path"]` — that assertion encoded the old hardcoded default. Updated to assert equality with `DEFAULT_DB_PATH`.

### `tests/unit/test_default_db_paths.py` (NEW)
- 9 tests covering every site's argparse / function default. The class `TestPipelineMetricsRoundtrip` specifically asserts `create_initial_state(db_path=None)` and `metrics campaign`'s argparse default resolve to the same path — the bug this PR exists to fix.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/pipeline/state.py` | use `DEFAULT_DB_PATH` |
| `src/gh_link_auditor/cli/metrics_cmd.py` | import from `unified_db`, drop local literal |
| `src/gh_link_auditor/cli/blacklist_cmd.py` | argparse default + simplify `_get_db` |
| `src/gh_link_auditor/cli/recheck_cmd.py` | argparse default + simplify resolution |
| `src/gh_link_auditor/state_db.py` | constructor default uses `DEFAULT_DB_PATH` |
| `tests/unit/pipeline/test_state.py` | update existing test to new canonical |
| `tests/unit/test_default_db_paths.py` | NEW — 9 default-path tests |
| `docs/lld/active/LLD-176.md` | NEW — design |

## Migration

Out of scope per LLD §3.4. Existing users with on-disk state at `~/.ghla/state.db` or `data/metrics/metrics.db` continue to work by passing the explicit `--db-path` flag. A future tool can offer a copy-across; this PR does not auto-migrate.

## Test count baseline

`pytest --co -q` collects **1758 tests** post-change (was 1749 + 9 new = 1758; 1 existing test rewritten in place, no net change there). 1 test is skipped (pre-existing).
