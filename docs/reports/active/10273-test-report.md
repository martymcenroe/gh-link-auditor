# Test Report: #273 derive_replacement_prs.py

## Verification

### Targeted

```
$ poetry run pytest tests/unit/tools/test_derive_replacement_prs.py -v
45 passed in 2.43s
```

### Full suite

```
$ poetry run pytest -q --tb=line
2203 passed, 1 skipped, 1 warning in 82.69s
```

No regressions. +45 from the new tool.

### Coverage

```
$ poetry run pytest tests/unit/tools/test_derive_replacement_prs.py \
    --cov=tools.derive_replacement_prs --cov-report=term-missing
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
tools\derive_replacement_prs.py     176      1    99%   363
```

The single uncovered line is the `if __name__ == "__main__": sys.exit(main())` guard. ≥95% bar met.

### Lint + format

```
$ ruff format --check tools/derive_replacement_prs.py tests/unit/tools/test_derive_replacement_prs.py
2 files already formatted
$ ruff check tools/derive_replacement_prs.py tests/unit/tools/test_derive_replacement_prs.py
All checks passed!
```

## Test strategy

End-to-end tests use a `fake_n6` callable injected via the `n6_fn=` kwarg on `derive_and_submit`. The fake returns the same `state` dict with `pr_url` set, simulating a successful PR submission without any real network/forking. This lets us assert the orchestration paths (blacklist skip, dup-PR skip, max-PRs cap, dry-run no-op, error propagation, surfaced=1 marking, pr_outcome insert) deterministically and in milliseconds.

Pure-compute helpers (`_row_to_fix`, `_row_to_verdict`, `_group_by_repo`, `_build_state`) are tested with hand-crafted row dicts — no DB needed.

DB tests use `tmp_path / "test.db"` and `UnifiedDatabase`, exercising the real schema (so any future schema migration that breaks these queries fails the tests).

The interactive `[y/n/s]` prompt is tested by injecting a stub `input_fn=` callable that returns canned responses.

## What's NOT tested

- The actual N6 fork+commit+PR machinery. That's covered by `n6_submit_pr`'s own tests; this tool just delegates to it.
- Real cross-fork PR creation against `api.github.com`. Live test only.
- Race conditions across concurrent invocations of this tool. v1 is sequential by design.
- Pathological row data (e.g., `repo_full_name=""`, NULL `dead_url`). Schema enforces these aren't NULL; if they ever were, derive_and_submit would propagate the row to N6 which would fail and we'd see it in the errors summary.

## Runtime verification (post-merge)

Operator runs:

```
poetry run python tools/derive_replacement_prs.py --dry-run
```

— sees a preview of every candidate repo with its fixes. No forking happens. Then:

```
poetry run python tools/derive_replacement_prs.py --auto-approve --max-prs 5
```

— files up to 5 PRs without prompts. Watch the operator's GitHub notifications. After PR submission, `ghla metrics refresh` polls outcomes.

The 143 carried-over candidates can be drained one batch at a time with `--max-prs`.

## Out of scope

- Performance test on the 143-candidate corpus. Sequential one-at-a-time submission with rate-limited GitHub calls — expected ~30s-2min per PR (fork + clone + push + create). Not a unit-test concern.
- Concurrent submission. Tool is sequential; one PR at a time. Future enhancement.
