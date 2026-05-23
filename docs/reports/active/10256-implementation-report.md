# 10256 — Implementation Report

**Issue:** #256 (Part B — dedup log handler output)
**Branch:** `256-dedup-log-handlers`
**LLD:** `docs/lld/active/LLD-256.md`

## Changes

### `src/logging_config.py`

One added line inside `setup_logging`:

```python
logger.propagate = False
```

Placed immediately after the handler-clear block, before level configuration. Comment references #256 and explains the user-pain symptom (duplicate output observed in `tools/finish_stage*.py` output streams).

### `tests/unit/test_logging_config.py`

Two new tests in `TestSetupLogging`:

- `test_disables_propagation_to_root` — direct assertion that the returned logger has `propagate is False`.
- `test_no_duplicate_output_when_root_has_basicconfig_handler` — end-to-end anti-regression test:
  - Sets up a root handler via `logging.basicConfig(format="ROOT:%(message)s", force=True)`.
  - Configures a module logger via `setup_logging(...)`.
  - Logs one message.
  - Asserts the message appears exactly once in captured output AND the root handler's `"ROOT:"` prefix is NOT present (proof that propagation didn't fire).

### `tests/unit/test_check_links_fallback.py`

One test updated: `test_fallback_is_logged`. The pre-existing test used `caplog.at_level(logging.INFO)` which relies on pytest's caplog observing records via the root logger's propagation. With `propagate=False` now applied on `setup_logging`-configured loggers, caplog can't see records from `check_links` through root anymore.

Fix: use `monkeypatch.setattr(check_links_logger, "propagate", True)` to restore propagation just for this test. The test still verifies user-visible behavior (a log message is emitted); the monkeypatch is purely about reaching pytest's captor. Comment explains the #256 context.

## Behavior change

| Scenario | Before | After |
|---|---|---|
| Module configured via `setup_logging` + root has `basicConfig` handler | Records printed twice (once by module handler, once by root handler via propagation) | Records printed once (by module handler only) |
| Module configured via `setup_logging`, no root setup | Records printed once (by module handler) | Records printed once (by module handler) — unchanged |
| `caplog` capturing module-logger records | Captured via propagation | Not captured by default; tests that need it must restore propagation or attach caplog to the specific logger explicitly |
| `setup_logging` called twice on same name | Handlers cleared and re-added | Same — propagate=False each time (idempotent) |

## Net effect on tonight's Stage 3 log spam

After this PR + the prior `tools/finish_stage*.py` patch:

- LinkDetective module loggers (`archive_client`, `github_resolver`, `link_detective`, `redirect_resolver`, `policy_checker`) are silenced to ERROR by the tool. Most noise gone.
- For any record they DO emit at ERROR level (genuinely error-class events worth seeing), it'll print once via their own handler, not twice via propagation.

The `2026-05-23 07:16:59,159 [WARNING]` vs `2026-05-23T07:16:59 | WARNING` dual-format spam the operator saw is permanently gone.

## Tests

```
poetry run pytest tests/unit/test_logging_config.py tests/unit/test_check_links_fallback.py -v
33 passed in 0.10s
```

Full suite: 2,151 tests, 1 skipped, 0 failures. (Pre-PR baseline was 2149 + 1 skipped + 1 failing.) The previously-failing `test_fallback_is_logged` is now correctly updated and passing.

## Out of scope (deferred follow-up)

- Migration of `src/logging_config.py` into the package as `src/gh_link_auditor/logging_config.py` and updating the 5 import sites from `from src.logging_config` to `from gh_link_auditor.logging_config`. That removes the `sys.path` hack in the bulk-scan tools and is the "Part C" cleanup from #256. Independent of this fix.
