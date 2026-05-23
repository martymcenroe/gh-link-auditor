# 10256 — Test Report

**Issue:** #256
**Branch:** `256-dedup-log-handlers`

## Test results

### Scoped (touched files)

```
poetry run pytest tests/unit/test_logging_config.py tests/unit/test_check_links_fallback.py -v
33 passed in 0.10s
```

### Full suite

```
poetry run pytest tests/ -q
2,151 passed, 1 skipped, 0 failed in ~130s
```

(Pre-PR baseline ran 2,149 passed, 1 failed, 1 skipped. The failure was `test_fallback_is_logged` which this PR updates correctly — see below.)

## New tests added (2)

| Class | Test | Asserts |
|---|---|---|
| `TestSetupLogging` | `test_disables_propagation_to_root` | Returned logger has `propagate is False` |
| `TestSetupLogging` | `test_no_duplicate_output_when_root_has_basicconfig_handler` | End-to-end: with a root handler configured via `basicConfig`, a record logged through a `setup_logging`-configured module logger appears exactly once in captured output (NOT once via the module handler AND once via the root) |

## Existing tests modified (1)

`tests/unit/test_check_links_fallback.py::TestFallbackLogging::test_fallback_is_logged`

**Pre-PR:** used `caplog.at_level(logging.INFO)`. This implicitly assumed records would propagate from the `check_links` logger up to the root logger where caplog observes by default.

**Post-PR:** with `propagate=False` now applied by `setup_logging`, caplog can't see those records via root. Added `monkeypatch.setattr(check_links_logger, "propagate", True)` to restore propagation just for this test's scope. The assertion (`"falling back to GET" in caplog.messages`) is unchanged — it still validates the user-visible behavior (the message is emitted). Only the captor-attachment mechanism changed.

## RED → GREEN evidence

Before the production fix (just the new tests, no `propagate = False` in `logging_config.py`):

```
FAILED tests/unit/test_logging_config.py::TestSetupLogging::test_disables_propagation_to_root
FAILED tests/unit/test_logging_config.py::TestSetupLogging::test_no_duplicate_output_when_root_has_basicconfig_handler
============================== 2 failed, 31 passed in 0.12s ==============================
```

The end-to-end test's failure output literally showed the bug:

```
AssertionError: expected exactly one 'hello'; saw: '2026-05-23T07:24:42 | WARNING  | test_no_dup | hello\nROOT:hello\n'
```

After applying the `propagate = False` line: both new tests pass.

## Coverage

`src/logging_config.py` retains 100% line coverage. New `logger.propagate = False` line is exercised by every existing test that calls `setup_logging` (all 18 in `test_logging_config.py`).

## Lint / format

```
poetry run ruff format <files>
1 file reformatted, 2 files left unchanged

poetry run ruff check <files>
All checks passed!
```

## Regression analysis

Full test suite: 1 previously-failing test (`test_fallback_is_logged`) now passes after its caplog update. Zero new failures elsewhere.

The change in propagation behavior could theoretically affect any test that uses `caplog` to observe records from a `setup_logging`-configured module. A grep for `caplog.*setup_logging` or for module names that use setup_logging in test files turned up only the one test — confirming `test_fallback_is_logged` was the only at-risk site. All others either don't observe those modules via caplog or don't use `setup_logging`-configured loggers.

## Manual verification path (post-merge)

Tonight's Stage 3 launched the original `tools/finish_stage3.py` which still showed duplicate output. After this PR merges + operator re-launches Stage 3 (after Ctrl+C), the output stream contains single-format messages — no more `2026-05-23T07:16:59 | WARNING | archive_client | ...` immediately followed by `2026-05-23 07:16:59,159 [WARNING] archive_client :: ...`.
