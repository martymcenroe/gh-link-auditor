# Implementation Report: #265 logger silencing not taking effect in Stage 3 tools

## Summary

`finish_stage3.py` (and three sibling tools) calls `logging.getLogger("archive_client").setLevel(logging.ERROR)` to silence the LinkDetective module loggers. The silencing was *not actually taking effect* — every Stage 3 run filled the operator console with CDX warnings at WARNING level.

Root cause traced via a minimal repro:

1. `finish_stage3.py` imports `from gh_link_auditor.bulk_scan import investigation` at top — but `investigation.investigate_one()` does `from gh_link_auditor.link_detective import LinkDetective` **lazily inside the function**.
2. So `link_detective`, `archive_client`, etc. only get imported when the **first worker actually calls `investigate_one`** — which is after `main()`'s `setLevel(ERROR)` loop has already run.
3. The `setLevel(ERROR)` runs on loggers that have no handlers yet (`level=NOTSET`, `propagate=True`). The set takes effect at that instant.
4. Then the first worker triggers the lazy chain; `setup_logging("archive_client")` finally fires and **resets `level` to INFO** (and adds a StreamHandler).
5. WARNINGs now pass the logger-level filter and reach setup_logging's StreamHandler. Spam.

Probe output verifying the fix (`after eager imports (before silencing)`):

```
archive_client: level=INFO handlers=2 propagate=False
github_resolver: level=INFO handlers=2 propagate=False
link_detective: level=INFO handlers=2 propagate=False
policy_checker: level=INFO handlers=2 propagate=False
redirect_resolver: level=INFO handlers=2 propagate=False
```

`setup_logging` ran during the eager-import block. Then `setLevel(ERROR)` lands on a fully-configured logger and actually filters records.

## Changes

### `tools/finish_stage1.py`, `tools/finish_stage2.py`, `tools/finish_stage3.py`, `tools/detect_languages.py`

All four tools gain the same eager-import block right after the existing `sys.path` setup, before any other imports:

```python
from gh_link_auditor import (  # noqa: E402
    archive_client,  # noqa: F401
    github_resolver,  # noqa: F401
    link_detective,  # noqa: F401
    policy_checker,  # noqa: F401
    redirect_resolver,  # noqa: F401
)
```

These are the modules whose loggers the in-`main()` `for noisy in (...): setLevel(ERROR)` loop targets. Eager-importing them forces each module's top-level `logger = setup_logging("<name>")` to run NOW, before `main()`'s silencing.

### `src/gh_link_auditor/bulk_scan/host_blocklist.py` (NEW)

`finish_stage3.py` imports `is_blocklisted_host` from this module. The module was untracked in the working tree from a prior session. Bundling it here so CI's import-of-finish_stage3 doesn't fail. (It's the same content the operator's been running with for the last two days: 14 `ANTI_BOT_HUMANS_OK` + 2 `PIPELINE_AND_HUMANS_BLOCKED` hosts, browser-verified.)

## Why not fix setup_logging itself?

Two reasons:

1. **The current `setup_logging` semantic is "always reconfigure on call"** — it explicitly does `if logger.handlers: logger.handlers.clear()` then sets the level. That's intentional for callers that want to re-configure. Changing it to "preserve pre-existing levels" would silently affect any other caller.
2. **The eager-import fix is the same shape that already works for `httpx`/`httpcore`/`urllib3`** in the same silencing list — those module loggers don't have a `setup_logging` call, so their levels stay as set. Eager-importing the LinkDetective chain makes them behave the same way.

Filing a separate ticket if `setup_logging`'s "always reconfigure" semantic causes pain elsewhere — out of scope here.

## Files modified

| File | Change |
|------|--------|
| `tools/finish_stage1.py` | NEW (with #265 fix applied) |
| `tools/finish_stage2.py` | NEW (with #265 fix applied) |
| `tools/finish_stage3.py` | NEW (with #265 fix applied) |
| `tools/detect_languages.py` | NEW (with #265 fix applied) |
| `src/gh_link_auditor/bulk_scan/host_blocklist.py` | NEW (required dep of finish_stage3) |

All five were untracked in the working tree from the overnight session — first-time commit.

## Test count

Unchanged: **2158 passed, 1 skipped**. No new tests; the tools are standalone scripts and the fix is a structural import-order change verified by the repro probe.

## Coverage

`host_blocklist.py` is small and self-contained (~75 LoC, 1 frozenset + 1 helper). The helper has implicit coverage via every Stage 3 finding it filters. A dedicated unit test for it would be a follow-up; the operator's been running it in production for 48h without incident.

## Out of scope

- Refactor `setup_logging` to respect pre-existing levels. Different design conversation.
- Commit the other six tools from the working tree (probes, `derive_host_blocklist.py`, etc.) — that's the broader #258 phase 1 PR, which the operator wants done separately.
- Add unit tests for the four tool scripts. They run in worker-thread orchestration patterns that don't lend themselves to clean unit testing; integration is via the operator running them.
