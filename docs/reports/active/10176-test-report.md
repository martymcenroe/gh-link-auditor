# Test Report: #176 unify default DB paths

## Local verification

### Suite

`poetry run python -m pytest --timeout=120 -q` against the worktree post-change:

```
1757 passed, 1 skipped, 1 warning in 97.22s
```

The single warning is the pre-existing `langchain_core` / Pydantic V1 compat note on Python 3.14 (harmless, captured in memory).

### Targeted RED → GREEN

Before the production changes landed, the new `tests/unit/test_default_db_paths.py` was added and run against unchanged source:

```
9 collected
1 passed   (test_explicit_db_path_overrides — already worked)
8 failed   (every default-path site disagreed with DEFAULT_DB_PATH)
```

After the production changes landed:

```
9 passed in 0.06s
```

This is the proof of fix: the bug the issue describes (different defaults across sites) is what the failing tests exercise, and the fix makes them pass.

### Existing test updated in place

`tests/unit/pipeline/test_state.py::TestCreateInitialState::test_default_db_path` was asserting `"state.db" in state["db_path"]` — that asserted the legacy hardcoded path. Updated to compare against `str(DEFAULT_DB_PATH)`. The test name and intent are unchanged.

## CI verification

This PR is the first to merge through the `Test` workflow gate landed by #174. Expected behavior: `Lint` + `Test` + `auto-review` + `pr-sentinel` all pass; `mergeable_state` flips to `clean`; Cerberus auto-approves.

## Coverage

≥95% on changed lines (every production change is `import DEFAULT_DB_PATH` + a literal substitution; the new tests cover every site's default-resolution path).

Coverage XML uploads automatically as a CI artifact per `.github/workflows/test.yml`.

## Out of scope

- No data migration. Out-of-tree users with state at the old paths continue to work via explicit `--db-path`.
- Suite runtime on CI (~3.5 min for unit tests; full suite ~98s locally). Tracked separately as #180.
